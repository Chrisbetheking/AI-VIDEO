from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

VERSION = "10.40.8.3"
AUTH_ROOT = Path(
    os.getenv(
        "AI_VIDEO_DOUYIN_AUTH_ROOT",
        "/opt/ai-video/storage/douyin_auth_v10_40_8_3",
    )
)
SESSION_ROOT = AUTH_ROOT / "sessions"
PROFILE_STATE_ROOT = AUTH_ROOT / "profiles"
COLLECTOR_ROOT = Path(
    os.getenv(
        "AI_VIDEO_COLLECTOR_ROOT",
        "/opt/ai-video-worker/collector-local",
    )
)
PROFILE_ROOT = COLLECTOR_ROOT / "profiles"
COOKIE_ROOT = COLLECTOR_ROOT / "cookies"
LOGIN_WORKER = COLLECTOR_ROOT / "douyin_login_worker_v10_40_8_3.py"
COLLECTOR_PYTHON = Path(
    os.getenv(
        "AI_VIDEO_COLLECTOR_PYTHON",
        str(COLLECTOR_ROOT / ".venv/bin/python"),
    )
)
ALLOWED_PROFILES = {
    "company_main": "公司主号",
    "company_backup": "公司备用号",
    "personal_test": "个人测试号",
}
ACTIVE_STATES = {"starting", "opening_browser", "waiting_scan", "verifying"}
TERMINAL_STATES = {"logged_in", "failed", "timeout", "cancelled"}
_LOCK = threading.RLock()


def _now() -> float:
    return time.time()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _profile(value: Any) -> str:
    profile = str(value or "company_main").strip()
    if profile not in ALLOWED_PROFILES:
        raise HTTPException(400, f"不支持的隔离账号：{profile}")
    return profile


def _profile_state_path(profile: str) -> Path:
    return PROFILE_STATE_ROOT / f"{profile}.json"


def _session_path(session_id: str) -> Path:
    safe = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in {"_", "-"})
    if not safe:
        raise HTTPException(400, "无效登录会话 ID")
    return SESSION_ROOT / f"{safe}.json"


def _qr_path(session_id: str) -> Path:
    return SESSION_ROOT / f"{session_id}.png"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _verify_token(session: dict[str, Any], token: str) -> None:
    expected = str(session.get("token_hash") or "")
    actual = _token_hash(str(token or ""))
    if not expected or not secrets.compare_digest(expected, actual):
        raise HTTPException(403, "登录会话凭证无效或已过期")


def _pid_alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _cookie_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        rows = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return sum(1 for row in rows if row and not row.startswith("#") and "\t" in row)
    except Exception:
        return 0


