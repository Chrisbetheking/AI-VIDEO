from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


PROVIDER = "douyin_account_library_v1"

BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
DB_PATH = Path(os.getenv("AI_VIDEO_DOUYIN_ACCOUNT_DB_PATH", str(BASE_DIR / "data" / "douyin-accounts" / "douyin_accounts.sqlite3")))

VALID_CATEGORIES = {"competitor", "traffic_teaching"}


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _json_loads(value: Any, default: Any):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def init_db():
    conn = _conn()
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS douyin_accounts (
            id TEXT PRIMARY KEY,
            created_at INTEGER,
            updated_at INTEGER,
            category TEXT,
            account_name TEXT,
            douyin_id TEXT,
            profile_url TEXT,
            niche TEXT,
            region TEXT,
            keywords_json TEXT,
            notes TEXT,
            source TEXT,
            status TEXT,
            metrics_json TEXT,
            score INTEGER,
            score_breakdown_json TEXT,
            tags_json TEXT,
            raw_json TEXT
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS douyin_account_learnings (
            id TEXT PRIMARY KEY,
            created_at INTEGER,
            category TEXT,
            title TEXT,
            summary TEXT,
            hook_patterns_json TEXT,
            title_patterns_json TEXT,
            content_formats_json TEXT,
            action_items_json TEXT,
            source_account_ids_json TEXT,
            raw_json TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def normalize_category(value: str | None) -> str:
    value = _clean(value or "competitor").lower()
    alias = {
        "同行": "competitor",
        "竞品": "competitor",
        "competitors": "competitor",
        "traffic": "traffic_teaching",
        "traffic_teacher": "traffic_teaching",
        "流量": "traffic_teaching",
        "流量教学": "traffic_teaching",
        "短视频教学": "traffic_teaching",
    }
    value = alias.get(value, value)
    if value not in VALID_CATEGORIES:
        raise ValueError("category 只能是 competitor 或 traffic_teaching。")
    return value


def score_account(account: dict[str, Any]) -> dict[str, Any]:
    category = normalize_category(account.get("category"))
    metrics = account.get("metrics") or {}

    score = 20
    breakdown: dict[str, int] = {}

    def add(name: str, points: int):
        nonlocal score
        points = int(points)
        score += points
        breakdown[name] = breakdown.get(name, 0) + points

    text_blob = " ".join(
        [
            _clean(account.get("account_name")),
            _clean(account.get("niche")),
            _clean(account.get("notes")),
            " ".join(map(str, account.get("keywords") or [])),
        ]
    ).lower()

    try:
        follower_count = int(metrics.get("follower_count") or metrics.get("followers") or 0)
        avg_likes = int(metrics.get("avg_likes") or metrics.get("like_count") or 0)
        avg_comments = int(metrics.get("avg_comments") or metrics.get("comment_count") or 0)
        avg_collects = int(metrics.get("avg_collects") or metrics.get("collect_count") or 0)
    except Exception:
        follower_count = avg_likes = avg_comments = avg_collects = 0

    if follower_count >= 100000:
        add("followers_100k_plus", 18)
    elif follower_count >= 30000:
        add("followers_30k_plus", 12)
    elif follower_count >= 5000:
        add("followers_5k_plus", 6)

    if avg_likes >= 5000:
        add("avg_likes_high", 18)
    elif avg_likes >= 1000:
        add("avg_likes_mid", 12)
    elif avg_likes >= 200:
        add("avg_likes_seed", 6)

    if avg_comments >= 200:
        add("comment_discussion_high", 14)
    elif avg_comments >= 50:
        add("comment_discussion_mid", 8)

    if avg_collects >= 500:
        add("collect_value_high", 10)
    elif avg_collects >= 100:
        add("collect_value_mid", 6)

    real_estate_words = ["房产", "买房", "楼盘", "海外房产", "马来西亚", "吉隆坡", "投资", "租金", "置业"]
    traffic_words = ["流量", "短视频", "起号", "爆款", "投放", "剪辑", "直播", "涨粉", "运营", "转化"]

    if any(w in text_blob for w in real_estate_words):
        add("real_estate_relevance", 18)

    if any(w in text_blob for w in traffic_words):
        add("traffic_method_relevance", 18 if category == "traffic_teaching" else 6)

    if category == "competitor":
        add("competitor_category", 8)
    else:
        add("traffic_teaching_category", 8)

    score = max(0, min(100, score))

    if score >= 80:
        level = "A"
    elif score >= 60:
        level = "B"
    elif score >= 40:
        level = "C"
    else:
        level = "D"

    tags = []
    if category == "competitor":
        tags.append("同行账号")
        if score >= 70:
            tags.append("可作为对标基础")
    else:
        tags.append("流量教学账号")
        if score >= 70:
            tags.append("优先学习方法论")

    if any(w in text_blob for w in real_estate_words):
        tags.append("房产相关")
    if any(w in text_blob for w in traffic_words):
        tags.append("流量方法")

    return {
        "score": score,
        "level": level,
        "score_breakdown": breakdown,
        "tags": tags,
    }


def upsert_account(account: dict[str, Any]) -> dict[str, Any]:
    init_db()

    if not isinstance(account, dict):
        raise ValueError("account 必须是对象。")

    category = normalize_category(account.get("category"))
    now = int(time.time())

    account_id = _clean(account.get("id"))
    if not account_id:
        stable_key = _clean(account.get("douyin_id")) or _clean(account.get("profile_url")) or _clean(account.get("account_name"))
        account_id = f"douyin_account_{uuid.uuid5(uuid.NAMESPACE_URL, stable_key or uuid.uuid4().hex).hex[:18]}"

    scoring = score_account({**account, "category": category})
    raw = {**account, "category": category, "score_result": scoring}

    conn = _conn()
    c = conn.cursor()

    c.execute("SELECT created_at FROM douyin_accounts WHERE id=?", (account_id,))
    row = c.fetchone()
    created_at = int(row[0]) if row else now

    c.execute(
        """
        INSERT OR REPLACE INTO douyin_accounts (
            id, created_at, updated_at, category, account_name, douyin_id,
            profile_url, niche, region, keywords_json, notes, source, status,
            metrics_json, score, score_breakdown_json, tags_json, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            created_at,
            now,
            category,
            _clean(account.get("account_name") or account.get("name")),
            _clean(account.get("douyin_id")),
            _clean(account.get("profile_url") or account.get("url")),
            _clean(account.get("niche")),
            _clean(account.get("region") or "中国"),
            _json_dumps(account.get("keywords") or []),
            _clean(account.get("notes")),
            _clean(account.get("source") or "manual"),
            _clean(account.get("status") or "active"),
            _json_dumps(account.get("metrics") or {}),
            scoring["score"],
            _json_dumps(scoring["score_breakdown"]),
            _json_dumps(scoring["tags"]),
            _json_dumps(raw),
        ),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "provider": PROVIDER,
        "account": {
            "id": account_id,
            "category": category,
            "account_name": _clean(account.get("account_name") or account.get("name")),
            "douyin_id": _clean(account.get("douyin_id")),
            "profile_url": _clean(account.get("profile_url") or account.get("url")),
            "niche": _clean(account.get("niche")),
            "score": scoring["score"],
            "level": scoring["level"],
            "tags": scoring["tags"],
            "score_breakdown": scoring["score_breakdown"],
        },
    }


def bulk_upsert_accounts(accounts: list[Any]) -> dict[str, Any]:
    if not accounts:
        raise ValueError("accounts 不能为空。")

    saved = []
    errors = []

    for index, item in enumerate(accounts[:500]):
        try:
            if isinstance(item, str):
                parts = [x.strip() for x in item.split(",")]
                item = {
                    "account_name": parts[0] if len(parts) > 0 else item,
                    "douyin_id": parts[1] if len(parts) > 1 else "",
                    "category": parts[2] if len(parts) > 2 else "competitor",
                    "niche": parts[3] if len(parts) > 3 else "",
                    "source": "bulk_text",
                }
            saved.append(upsert_account(item)["account"])
        except Exception as exc:
            errors.append({"index": index, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "provider": PROVIDER,
        "saved_count": len(saved),
        "error_count": len(errors),
        "accounts": saved,
        "errors": errors,
    }


def list_accounts(category: str | None = None, min_score: int = 0, limit: int = 100) -> dict[str, Any]:
    init_db()
    limit = max(1, min(int(limit or 100), 500))
    min_score = max(0, min(int(min_score or 0), 100))

    where = ["score >= ?"]
    args: list[Any] = [min_score]

    if category:
        where.append("category = ?")
        args.append(normalize_category(category))

    sql = f"""
        SELECT id, created_at, updated_at, category, account_name, douyin_id,
               profile_url, niche, region, keywords_json, notes, source, status,
               metrics_json, score, score_breakdown_json, tags_json, raw_json
        FROM douyin_accounts
        WHERE {' AND '.join(where)}
        ORDER BY score DESC, updated_at DESC
        LIMIT ?
    """
    args.append(limit)

    conn = _conn()
    c = conn.cursor()
    c.execute(sql, args)
    rows = c.fetchall()
    conn.close()

    items = []
    for row in rows:
        items.append(
            {
                "id": row[0],
                "created_at": row[1],
                "updated_at": row[2],
                "category": row[3],
                "account_name": row[4],
                "douyin_id": row[5],
                "profile_url": row[6],
                "niche": row[7],
                "region": row[8],
                "keywords": _json_loads(row[9], []),
                "notes": row[10],
                "source": row[11],
                "status": row[12],
                "metrics": _json_loads(row[13], {}),
                "score": row[14],
                "score_breakdown": _json_loads(row[15], {}),
                "tags": _json_loads(row[16], []),
                "raw": _json_loads(row[17], {}),
            }
        )

    return {
        "ok": True,
        "provider": PROVIDER,
        "count": len(items),
        "category": category or "all",
        "min_score": min_score,
        "accounts": items,
    }


def traffic_learning(dry_run: bool = True, min_score: int = 50, limit: int = 30) -> dict[str, Any]:
    accounts = list_accounts(category="traffic_teaching", min_score=min_score, limit=limit)["accounts"]

    hook_patterns = [
        "反常识开头：不要一上来问价格，先看风险点。",
        "问题开头：为什么同样预算，有人买对区域，有人踩坑？",
        "清单结构：3 个判断标准 / 5 个避坑动作 / 4 个核验步骤。",
        "评论区驱动：把高频问题改成下一条视频开头。",
    ]

    title_patterns = [
        "千万别只看 X，真正关键的是 Y",
        "第一次做 X，先看这 3 件事",
        "很多人以为 X，其实真正影响结果的是 Y",
        "评论区问爆的问题，我一次讲清楚",
    ]

    content_formats = [
        "痛点问题 → 误区 → 3 点拆解 → 评论区追问",
        "同行爆款标题 → 换角度原创 → 房产真实资料约束 → Timeline",
        "评论高频问题 → 线索判断 → 回复话术 → 下一条视频选题",
    ]

    action_items = [
        "每天从流量教学账号提炼 5 个标题结构，不照搬文字，只拿结构。",
        "把同行高分视频拆成 hook、转折、证据、评论引导四段。",
        "每条视频结尾必须留一个筛选问题：预算、区域、自住/投资、时间。",
        "高意向评论优先做下一条视频，不直接硬广。",
    ]

    result = {
        "ok": True,
        "provider": PROVIDER,
        "dry_run": dry_run,
        "source_account_count": len(accounts),
        "title": "抖音流量教学账号学习结果",
        "summary": "根据流量教学账号库沉淀短视频方法论：重点学习标题结构、开头钩子、评论区转化方式和内容复盘框架，不复制原文。",
        "hook_patterns": hook_patterns,
        "title_patterns": title_patterns,
        "content_formats": content_formats,
        "action_items": action_items,
        "source_accounts": accounts,
    }

    _save_learning(
        category="traffic_teaching",
        title=result["title"],
        summary=result["summary"],
        hook_patterns=hook_patterns,
        title_patterns=title_patterns,
        content_formats=content_formats,
        action_items=action_items,
        source_account_ids=[x["id"] for x in accounts],
        raw=result,
    )

    return result


def competitor_benchmarks(min_score: int = 60, limit: int = 30) -> dict[str, Any]:
    accounts = list_accounts(category="competitor", min_score=min_score, limit=limit)["accounts"]

    benchmarks = []
    for acc in accounts:
        benchmarks.append(
            {
                "account_id": acc["id"],
                "account_name": acc["account_name"],
                "score": acc["score"],
                "level": "A" if acc["score"] >= 80 else "B" if acc["score"] >= 60 else "C",
                "use_as_basis": acc["score"] >= 60,
                "what_to_learn": [
                    "选题角度",
                    "评论区问题",
                    "开头 hook 结构",
                    "视频结尾转化问题",
                ],
                "do_not_copy": [
                    "不要照搬文案",
                    "不要盗用素材",
                    "不要编造项目、价格、户型、周边",
                ],
                "our_action": "作为对标基础：拆结构、换原创角度、结合真实项目资料生成我们自己的脚本和 Timeline。",
            }
        )

    return {
        "ok": True,
        "provider": PROVIDER,
        "min_score": min_score,
        "benchmark_count": len(benchmarks),
        "benchmarks": benchmarks,
        "message": "同行高分账号已筛出：只学习结构和选题，不复制内容，不盗素材。",
    }


def _save_learning(
    category: str,
    title: str,
    summary: str,
    hook_patterns: list[str],
    title_patterns: list[str],
    content_formats: list[str],
    action_items: list[str],
    source_account_ids: list[str],
    raw: dict[str, Any],
):
    init_db()
    conn = _conn()
    c = conn.cursor()
    learn_id = f"douyin_learning_{uuid.uuid4().hex[:18]}"
    now = int(time.time())

    c.execute(
        """
        INSERT INTO douyin_account_learnings (
            id, created_at, category, title, summary,
            hook_patterns_json, title_patterns_json, content_formats_json,
            action_items_json, source_account_ids_json, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            learn_id,
            now,
            category,
            title,
            summary,
            _json_dumps(hook_patterns),
            _json_dumps(title_patterns),
            _json_dumps(content_formats),
            _json_dumps(action_items),
            _json_dumps(source_account_ids),
            _json_dumps(raw),
        ),
    )
    conn.commit()
    conn.close()


def seed_mission_targets(market: str = "马来西亚") -> dict[str, Any]:
    keywords = [
        f"{market}买房",
        f"{market}房产",
        f"{market}置业",
        "吉隆坡公寓",
        "海外房产投资",
        "海外买房避坑",
        "抖音房产获客",
        "短视频起号",
        "短视频流量",
        "评论区转化",
    ]

    return {
        "ok": True,
        "provider": PROVIDER,
        "platform": "douyin",
        "market": market,
        "targets": {
            "competitor_keywords": keywords[:6],
            "traffic_teaching_keywords": keywords[6:],
            "recommended_collection": {
                "competitor_accounts": 50,
                "traffic_teaching_accounts": 30,
                "videos_per_account": 20,
                "comments_per_video": 50,
            },
        },
        "collector_instruction": "采集器按关键词扩展抖音账号库：同行账号进 competitor，流量教学账号进 traffic_teaching；回传后系统评分和学习。",
    }


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": PROVIDER,
        "platform": "douyin",
        "categories": ["competitor", "traffic_teaching"],
        "features": [
            "douyin_account_library",
            "competitor_account_scoring",
            "traffic_teaching_learning",
            "benchmark_selection",
            "collector_target_generation",
            "no_auto_dm_no_auto_comment",
        ],
        "message": "抖音账号库可用：同行账号和流量教学账号分开管理，同行高分做对标基础，流量教学账号沉淀方法论。",
    }


def self_test() -> dict[str, Any]:
    sample = bulk_upsert_accounts(
        [
            {
                "category": "competitor",
                "account_name": "示例马来西亚房产同行",
                "douyin_id": "demo_competitor",
                "niche": "马来西亚房产 买房 投资 吉隆坡",
                "keywords": ["马来西亚买房", "海外房产投资"],
                "metrics": {"followers": 30000, "avg_likes": 1200, "avg_comments": 80, "avg_collects": 150},
                "notes": "用于自测，不代表真实账号。",
                "source": "self_test",
            },
            {
                "category": "traffic_teaching",
                "account_name": "示例短视频流量教学",
                "douyin_id": "demo_traffic_teacher",
                "niche": "短视频流量 起号 爆款 评论区转化",
                "keywords": ["短视频起号", "爆款标题", "评论区转化"],
                "metrics": {"followers": 100000, "avg_likes": 5000, "avg_comments": 300, "avg_collects": 800},
                "notes": "用于自测，不代表真实账号。",
                "source": "self_test",
            },
        ]
    )

    return {
        "ok": True,
        "provider": PROVIDER,
        "seed": sample,
        "competitor_benchmarks": competitor_benchmarks(min_score=40, limit=10),
        "traffic_learning": traffic_learning(dry_run=True, min_score=40, limit=10),
        "seed_targets": seed_mission_targets(),
    }
