from __future__ import annotations

import hmac
import os
import time
from typing import Any


_RATE_STATE: dict[tuple[str, str, int], int] = {}


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def api_token_configured() -> bool:
    return bool(os.getenv("AI_VIDEO_API_TOKEN", "").strip())


def protect_write_endpoints() -> bool:
    return _env_bool("AI_VIDEO_PROTECT_WRITE_ENDPOINTS", "1")


def general_limit_per_minute() -> int:
    return max(1, _env_int("AI_VIDEO_RATE_LIMIT_GENERAL_PER_MIN", 120))


def write_limit_per_minute() -> int:
    return max(1, _env_int("AI_VIDEO_RATE_LIMIT_WRITE_PER_MIN", 12))


def _path_matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(path == p or path.startswith(p) for p in patterns)


PUBLIC_PREFIXES = (
    "/api/video/production/health",
    "/api/video/runtime-safety/health",
    "/api/video/fal/health",
    "/api/video/compose/health",
    "/api/video/subtitle/health",
    "/api/video/subtitle/upload-health",
    "/api/video/full-ai/subtitle-bridge/health",
    "/api/video/real-shot/health",
    "/api/video/hybrid/health",
    "/api/video/jobs/persistence/health",
    "/api/collector/commands/next",
    "/api/video/watermark/health",
    "/api/video/timeline/health",
)

ADMIN_PREFIXES = (
    "/api/video/runtime-safety/cleanup",
    "/api/video/production/security",
    "/api/video/watermark/self-test",
    "/api/video/timeline/self-test",
)

WRITE_PROTECTED_PREFIXES = (
    "/api/video/full-ai/start",
    "/api/video/fal/shot/start",
    "/api/video/fal/storyboard/start",
    "/api/video/compose/urls/start",
    "/api/video/compose/fal-storyboard/start",
    "/api/video/subtitle/burn",
    "/api/video/subtitle/burn-upload",
    "/api/video/full-ai/subtitle-bridge/",
    "/api/video/real-shot/upload",
    "/api/video/real-shot/process",
    "/api/video/hybrid/process",
    "/api/video/watermark/check",
    "/api/video/timeline/build",
)


def client_ip_from_headers(headers: dict[str, str], fallback: str = "") -> str:
    xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or ""
    if xff:
        return xff.split(",")[0].strip() or fallback or "unknown"

    real_ip = headers.get("cf-connecting-ip") or headers.get("CF-Connecting-IP") or ""
    if real_ip:
        return real_ip.strip()

    return fallback or "unknown"


def _extract_token(headers: dict[str, str]) -> str:
    token = headers.get("x-ai-video-token") or headers.get("X-AI-Video-Token") or ""
    if token:
        return token.strip()

    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()

    return ""


def token_ok(headers: dict[str, str]) -> bool:
    expected = os.getenv("AI_VIDEO_API_TOKEN", "").strip()
    if not expected:
        return False

    supplied = _extract_token(headers)
    if not supplied:
        return False

    return hmac.compare_digest(supplied, expected)


def _rate_check(ip: str, path: str, is_write: bool) -> tuple[bool, int, int]:
    now_bucket = int(time.time() // 60)
    group = "write" if is_write else "general"
    limit = write_limit_per_minute() if is_write else general_limit_per_minute()

    key = (ip, group, now_bucket)
    _RATE_STATE[key] = _RATE_STATE.get(key, 0) + 1

    # 清掉旧 bucket，避免内存无限增长
    old_keys = [k for k in _RATE_STATE if k[2] < now_bucket - 3]
    for k in old_keys:
        _RATE_STATE.pop(k, None)

    count = _RATE_STATE[key]
    return count <= limit, count, limit


def check_request(
    method: str,
    path: str,
    headers: dict[str, str],
    client_ip: str = "",
) -> dict[str, Any] | None:
    method = method.upper()
    ip = client_ip_from_headers(headers, client_ip)

    if method == "OPTIONS":
        return None

    if not path.startswith("/api/"):
        return None

    is_public = _path_matches(path, PUBLIC_PREFIXES)
    is_admin = _path_matches(path, ADMIN_PREFIXES)
    is_write = method in {"POST", "PUT", "PATCH", "DELETE"} and _path_matches(path, WRITE_PROTECTED_PREFIXES)

    limited, count, limit = _rate_check(ip, path, is_write=is_write or is_admin)
    if not limited:
        return {
            "status_code": 429,
            "body": {
                "ok": False,
                "status": "rate_limited",
                "message": "请求过于频繁，已被后端限流。",
                "ip": ip,
                "count": count,
                "limit_per_minute": limit,
            },
        }

    if is_public:
        return None

    token_required = False

    if is_admin:
        token_required = True

    if protect_write_endpoints() and is_write:
        token_required = True

    if token_required:
        if not api_token_configured():
            return {
                "status_code": 503,
                "body": {
                    "ok": False,
                    "status": "api_token_not_configured",
                    "message": "后端未配置 AI_VIDEO_API_TOKEN，已拒绝高风险写接口。",
                },
            }

        if not token_ok(headers):
            return {
                "status_code": 401,
                "body": {
                    "ok": False,
                    "status": "api_token_required",
                    "message": "该接口需要 API Token。前端首次操作会提示输入，或通过 X-AI-Video-Token 请求头传入。",
                },
            }

    return None


def security_status() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "api_guard",
        "api_token_configured": api_token_configured(),
        "protect_write_endpoints": protect_write_endpoints(),
        "general_limit_per_minute": general_limit_per_minute(),
        "write_limit_per_minute": write_limit_per_minute(),
        "public_prefixes": list(PUBLIC_PREFIXES),
        "admin_prefixes": list(ADMIN_PREFIXES),
        "write_protected_prefixes": list(WRITE_PROTECTED_PREFIXES),
        "message": "API Guard 已启用：Token 保护 + 全局限流。",
    }