def _latest_session_for_profile(profile: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for path in SESSION_ROOT.glob("douyin_login_*.json"):
        data = _read_json(path, {})
        if not isinstance(data, dict) or data.get("account_profile") != profile:
            continue
        if latest is None or float(data.get("updated_at") or 0) > float(latest.get("updated_at") or 0):
            latest = data
    return latest


def profile_status(account_profile: str = "company_main") -> dict[str, Any]:
    profile = _profile(account_profile)
    state = _read_json(_profile_state_path(profile), {})
    if not isinstance(state, dict):
        state = {}
    latest = _latest_session_for_profile(profile) or {}
    cookie_file = COOKIE_ROOT / f"{profile}.txt"
    count = _cookie_count(cookie_file)
    logged_at = float(state.get("logged_in_at") or 0)
    # 只信任登录 Worker 真正确认过的状态。Cookie 文件单独存在不能冒充登录成功。
    login_ok = bool(state.get("login_ok") is True and logged_at > 0 and count > 0)
    active = bool(
        latest
        and str(latest.get("status") or "") in ACTIVE_STATES
        and _pid_alive(latest.get("pid"))
    )
    return {
        "ok": True,
        "version": VERSION,
        "account_profile": profile,
        "account_name": ALLOWED_PROFILES[profile],
        "login_ok": login_ok,
        "logged_in_at": logged_at or None,
        "logged_in_at_iso": state.get("logged_in_at_iso") or "",
        "cookie_count": count,
        "profile_path": str(PROFILE_ROOT / profile),
        "cookie_path": str(cookie_file),
        "active_session": {
            "session_id": latest.get("session_id"),
            "status": latest.get("status"),
            "message": latest.get("message"),
            "updated_at": latest.get("updated_at"),
        } if latest else None,
        "session_active": active,
        "last_error": state.get("last_error") or "",
    }


def _public_session(session: dict[str, Any]) -> dict[str, Any]:
    status = str(session.get("status") or "starting")
    session_id = str(session.get("session_id") or "")
    return {
        "ok": status not in {"failed"},
        "version": VERSION,
        "session_id": session_id,
        "account_profile": session.get("account_profile"),
        "account_name": ALLOWED_PROFILES.get(str(session.get("account_profile")), ""),
        "status": status,
        "message": session.get("message") or "",
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "expires_at": session.get("expires_at"),
        "login_ok": status == "logged_in",
        "qr_ready": _qr_path(session_id).exists(),
        "screenshot_mode": session.get("screenshot_mode") or "",
        "error": session.get("error") or "",
    }


def _start_login(account_profile: str) -> dict[str, Any]:
    profile = _profile(account_profile)
    SESSION_ROOT.mkdir(parents=True, exist_ok=True)
    PROFILE_STATE_ROOT.mkdir(parents=True, exist_ok=True)
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    COOKIE_ROOT.mkdir(parents=True, exist_ok=True)

    if not LOGIN_WORKER.exists():
        raise HTTPException(503, f"登录 Worker 尚未安装：{LOGIN_WORKER}")
    if not COLLECTOR_PYTHON.exists():
        raise HTTPException(503, f"Collector Python 不存在：{COLLECTOR_PYTHON}")

    with _LOCK:
        latest = _latest_session_for_profile(profile)
        if latest and str(latest.get("status") or "") in ACTIVE_STATES and _pid_alive(latest.get("pid")):
            raise HTTPException(409, "当前隔离账号已有登录窗口，请继续扫码或先取消旧会话。")

        session_id = f"douyin_login_{profile}_{uuid.uuid4().hex[:14]}"
        token = secrets.token_urlsafe(32)
        created_at = _now()
        session = {
            "session_id": session_id,
            "account_profile": profile,
            "status": "starting",
            "message": "正在启动抖音扫码登录窗口",
            "created_at": created_at,
            "updated_at": created_at,
            "expires_at": created_at + 360,
            "token_hash": _token_hash(token),
            "pid": None,
        }
        session_path = _session_path(session_id)
        _atomic_json(session_path, session)
        log_path = SESSION_ROOT / f"{session_id}.log"
        log_file = log_path.open("ab")
        try:
            proc = subprocess.Popen(
                [
                    str(COLLECTOR_PYTHON),
                    str(LOGIN_WORKER),
                    "--session-file",
                    str(session_path),
                    "--account-profile",
                    profile,
                    "--timeout-seconds",
                    "360",
                ],
                cwd=str(COLLECTOR_ROOT),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={
                    **os.environ,
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONIOENCODING": "utf-8",
                },
            )
        finally:
            log_file.close()
        session["pid"] = proc.pid
        session["log_path"] = str(log_path)
        session["updated_at"] = _now()
        _atomic_json(session_path, session)

    return {
        **_public_session(session),
        "access_token": token,
        "session_url": f"/api/video/integration/douyin-auth/session/{session_id}",
        "qr_url": f"/api/video/integration/douyin-auth/qr/{session_id}",
    }


def install_douyin_auth_bridge_v10_40_8_3(app: FastAPI) -> None:
    if getattr(app.state, "douyin_auth_bridge_v10_40_8_3_installed", False):
        return
    app.state.douyin_auth_bridge_v10_40_8_3_installed = True

    @app.get("/api/video/integration/douyin-auth/health")
    def douyin_auth_health():
        return {
            "ok": True,
            "version": VERSION,
            "profiles": ALLOWED_PROFILES,
            "worker_installed": LOGIN_WORKER.exists(),
            "collector_python": str(COLLECTOR_PYTHON),
            "collector_python_exists": COLLECTOR_PYTHON.exists(),
            "auth_root": str(AUTH_ROOT),
        }

    @app.get("/api/video/integration/douyin-auth/status")
    def douyin_auth_status(account_profile: str = Query("company_main")):
        return profile_status(account_profile)

    @app.post("/api/video/integration/douyin-auth/start")
    def douyin_auth_start(payload: dict[str, Any] = Body(default_factory=dict)):
        return _start_login(str(payload.get("account_profile") or "company_main"))

    @app.get("/api/video/integration/douyin-auth/session/{session_id}")
    def douyin_auth_session(session_id: str, token: str = Query("")):
        session = _read_json(_session_path(session_id), {})
        if not isinstance(session, dict) or not session:
            raise HTTPException(404, "登录会话不存在")
        _verify_token(session, token)
        return _public_session(session)

    @app.get("/api/video/integration/douyin-auth/qr/{session_id}")
    def douyin_auth_qr(session_id: str, token: str = Query("")):
        session = _read_json(_session_path(session_id), {})
        if not isinstance(session, dict) or not session:
            raise HTTPException(404, "登录会话不存在")
        _verify_token(session, token)
        path = _qr_path(session_id)
        if not path.exists():
            raise HTTPException(404, "二维码仍在生成，请稍后刷新")
        return FileResponse(
            path,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )

    @app.post("/api/video/integration/douyin-auth/cancel/{session_id}")
    def douyin_auth_cancel(session_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
        session_path = _session_path(session_id)
        session = _read_json(session_path, {})
        if not isinstance(session, dict) or not session:
            raise HTTPException(404, "登录会话不存在")
        _verify_token(session, str(payload.get("token") or ""))
        pid = session.get("pid")
        if _pid_alive(pid):
            try:
                os.killpg(int(pid), signal.SIGTERM)
            except Exception:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except Exception:
                    pass
        session.update(
            {
                "status": "cancelled",
                "message": "登录会话已取消",
                "updated_at": _now(),
            }
        )
        _atomic_json(session_path, session)
        return _public_session(session)
