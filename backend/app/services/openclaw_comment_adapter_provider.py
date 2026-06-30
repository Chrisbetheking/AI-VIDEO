from __future__ import annotations

import csv
import io
import json
import re
import uuid
from typing import Any

from app.services.comment_lead_provider import analyze_comments


TEXT_KEYS = [
    "text", "comment", "content", "body", "message", "comment_text", "commentText",
    "评论", "评论内容", "内容", "文本",
]

AUTHOR_KEYS = [
    "author", "username", "user", "nickname", "name", "display_name", "screen_name",
    "用户", "昵称", "作者",
]

PLATFORM_KEYS = ["platform", "source_platform", "site", "channel", "平台"]
URL_KEYS = ["source_url", "url", "video_url", "post_url", "share_url", "permalink", "link", "链接"]
TITLE_KEYS = ["video_title", "title", "post_title", "caption", "desc", "视频标题", "标题"]
LIKE_KEYS = ["like_count", "likes", "digg_count", "likeCount", "点赞", "点赞数"]
REPLY_KEYS = ["reply_count", "replies", "comment_reply_count", "replyCount", "回复", "回复数"]
CREATED_KEYS = ["created_at", "create_time", "timestamp", "time", "date", "发布时间", "评论时间"]


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _first_value(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in item and item.get(key) not in (None, ""):
            return item.get(key)

    lower_map = {str(k).lower(): k for k in item.keys()}
    for key in keys:
        found = lower_map.get(key.lower())
        if found is not None and item.get(found) not in (None, ""):
            return item.get(found)

    return None


def _author_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ["nickname", "username", "name", "display_name", "unique_id", "id"]:
            if value.get(key):
                return _clean(value.get(key))
        return _clean(json.dumps(value, ensure_ascii=False))
    return _clean(value)


def _to_int(value: Any) -> int:
    if value is None:
        return 0

    if isinstance(value, (int, float)):
        return int(value)

    text = _clean(value).lower().replace(",", "")
    if not text:
        return 0

    multiplier = 1
    if text.endswith("k"):
        multiplier = 1000
        text = text[:-1]
    elif text.endswith("w") or text.endswith("万"):
        multiplier = 10000
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1000000
        text = text[:-1]

    try:
        return int(float(text) * multiplier)
    except Exception:
        return 0


def _extract_items_from_json(obj: Any) -> list[Any]:
    if isinstance(obj, list):
        return obj

    if isinstance(obj, dict):
        for key in [
            "comments", "items", "data", "records", "rows", "results",
            "comment_list", "commentList", "aweme_list",
        ]:
            value = obj.get(key)
            if isinstance(value, list):
                return value

        # 常见嵌套
        for key in ["data", "result", "payload"]:
            value = obj.get(key)
            if isinstance(value, dict):
                nested = _extract_items_from_json(value)
                if nested:
                    return nested

        return [obj]

    return []


def _parse_csv_text(raw_text: str) -> list[dict[str, Any]]:
    text = raw_text.strip()
    if not text:
        return []

    sample = text[:4096]

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except Exception:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = [dict(row) for row in reader if row]

    if rows and any(any(k in row for k in TEXT_KEYS) for row in rows):
        return rows

    return []


def _parse_line_text(raw_text: str) -> list[dict[str, Any]]:
    lines = [_clean(x) for x in raw_text.splitlines()]
    return [{"text": x} for x in lines if x]


def parse_openclaw_export(raw_export: Any) -> list[Any]:
    if raw_export is None:
        return []

    if isinstance(raw_export, list):
        return raw_export

    if isinstance(raw_export, dict):
        return _extract_items_from_json(raw_export)

    raw_text = str(raw_export or "").strip()
    if not raw_text:
        return []

    try:
        obj = json.loads(raw_text)
        items = _extract_items_from_json(obj)
        if items:
            return items
    except Exception:
        pass

    csv_items = _parse_csv_text(raw_text)
    if csv_items:
        return csv_items

    return _parse_line_text(raw_text)


def normalize_comment(item: Any, default_platform: str = "", campaign_context: dict[str, Any] | None = None) -> dict[str, Any]:
    campaign_context = campaign_context or {}

    if isinstance(item, str):
        return {
            "platform": default_platform or campaign_context.get("platform") or "",
            "text": _clean(item),
        }

    if not isinstance(item, dict):
        return {
            "platform": default_platform or campaign_context.get("platform") or "",
            "text": _clean(item),
        }

    text = _first_value(item, TEXT_KEYS)
    author = _first_value(item, AUTHOR_KEYS)
    platform = _first_value(item, PLATFORM_KEYS)
    source_url = _first_value(item, URL_KEYS)
    video_title = _first_value(item, TITLE_KEYS)
    like_count = _first_value(item, LIKE_KEYS)
    reply_count = _first_value(item, REPLY_KEYS)
    created_at = _first_value(item, CREATED_KEYS)

    # 兼容一些常见嵌套字段
    if not text and isinstance(item.get("comment"), dict):
        text = _first_value(item["comment"], TEXT_KEYS)

    if not author and isinstance(item.get("user"), dict):
        author = item.get("user")

    if not author and isinstance(item.get("author"), dict):
        author = item.get("author")

    return {
        "platform": _clean(platform) or default_platform or campaign_context.get("platform") or "",
        "source_url": _clean(source_url) or campaign_context.get("source_url") or "",
        "video_title": _clean(video_title) or campaign_context.get("video_title") or "",
        "author": _author_value(author),
        "text": _clean(text),
        "like_count": _to_int(like_count),
        "reply_count": _to_int(reply_count),
        "created_at": _clean(created_at),
        "raw_openclaw": item,
    }


def normalize_comments(
    raw_export: Any = None,
    comments: list[Any] | None = None,
    default_platform: str = "",
    campaign_context: dict[str, Any] | None = None,
    max_items: int = 500,
) -> list[dict[str, Any]]:
    campaign_context = campaign_context or {}
    items = comments if comments else parse_openclaw_export(raw_export)

    normalized: list[dict[str, Any]] = []
    for item in items[: max(1, min(int(max_items or 500), 2000))]:
        c = normalize_comment(item, default_platform=default_platform, campaign_context=campaign_context)
        if c.get("text"):
            normalized.append(c)

    return normalized


def analyze_openclaw_comments(
    raw_export: Any = None,
    comments: list[Any] | None = None,
    campaign_context: dict[str, Any] | None = None,
    default_platform: str = "",
    save: bool = True,
    max_items: int = 500,
) -> dict[str, Any]:
    campaign_context = campaign_context or {}
    normalized = normalize_comments(
        raw_export=raw_export,
        comments=comments,
        default_platform=default_platform,
        campaign_context=campaign_context,
        max_items=max_items,
    )

    if not normalized:
        raise ValueError("没有解析到有效评论。请传 raw_export 字符串、JSON、CSV，或 comments 列表。")

    analysis = analyze_comments(
        comments=normalized,
        campaign_context=campaign_context,
        save=save,
        max_items=max_items,
    )

    return {
        "ok": True,
        "provider": "openclaw_comment_adapter_v1",
        "status": "done",
        "import_id": f"openclaw_import_{uuid.uuid4().hex[:18]}",
        "normalized_count": len(normalized),
        "comments_preview": normalized[:10],
        "analysis": analysis,
        "message": "OpenClaw 评论导入适配完成：只解析导出的评论数据并送入线索引擎，不自动抓取平台、不自动评论、不自动私信。",
    }


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "openclaw_comment_adapter_v1",
        "message": "OpenClaw 评论适配器可用：支持 JSON / CSV / 文本评论导入，统一转成评论区线索引擎格式。",
        "features": [
            "json_export_parse",
            "csv_export_parse",
            "plain_text_comments_parse",
            "field_normalization",
            "comment_lead_engine_bridge",
            "no_auto_scrape_no_auto_dm_no_auto_comment",
        ],
    }


def self_test() -> dict[str, Any]:
    csv_text = """author,text,like_count,reply_count,platform,source_url
lead_a,马来西亚买房首付多少？哪个区适合投资出租？,18,3,tiktok,https://example.com/video/1
lead_b,海外房产怕踩坑，有没有核验清单？,9,1,tiktok,https://example.com/video/1
lead_c,可以私信我吗，想了解预算和贷款,5,2,tiktok,https://example.com/video/1
"""
    return analyze_openclaw_comments(
        raw_export=csv_text,
        campaign_context={
            "market": "马来西亚",
            "platform": "tiktok",
            "video_title": "马来西亚买房避坑",
        },
        save=False,
        max_items=50,
    )
