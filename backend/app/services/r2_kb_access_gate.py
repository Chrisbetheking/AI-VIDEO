from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

VERSION = "1.0.0-reversible-r2-kb-suspension-gate"

DEFAULT_MESSAGE = (
    "R2 knowledge base access is temporarily suspended. "
    "Please check the R2 account balance and billing status, "
    "then contact the administrator."
)

DEFAULT_BLOCKED_PREFIXES = (
    "/api/knowledge",
    "/api/storage/status",
    "/api/assets",
    "/api/video/r2",
    "/api/video/r2-direct-upload",
    "/api/video/asset-zip",
)

STATUS_PATH = "/api/admin/r2-kb-gate/status"
_LOCK = RLock()
_CACHE: dict[str, Any] = {
    "mtime_ns": None,
    "state": None,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
        "suspended",
    }


def _state_path() -> Path:
    configured = os.getenv("R2_KB_GATE_STATE_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    app_data_dir = os.getenv("APP_DATA_DIR", "./data").strip() or "./data"
    return (Path(app_data_dir).expanduser().resolve() / "r2-kb-access-gate.json")


def _normalize_prefixes(values: Iterable[Any]) -> list[str]:
    prefixes: list[str] = []

    for raw in values:
        value = str(raw or "").strip()

        if not value:
            continue

        if not value.startswith("/"):
            value = "/" + value

        value = value.rstrip("/") or "/"

        if value not in prefixes:
            prefixes.append(value)

    return prefixes


def default_state() -> dict[str, Any]:
    env_prefixes = os.getenv("R2_KB_GATE_PREFIXES", "").strip()

    if env_prefixes:
        prefixes = _normalize_prefixes(env_prefixes.split(","))
    else:
        prefixes = list(DEFAULT_BLOCKED_PREFIXES)

    return {
        "suspended": False,
        "message": os.getenv("R2_KB_GATE_MESSAGE", "").strip()
        or DEFAULT_MESSAGE,
        "blocked_prefixes": prefixes,
        "updated_at": _utc_now(),
        "updated_by": "default",
    }


def _safe_state(raw: Any) -> dict[str, Any]:
    base = default_state()

    if not isinstance(raw, dict):
        return base

    base["suspended"] = _as_bool(raw.get("suspended"), False)

    message = str(raw.get("message") or "").strip()
    if message:
        base["message"] = message[:1200]

    prefixes = raw.get("blocked_prefixes")
    if isinstance(prefixes, list):
        normalized = _normalize_prefixes(prefixes)
        if normalized:
            base["blocked_prefixes"] = normalized

    updated_at = str(raw.get("updated_at") or "").strip()
    if updated_at:
        base["updated_at"] = updated_at[:120]

    updated_by = str(raw.get("updated_by") or "").strip()
    if updated_by:
        base["updated_by"] = updated_by[:120]

    return base


def read_state() -> dict[str, Any]:
    path = _state_path()

    try:
        stat_result = path.stat()
        mtime_ns = stat_result.st_mtime_ns
    except FileNotFoundError:
        return default_state()
    except OSError:
        return default_state()

    with _LOCK:
        if (
            _CACHE.get("mtime_ns") == mtime_ns
            and isinstance(_CACHE.get("state"), dict)
        ):
            return dict(_CACHE["state"])

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            state = _safe_state(raw)
        except Exception:
            state = default_state()

        _CACHE["mtime_ns"] = mtime_ns
        _CACHE["state"] = dict(state)
        return state


def write_state(
    *,
    suspended: bool,
    message: str | None = None,
    blocked_prefixes: list[str] | None = None,
    updated_by: str = "ecs-admin",
) -> dict[str, Any]:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    current = read_state()
    state = {
        "suspended": bool(suspended),
        "message": (
            str(message or "").strip()
            or str(current.get("message") or "").strip()
            or DEFAULT_MESSAGE
        )[:1200],
        "blocked_prefixes": _normalize_prefixes(
            blocked_prefixes
            if blocked_prefixes is not None
            else current.get("blocked_prefixes")
            or DEFAULT_BLOCKED_PREFIXES
        ),
        "updated_at": _utc_now(),
        "updated_by": str(updated_by or "ecs-admin")[:120],
    }

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)

    with _LOCK:
        _CACHE["mtime_ns"] = None
        _CACHE["state"] = None

    return state


def _path_matches(path: str, prefixes: list[str]) -> bool:
    normalized = path.rstrip("/") or "/"

    for prefix in prefixes:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True

    return False


class R2KnowledgeBaseAccessGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == STATUS_PATH:
            state = read_state()
            return JSONResponse(
                {
                    "ok": True,
                    "version": VERSION,
                    "suspended": bool(state.get("suspended")),
                    "message": state.get("message"),
                    "blocked_prefixes": state.get("blocked_prefixes"),
                    "updated_at": state.get("updated_at"),
                    "updated_by": state.get("updated_by"),
                    "data_preserved": True,
                    "bucket_deleted": False,
                },
                headers={"Cache-Control": "no-store"},
            )

        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        state = read_state()
        prefixes = _normalize_prefixes(
            state.get("blocked_prefixes") or DEFAULT_BLOCKED_PREFIXES
        )

        if bool(state.get("suspended")) and _path_matches(
            request.url.path,
            prefixes,
        ):
            message = (
                str(state.get("message") or "").strip()
                or DEFAULT_MESSAGE
            )

            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "error": "R2_KNOWLEDGE_BASE_SUSPENDED",
                    "error_code": "R2_KNOWLEDGE_BASE_SUSPENDED",
                    "detail": message,
                    "message": message,
                    "retryable": True,
                    "data_preserved": True,
                    "bucket_deleted": False,
                },
                headers={
                    "Cache-Control": "no-store",
                    "Retry-After": "3600",
                    "X-R2-KB-Gate": "suspended",
                },
            )

        response = await call_next(request)
        response.headers.setdefault("X-R2-KB-Gate", "open")
        return response


def install_r2_kb_access_gate(app: Any) -> None:
    if getattr(app.state, "r2_kb_gate_installed", False):
        return

    app.add_middleware(R2KnowledgeBaseAccessGateMiddleware)
    app.state.r2_kb_gate_installed = True
