from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import secrets
import signal
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

VERSION = "10.40.8.6-a1"
AUTH_ROOT = Path(
    os.getenv(
        "AI_VIDEO_DOUYIN_AUTH_ROOT",
        "/opt/ai-video/storage/douyin_auth_v10_40_8_3",
    )
)
SESSION_ROOT = AUTH_ROOT / "sessions"
NOVNC_ROOT = Path(os.getenv("AI_VIDEO_NOVNC_ROOT", "/usr/share/novnc"))
VNC_HOST = os.getenv("AI_VIDEO_DOUYIN_VNC_HOST", "127.0.0.1")
VNC_PORT = int(os.getenv("AI_VIDEO_DOUYIN_VNC_PORT", "5901"))
ACTIVE_STATES = {
    "starting",
    "opening_browser",
    "waiting_scan",
    "verifying",
    "logged_in",
}


def _safe_session_id(value: str) -> str:
    safe = "".join(
        ch for ch in str(value or "") if ch.isalnum() or ch in {"_", "-"}
    )
    if not safe:
        raise HTTPException(400, "无效登录会话 ID")
    return safe


def _session_path(session_id: str) -> Path:
    return SESSION_ROOT / f"{_safe_session_id(session_id)}.json"


def _read_session(session_id: str) -> dict[str, Any]:
    path = _session_path(session_id)
    if not path.exists():
        raise HTTPException(404, "登录会话不存在")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"登录会话文件损坏：{exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(500, "登录会话格式错误")
    return data


