from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SingleRunLock:
    """Simple cross-platform lock based on atomic file creation.

    It prevents two collector processes from running at the same time.
    If the process crashes, delete the lock file manually.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.fd: int | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, f"pid={os.getpid()} time={utc_now_iso()}\n".encode("utf-8"))
        except FileExistsError as exc:
            raise RuntimeError(f"已有采集任务在运行。如确认没有运行，请删除锁文件：{self.path}") from exc
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class CollectorState:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                create table if not exists account_state (
                    account_url text primary key,
                    last_crawled_at text,
                    last_status text,
                    fail_count integer default 0,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists seen_videos (
                    video_url text primary key,
                    account_url text,
                    first_seen_at text not null,
                    last_seen_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists runs (
                    run_id text primary key,
                    started_at text not null,
                    finished_at text,
                    status text not null,
                    message text
                )
                """
            )

    def start_run(self, run_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "insert into runs(run_id, started_at, status) values(?, ?, 'running')",
                (run_id, utc_now_iso()),
            )

    def finish_run(self, run_id: str, status: str, message: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "update runs set finished_at=?, status=?, message=? where run_id=?",
                (utc_now_iso(), status, message[:2000], run_id),
            )

    def mark_account(self, account_url: str, status: str) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "select fail_count from account_state where account_url=?",
                (account_url,),
            ).fetchone()
            fail_count = int(row["fail_count"]) if row else 0
            if status == "ok":
                fail_count = 0
            else:
                fail_count += 1
            conn.execute(
                """
                insert into account_state(account_url, last_crawled_at, last_status, fail_count, updated_at)
                values(?, ?, ?, ?, ?)
                on conflict(account_url) do update set
                  last_crawled_at=excluded.last_crawled_at,
                  last_status=excluded.last_status,
                  fail_count=excluded.fail_count,
                  updated_at=excluded.updated_at
                """,
                (account_url, utc_now_iso(), status, fail_count, utc_now_iso()),
            )

    def choose_accounts(self, accounts: list[dict], limit: int) -> list[dict]:
        """Pick accounts least recently crawled, max `limit`."""
        with self.connect() as conn:
            enriched: list[tuple[str, int, dict]] = []
            for account in accounts:
                url = str(account.get("url") or "").strip()
                if not url:
                    continue
                row = conn.execute(
                    "select last_crawled_at, fail_count from account_state where account_url=?",
                    (url,),
                ).fetchone()
                last = row["last_crawled_at"] if row else ""
                fail_count = int(row["fail_count"]) if row else 0
                enriched.append((last or "", fail_count, account))
            enriched.sort(key=lambda x: (x[0], x[1]))
            return [x[2] for x in enriched[: max(1, limit)]]

    def is_seen(self, video_url: str) -> bool:
        if not video_url:
            return False
        with self.connect() as conn:
            row = conn.execute("select 1 from seen_videos where video_url=?", (video_url,)).fetchone()
            return bool(row)

    def mark_seen(self, account_url: str, video_url: str) -> None:
        if not video_url:
            return
        with self.connect() as conn:
            conn.execute(
                """
                insert into seen_videos(video_url, account_url, first_seen_at, last_seen_at)
                values(?, ?, ?, ?)
                on conflict(video_url) do update set last_seen_at=excluded.last_seen_at
                """,
                (video_url, account_url, utc_now_iso(), utc_now_iso()),
            )
