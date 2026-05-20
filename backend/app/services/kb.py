from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from app.schemas import KnowledgeCreate, KnowledgeItem


class KnowledgeBase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def add(self, item: KnowledgeCreate) -> KnowledgeItem:
        now = datetime.now(timezone.utc).isoformat()
        tags_json = json.dumps(item.tags, ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO knowledge_items(title, content, tags, created_at) VALUES (?, ?, ?, ?)",
                (item.title.strip(), item.content.strip(), tags_json, now),
            )
            conn.commit()
            new_id = int(cursor.lastrowid)
        return self.get(new_id)

    def get(self, item_id: int) -> KnowledgeItem:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM knowledge_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(f"Knowledge item {item_id} not found")
        return self._row_to_item(row)

    def list(self, limit: int = 30) -> List[KnowledgeItem]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_items ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def search_texts(self, query: str, limit: int = 8) -> List[str]:
        tokens = [x for x in query.replace("，", " ").replace("。", " ").split() if x]
        with self._connect() as conn:
            if not tokens:
                rows = conn.execute(
                    "SELECT title, content FROM knowledge_items ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                like = f"%{tokens[0]}%"
                rows = conn.execute(
                    """
                    SELECT title, content FROM knowledge_items
                    WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (like, like, like, limit),
                ).fetchall()
        return [f"标题：{row['title']}\n内容：{row['content']}" for row in rows]

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> KnowledgeItem:
        try:
            tags = json.loads(row["tags"] or "[]")
        except json.JSONDecodeError:
            tags = []
        return KnowledgeItem(
            id=int(row["id"]),
            title=row["title"],
            content=row["content"],
            tags=tags,
            created_at=row["created_at"],
        )
