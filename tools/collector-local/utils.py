from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse


def parse_metric(value: object) -> int | None:
    """Parse Chinese short metrics: 999, 1.2万, 3万+, 10w."""
    if value is None:
        return None
    text = str(value).strip().lower().replace(",", "")
    if not text or text in {"-", "--"}:
        return None
    text = text.replace("+", "").replace("次", "").replace("播放", "")
    multiplier = 1
    if "万" in text or "w" in text:
        multiplier = 10000
        text = text.replace("万", "").replace("w", "")
    elif "千" in text or "k" in text:
        multiplier = 1000
        text = text.replace("千", "").replace("k", "")
    elif "亿" in text:
        multiplier = 100000000
        text = text.replace("亿", "")
    m = re.search(r"\d+(?:\.\d+)?", text)
    if not m:
        return None
    return int(float(m.group(0)) * multiplier)


def normalize_video_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://www.douyin.com" + (url if url.startswith("/") else f"/{url}")
    return url.split("?")[0].split("#")[0]


def split_tags(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in re.split(r"[,，;；\s]+", str(value or "")) if x.strip()]


def within_recent_days(iso_or_text: str | None, days: int) -> bool:
    if not iso_or_text:
        return False
    text = str(iso_or_text)
    now = datetime.now(timezone.utc)
    if "今天" in text or "刚刚" in text or "小时前" in text or "分钟前" in text:
        return True
    if "昨天" in text:
        return days >= 1
    m = re.search(r"(\d+)天前", text)
    if m:
        return int(m.group(1)) <= days
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m-%d", "%m/%d"):
        try:
            if fmt.startswith("%m"):
                dt = datetime.strptime(text[:5], fmt).replace(year=now.year, tzinfo=timezone.utc)
            else:
                dt = datetime.strptime(text[:10], fmt).replace(tzinfo=timezone.utc)
            return dt >= now - timedelta(days=days)
        except Exception:
            continue
    return False