def _verify(session: dict[str, Any], token: str) -> None:
    expected = str(session.get("token_hash") or "")
    actual = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
    if not expected or not secrets.compare_digest(expected, actual):
        raise HTTPException(403, "登录会话凭证无效或已过期")
    status = str(session.get("status") or "")
    if status not in ACTIVE_STATES:
        raise HTTPException(409, f"当前登录会话不可操作：{status or 'unknown'}")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _latest_profile_session(account_profile: str) -> tuple[Path, dict[str, Any]] | None:
    latest: tuple[Path, dict[str, Any]] | None = None
    for path in SESSION_ROOT.glob("douyin_login_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("account_profile") or "") != account_profile:
            continue
        if latest is None or float(data.get("updated_at") or 0) > float(
            latest[1].get("updated_at") or 0
        ):
            latest = (path, data)
    return latest


def _stop_session_process(session: dict[str, Any]) -> None:
    try:
        pid = int(session.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass


def _view_html(session_id: str, token: str) -> str:
    sid = html.escape(session_id, quote=True)
    tok = html.escape(token, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1" />
  <title>AI-VIDEO 抖音真机验证</title>
  <style>
    html,body,#screen{{width:100%;height:100%;margin:0;background:#111827;overflow:hidden}}
    #screen{{display:flex;align-items:center;justify-content:center}}
    #bar{{position:fixed;z-index:9;left:12px;right:12px;top:10px;display:flex;gap:8px;align-items:center;
      padding:8px 10px;border-radius:12px;background:rgba(17,24,39,.86);color:white;font:13px system-ui}}
    #bar button{{border:0;border-radius:9px;padding:7px 11px;background:#6d28d9;color:white;cursor:pointer}}
    #status{{margin-left:auto;color:#d1d5db}}
  </style>
</head>
<body>
  <div id="bar">
    <b>抖音真机验证</b>
    <span>在这里直接扫码、拖动验证码或确认登录</span>
    <button id="reconnect">重新连接</button>
    <button id="fullscreen">全屏</button>
    <span id="status">连接中</span>
  </div>
  <div id="screen"></div>
  <script type="module">
    import RFB from "/api/video/integration/douyin-auth/novnc/core/rfb.js";
    const screen = document.getElementById("screen");
    const status = document.getElementById("status");
    const sid = "{sid}";
    const token = "{tok}";
    let rfb = null;
    function connect() {{
      if (rfb) {{
        try {{ rfb.disconnect(); }} catch (_) {{}}
      }}
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const ws = `${{scheme}}://${{location.host}}/api/video/integration/douyin-auth/remote/ws/${{encodeURIComponent(sid)}}?token=${{encodeURIComponent(token)}}`;
      status.textContent = "连接中";
      rfb = new RFB(screen, ws, {{ shared: true }});
      rfb.scaleViewport = true;
      rfb.resizeSession = true;
      rfb.viewOnly = false;
      rfb.addEventListener("connect", () => status.textContent = "已连接，可直接操作");
      rfb.addEventListener("disconnect", (event) => {{
        status.textContent = event.detail.clean ? "已断开" : "连接中断";
      }});
      rfb.addEventListener("securityfailure", () => status.textContent = "安全验证失败");
    }}
    document.getElementById("reconnect").onclick = connect;
    document.getElementById("fullscreen").onclick = () => document.documentElement.requestFullscreen?.();
    connect();
  </script>
</body>
</html>"""


async def _websocket_to_tcp(
    websocket: WebSocket,
    writer: asyncio.StreamWriter,
) -> None:
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            return
        payload = message.get("bytes")
        if payload is None and message.get("text") is not None:
            payload = str(message["text"]).encode("latin-1", errors="ignore")
        if payload:
            writer.write(payload)
            await writer.drain()


async def _tcp_to_websocket(
    reader: asyncio.StreamReader,
    websocket: WebSocket,
) -> None:
    while True:
        payload = await reader.read(65536)
        if not payload:
            return
        await websocket.send_bytes(payload)


def install_douyin_remote_browser_v10_40_8_6(app: FastAPI) -> None:
    if getattr(app.state, "douyin_remote_browser_v10_40_8_6_installed", False):
        return
    app.state.douyin_remote_browser_v10_40_8_6_installed = True

    if NOVNC_ROOT.exists():
        app.mount(
            "/api/video/integration/douyin-auth/novnc",
            StaticFiles(directory=str(NOVNC_ROOT)),
            name="douyin-auth-novnc",
        )

    @app.get("/api/video/integration/douyin-auth/remote/health")
    def remote_health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": VERSION,
            "novnc_root": str(NOVNC_ROOT),
            "novnc_exists": (NOVNC_ROOT / "core/rfb.js").exists(),
            "vnc_host": VNC_HOST,
            "vnc_port": VNC_PORT,
            "display": os.getenv("DISPLAY", ""),
            "security": {
                "vnc_localhost_only": True,
                "session_token_required": True,
                "captcha_automation": False,
                "human_interaction_only": True,
            },
        }

    @app.post(
        "/api/video/integration/douyin-auth/remote/cancel-active"
    )
    def cancel_active(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        account_profile = str(
            payload.get("account_profile") or "company_main"
        ).strip()
        if account_profile not in {
            "company_main",
            "company_backup",
            "personal_test",
        }:
            raise HTTPException(400, "不支持的隔离账号")

        latest = _latest_profile_session(account_profile)
        if latest is None:
            return {
                "ok": True,
                "cancelled": False,
                "message": "当前隔离账号没有旧登录会话",
                "account_profile": account_profile,
            }

        path, session = latest
        _stop_session_process(session)
        session.update(
            {
                "status": "cancelled",
                "message": "旧登录会话已取消，可重新打开真机登录",
                "updated_at": __import__("time").time(),
            }
        )
        _atomic_json(path, session)
        return {
            "ok": True,
            "cancelled": True,
            "message": session["message"],
            "account_profile": account_profile,
            "session_id": session.get("session_id"),
        }

    @app.get(
        "/api/video/integration/douyin-auth/remote/view/{session_id}",
        response_class=HTMLResponse,
    )
    def remote_view(session_id: str, token: str = Query("")) -> HTMLResponse:
        session = _read_session(session_id)
        _verify(session, token)
        if not (NOVNC_ROOT / "core/rfb.js").exists():
            raise HTTPException(503, "noVNC 尚未安装")
        return HTMLResponse(
            _view_html(_safe_session_id(session_id), token),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; "
                    "img-src 'self' data:; frame-ancestors 'self' https:;"
                ),
            },
        )

    @app.websocket("/api/video/integration/douyin-auth/remote/ws/{session_id}")
    async def remote_ws(
        websocket: WebSocket,
        session_id: str,
        token: str = Query(""),
    ) -> None:
        try:
            session = _read_session(session_id)
            _verify(session, token)
        except HTTPException:
            await websocket.close(code=4403)
            return

        requested_protocols = str(
            websocket.headers.get("sec-websocket-protocol") or ""
        )
        selected_protocol = (
            "binary"
            if "binary" in {
                item.strip()
                for item in requested_protocols.split(",")
            }
            else None
        )
        await websocket.accept(subprotocol=selected_protocol)
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.open_connection(VNC_HOST, VNC_PORT)
            tasks = {
                asyncio.create_task(_websocket_to_tcp(websocket, writer)),
                asyncio.create_task(_tcp_to_websocket(reader, websocket)),
            }
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                try:
                    task.result()
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
        except (ConnectionRefusedError, OSError):
            try:
                await websocket.close(code=1013)
            except Exception:
                pass
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
