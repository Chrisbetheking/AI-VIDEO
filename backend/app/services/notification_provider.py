from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
import uuid
from typing import Any


PROVIDER = "notification_center_v1"


def _clean(text: Any) -> str:
    return " ".join(str(text or "").strip().split())


def _json_post(url: str, payload: dict[str, Any], timeout: float = 20) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        status = resp.status

    try:
        body = json.loads(raw)
    except Exception:
        body = {"raw": raw}

    return {
        "http_status": status,
        "response": body,
    }


def _feishu_sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def _send_feishu_text(text: str, dry_run: bool = False) -> dict[str, Any]:
    webhook = os.getenv("FEISHU_WEBHOOK_URL") or os.getenv("AI_VIDEO_FEISHU_WEBHOOK_URL") or ""
    secret = os.getenv("FEISHU_WEBHOOK_SECRET") or os.getenv("AI_VIDEO_FEISHU_WEBHOOK_SECRET") or ""

    if not webhook:
        return {
            "channel": "feishu",
            "ok": False,
            "configured": False,
            "message": "FEISHU_WEBHOOK_URL 未配置。",
        }

    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {
            "text": text,
        },
    }

    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = _feishu_sign(secret, timestamp)

    if dry_run:
        return {
            "channel": "feishu",
            "ok": True,
            "configured": True,
            "dry_run": True,
            "payload_preview": payload,
        }

    try:
        result = _json_post(webhook, payload)
        return {
            "channel": "feishu",
            "ok": True,
            "configured": True,
            "dry_run": False,
            "result": result,
        }
    except Exception as exc:
        return {
            "channel": "feishu",
            "ok": False,
            "configured": True,
            "dry_run": False,
            "error": str(exc),
        }


def _send_wecom_markdown(text: str, dry_run: bool = False) -> dict[str, Any]:
    webhook = os.getenv("WECOM_WEBHOOK_URL") or os.getenv("WECHAT_WORK_WEBHOOK_URL") or os.getenv("AI_VIDEO_WECOM_WEBHOOK_URL") or ""

    if not webhook:
        return {
            "channel": "wecom",
            "ok": False,
            "configured": False,
            "message": "WECOM_WEBHOOK_URL 未配置。",
        }

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": text,
        },
    }

    if dry_run:
        return {
            "channel": "wecom",
            "ok": True,
            "configured": True,
            "dry_run": True,
            "payload_preview": payload,
        }

    try:
        result = _json_post(webhook, payload)
        body = result.get("response") or {}
        ok = bool(body.get("errcode") in (0, None))
        return {
            "channel": "wecom",
            "ok": ok,
            "configured": True,
            "dry_run": False,
            "result": result,
        }
    except Exception as exc:
        return {
            "channel": "wecom",
            "ok": False,
            "configured": True,
            "dry_run": False,
            "error": str(exc),
        }


def _default_channels() -> list[str]:
    raw = os.getenv("AI_VIDEO_NOTIFY_CHANNELS") or "feishu,wecom"
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def send_message(
    title: str,
    message: str,
    level: str = "info",
    channels: list[str] | None = None,
    dry_run: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    channels = channels or _default_channels()
    metadata = metadata or {}

    title = _clean(title) or "AI-VIDEO 通知"
    level = _clean(level) or "info"
    message = str(message or "").strip()

    notify_id = f"notify_{uuid.uuid4().hex[:18]}"

    text = format_message(
        title=title,
        message=message,
        level=level,
        metadata=metadata,
        notify_id=notify_id,
    )

    results = []
    for ch in channels:
        if ch in ("feishu", "lark"):
            results.append(_send_feishu_text(text, dry_run=dry_run))
        elif ch in ("wecom", "wechat_work", "work_wechat", "qywx", "qiyeweixin"):
            results.append(_send_wecom_markdown(text, dry_run=dry_run))
        else:
            results.append(
                {
                    "channel": ch,
                    "ok": False,
                    "configured": False,
                    "message": f"未知通知通道：{ch}",
                }
            )

    return {
        "ok": any(x.get("ok") for x in results),
        "provider": PROVIDER,
        "notify_id": notify_id,
        "dry_run": dry_run,
        "level": level,
        "channels": channels,
        "results": results,
        "message": "通知发送流程完成。",
    }


def format_message(title: str, message: str, level: str, metadata: dict[str, Any], notify_id: str) -> str:
    icon = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
        "lead": "🔥",
        "video": "🎬",
    }.get(level, "ℹ️")

    lines = [
        f"{icon} {title}",
        "",
        message,
    ]

    if metadata:
        lines.append("")
        lines.append("——")
        for k, v in metadata.items():
            if v is None or v == "":
                continue
            lines.append(f"{k}: {v}")

    lines.append("")
    lines.append(f"notify_id: {notify_id}")
    return "\n".join(lines)


def send_openclaw_lead(
    lead: dict[str, Any],
    channels: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    score = lead.get("lead_score") or lead.get("score") or ""
    priority = lead.get("priority") or ""
    text = lead.get("original_text") or lead.get("text") or ""
    public_reply = lead.get("public_reply") or lead.get("reply_draft") or ""
    hook = lead.get("script_hook") or ""
    stage = lead.get("buyer_stage") or lead.get("capture_angle") or ""

    msg = "\n".join(
        [
            f"发现高分评论线索：{priority} / {score}",
            f"评论：{text}",
            "",
            f"阶段/意图：{stage}",
            f"建议回复：{public_reply}",
            "",
            f"可转选题 Hook：{hook}",
        ]
    )

    return send_message(
        title="AI-VIDEO 新线索提醒",
        message=msg,
        level="lead",
        channels=channels,
        dry_run=dry_run,
        metadata={
            "priority": priority,
            "score": score,
            "source": lead.get("platform") or "",
        },
    )


def send_video_job(
    job: dict[str, Any],
    channels: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    status = job.get("status") or ""
    job_id = job.get("job_id") or job.get("id") or ""
    video_url = job.get("video_url") or job.get("output_url") or ""
    error = job.get("error") or ""

    level = "success" if status in ("done", "success", "completed") else "error" if status in ("failed", "error") else "video"

    msg_lines = [
        f"任务状态：{status}",
        f"任务 ID：{job_id}",
    ]

    if video_url:
        msg_lines.append(f"视频链接：{video_url}")

    if error:
        msg_lines.append(f"错误：{error}")

    return send_message(
        title="AI-VIDEO 视频任务通知",
        message="\n".join(msg_lines),
        level=level,
        channels=channels,
        dry_run=dry_run,
        metadata={
            "job_id": job_id,
            "status": status,
        },
    )


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": PROVIDER,
        "configured": {
            "feishu": bool(os.getenv("FEISHU_WEBHOOK_URL") or os.getenv("AI_VIDEO_FEISHU_WEBHOOK_URL")),
            "feishu_sign": bool(os.getenv("FEISHU_WEBHOOK_SECRET") or os.getenv("AI_VIDEO_FEISHU_WEBHOOK_SECRET")),
            "wecom": bool(os.getenv("WECOM_WEBHOOK_URL") or os.getenv("WECHAT_WORK_WEBHOOK_URL") or os.getenv("AI_VIDEO_WECOM_WEBHOOK_URL")),
        },
        "default_channels": _default_channels(),
        "features": [
            "feishu_webhook",
            "wecom_group_robot_webhook",
            "generic_notification",
            "openclaw_lead_notification",
            "video_job_notification",
        ],
        "message": "Notification Center v1 可用：用于把视频任务、OpenClaw 线索、系统告警推送到飞书/企业微信群。",
    }


def self_test(dry_run: bool = True) -> dict[str, Any]:
    lead_result = send_openclaw_lead(
        {
            "priority": "A",
            "lead_score": 96,
            "platform": "tiktok",
            "original_text": "马来西亚买房首付多少？哪个区域适合投资出租？",
            "buyer_stage": "investment_research",
            "public_reply": "这个要看预算、用途和区域。你更关注稳定出租还是未来转手？",
            "script_hook": "海外房产投资别只看租金回报，真正影响转手的是这三个因素。",
        },
        dry_run=dry_run,
    )

    job_result = send_video_job(
        {
            "job_id": "demo_job_001",
            "status": "done",
            "video_url": "https://example.com/demo.mp4",
        },
        dry_run=dry_run,
    )

    return {
        "ok": True,
        "provider": PROVIDER,
        "dry_run": dry_run,
        "lead_result": lead_result,
        "job_result": job_result,
    }
