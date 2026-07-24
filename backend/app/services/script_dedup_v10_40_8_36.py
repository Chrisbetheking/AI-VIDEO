from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, Field

VERSION = "10.40.8.36-script-memory-dedup-rotation"

# Decision thresholds are intentionally conservative: the system rewrites before a
# script becomes an obvious paraphrase, while still allowing the same business topic
# to be explained from a genuinely different angle.
WARN_THRESHOLD = 0.52
REWRITE_THRESHOLD = 0.62
BLOCK_THRESHOLD = 0.82

ANGLE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("价格预算", ("价格", "预算", "总价", "首付", "贷款", "现金")),
    ("自住投资", ("自住", "投资", "第二居所", "用途")),
    ("出租租客", ("出租", "租客", "租金", "空置", "租赁")),
    ("区域通勤", ("区域", "通勤", "交通", "地铁", "轻轨", "办公")),
    ("生活配套", ("生活半径", "商场", "学校", "医院", "配套", "社区")),
    ("交付规划", ("交付", "规划", "施工", "兑现", "烂尾", "进度")),
    ("持有成本", ("持有成本", "物业费", "税费", "维修", "管理费", "保险")),
    ("合同付款", ("合同", "付款", "定金", "律师", "条款", "节点")),
    ("户型实用", ("户型", "采光", "动线", "面积", "朝向", "收纳")),
    ("转售流动性", ("转手", "二手", "流动性", "退出", "转售")),
    ("客户案例", ("客户", "案例", "看房", "现场", "真实经历", "上周")),
    ("流程手续", ("流程", "手续", "签约", "身份", "外国人", "申请")),
    ("家庭需求", ("家庭", "孩子", "父母", "养老", "成员", "居住需求")),
    ("物业管理", ("物业", "管理", "维护", "入住率", "公共区域")),
    ("数据核验", ("核验", "数据", "官方资料", "实地", "证据", "清单")),
]

ANGLE_POOL = [name for name, _ in ANGLE_RULES]
STRUCTURE_POOL = [
    "客户案例",
    "现场实测",
    "成本账单",
    "决策树",
    "红旗清单",
    "问答拆解",
    "前后对比",
    "误区纠正",
    "一分钟审计",
    "单一观点论证",
]

COMMON_FILLERS = {
    "很多人", "其实", "真的", "就是", "然后", "还有", "首先", "其次", "最后",
    "一上来", "第一眼", "说白了", "简单来说", "你要知道", "别只看", "先别急",
}

CONCEPT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("价格", ("价格", "总价", "房价", "价钱", "预算")),
    ("自住", ("自住", "自己住", "买来住", "居住")),
    ("投资", ("投资", "资产配置", "增值")),
    ("租客", ("租客", "租户", "出租", "租赁", "承租")),
    ("通勤", ("通勤", "上班", "出勤", "交通时间")),
    ("配套", ("生活半径", "配套", "商场", "医院", "生活设施")),
    ("办公", ("办公", "办公区", "写字楼", "商务区")),
    ("学校", ("学校", "大学", "教育资源", "国际学校")),
    ("规划", ("未来规划", "规划", "兑现", "建设计划")),
    ("核验", ("核验", "核实", "确认", "正式资料", "官方资料", "实地")),
    ("风险", ("风险", "买错", "选错", "踩坑", "后悔", "不兑现")),
    ("区域", ("区域", "板块", "地段", "周边", "附近")),
    ("交付", ("交付", "施工", "竣工", "收房")),
    ("成本", ("持有成本", "物业费", "税费", "维修", "费用")),
    ("合同", ("合同", "条款", "付款节点", "定金", "律师")),
    ("户型", ("户型", "采光", "动线", "收纳", "朝向")),
    ("转售", ("转售", "转手", "二手", "流动性", "退出")),
    ("家庭", ("家庭", "孩子", "父母", "养老", "一家人")),
]

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize(value: Any) -> str:
    text = _clean_text(value).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    for filler in COMMON_FILLERS:
        text = text.replace(filler, "")
    return text


def extract_concepts(value: Any) -> list[str]:
    text = _clean_text(value).lower()
    found: list[str] = []
    for label, words in CONCEPT_RULES:
        if any(word in text for word in words):
            found.append(label)
    return found


def _semantic_normalize(value: Any) -> str:
    text = _normalize(value)
    raw = _clean_text(value).lower()
    for label, words in CONCEPT_RULES:
        if any(word in raw for word in words):
            # Append canonical labels rather than destructively replacing text. This
            # preserves wording similarity while making paraphrased concepts visible.
            text += label
    return text


def _sentences(value: Any) -> list[str]:
    return [
        _normalize(item)
        for item in re.split(r"[。！？!?；;\n]+", str(value or ""))
        if _normalize(item)
    ]


def _ngrams(text: str, n: int = 3) -> set[str]:
    if not text:
        return set()
    if len(text) <= n:
        return {text}
    return {text[index:index + n] for index in range(len(text) - n + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _sequence(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _sentence_similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    # Average each new sentence's best historical counterpart. This catches
    # paragraph reshuffling and synonym-heavy rewrites better than whole-text only.
    best = [max(_sequence(sentence, candidate) for candidate in right) for sentence in left]
    best.sort(reverse=True)
    keep = best[: max(1, math.ceil(len(best) * 0.75))]
    return sum(keep) / len(keep)


def classify_angles(*values: Any) -> list[str]:
    text = " ".join(_clean_text(value) for value in values)
    scored: list[tuple[int, str]] = []
    for name, words in ANGLE_RULES:
        score = sum(text.count(word) for word in words)
        if score:
            scored.append((score, name))
    scored.sort(key=lambda item: (-item[0], ANGLE_POOL.index(item[1])))
    return [name for _, name in scored[:8]] or ["综合判断"]


def classify_structure(script: Any) -> str:
    text = _clean_text(script)
    if re.search(r"上周|昨天|之前有位|有个客户|有位客户|真实经历|我带.*看", text):
        return "客户案例"
    if re.search(r"实测|现场|走一遍|亲自|镜头里", text):
        return "现场实测"
    if re.search(r"成本|账单|物业费|税费|一共|每年要花", text):
        return "成本账单"
    if re.search(r"如果.+就|如果.+那么|满足.+选|否则", text):
        return "决策树"
    if re.search(r"红旗|警惕|风险信号|看到.+就", text):
        return "红旗清单"
    if text.count("？") + text.count("?") >= 2 or re.search(r"有人问|常见问题|问得最多", text):
        return "问答拆解"
    if re.search(r"vs|对比|自住.+投资|以前.+现在|一边.+另一边", text, flags=re.I):
        return "前后对比"
    if re.search(r"误区|别以为|真相|并不是|不是.+而是", text):
        return "误区纠正"
    if re.search(r"核验|审计|检查清单|逐项|五分钟看", text):
        return "一分钟审计"
    if re.search(r"第一|第二|第三|三个|四个|\d+[、.]", text):
        return "列表拆解"
    return "单一观点论证"


def classify_hook(hook: Any, script: Any = "") -> str:
    text = _clean_text(hook) or (_clean_text(script)[:80])
    if re.search(r"上周|昨天|有个客户|我遇到", text):
        return "故事开场"
    if re.search(r"\d|三种|三个|一条", text):
        return "数字清单"
    if "？" in text or "?" in text or re.search(r"为什么|怎么|到底|你会", text):
        return "问题开场"
    if re.search(r"别|不要|风险|买错|选错|踩坑|警惕", text):
        return "风险警告"
    if re.search(r"不是.+而是|恰恰|反而|真相", text):
        return "反常识"
    return "观点直给"


def classify_cta(cta: Any, script: Any = "") -> str:
    text = _clean_text(cta) or (_clean_text(script)[-100:])
    if re.search(r"评论|留言|打在评论区", text):
        return "评论承接"
    if re.search(r"私信|联系|咨询|发给你", text):
        return "私信承接"
    if re.search(r"你是|你会选|更适合|选哪|偏向|更偏|还是", text):
        return "选择提问"
    if re.search(r"收藏|转发|关注", text):
        return "收藏关注"
    return "弱CTA"


def _fingerprint(script: Any) -> str:
    return hashlib.sha256(_normalize(script).encode("utf-8")).hexdigest()


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"


def _parse_json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(str(value or ""))
        return parsed
    except Exception:
        return default


def _data_dir(settings: Any) -> Path:
    raw = getattr(settings, "data_dir", None) or "/opt/ai-video/backend/data"
    return Path(raw)


def _workspace(settings: Any) -> str:
    return str(getattr(settings, "workspace_id", None) or "default")


@dataclass
class ScriptRecord:
    id: str
    workspace_id: str
    source: str
    topic: str
    title: str
    hook: str
    script: str
    cta: str
    angle: str
    structure: str
    hook_type: str
    cta_type: str
    status: str
    task_id: str
    fingerprint: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class ScriptDedupEngine:
    def __init__(self, settings: Any):
        self.settings = settings
        self.workspace_id = _workspace(settings)
        self.db_path = _data_dir(settings) / "script-dedup" / "script_dedup.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _init_db(self) -> None:
        with _LOCK, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS script_history (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    hook TEXT NOT NULL DEFAULT '',
                    script TEXT NOT NULL DEFAULT '',
                    cta TEXT NOT NULL DEFAULT '',
                    angle TEXT NOT NULL DEFAULT '',
                    structure TEXT NOT NULL DEFAULT '',
                    hook_type TEXT NOT NULL DEFAULT '',
                    cta_type TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'generated',
                    task_id TEXT NOT NULL DEFAULT '',
                    fingerprint TEXT NOT NULL DEFAULT '',
                    normalized_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS script_history_workspace_created_idx
                    ON script_history(workspace_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS script_history_workspace_fingerprint_idx
                    ON script_history(workspace_id, fingerprint);
                CREATE INDEX IF NOT EXISTS script_history_status_idx
                    ON script_history(status);
                CREATE TABLE IF NOT EXISTS script_dedup_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _meta_get(self, key: str) -> str:
        with _LOCK, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM script_dedup_meta WHERE key=?",
                (key,),
            ).fetchone()
        return str(row["value"] or "") if row else ""

    def _meta_set(self, key: str, value: str) -> None:
        with _LOCK, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO script_dedup_meta(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key, value, _now()),
            )

    def backfill_from_memory(self, memory: Any, *, limit: int = 500, force: bool = False) -> dict[str, Any]:
        """Import pre-V36 script_versions once so the first new script is checked
        against historical production copy, not only content generated after deploy.
        New writes are mirrored live by MemoryStore.save_script_version.
        """
        marker = "script_versions_backfill_v36"
        previous = self._meta_get(marker)
        if previous and not force:
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_backfilled",
                "marker": _parse_json(previous, {}),
            }
        try:
            rows = memory.list("script_versions", limit=max(1, min(int(limit), 2000)))
        except Exception as exc:
            return {
                "ok": False,
                "skipped": False,
                "imported": 0,
                "warning": f"history_backfill_failed: {type(exc).__name__}: {exc}",
            }
        imported = 0
        ignored = 0
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                ignored += 1
                continue
            script = _clean_text(row.get("script") or row.get("copy") or row.get("text"))
            if len(_normalize(script)) < 12:
                ignored += 1
                continue
            result = self.save({
                "source": "script_versions_backfill",
                "topic": row.get("topic") or "",
                "title": row.get("title") or "",
                "hook": row.get("hook") or "",
                "script": script,
                "cta": row.get("cta") or "",
                "angle": row.get("angle") or "",
                "structure": row.get("structure") or "",
                "hook_type": row.get("hook_type") or "",
                "cta_type": row.get("cta_type") or "",
                "status": row.get("status") or "historical_backfill",
                "task_id": row.get("task_id") or row.get("job_id") or "",
                "created_at": row.get("created_at") or _now(),
                "metadata": {
                    "backfilled_from_script_versions": True,
                    "legacy_id": row.get("id"),
                    "legacy_source": row.get("source"),
                },
            })
            if result.get("saved"):
                imported += 1
            else:
                ignored += 1
        summary = {
            "completed_at": _now(),
            "imported": imported,
            "ignored": ignored,
            "source_rows": len(rows) if isinstance(rows, list) else 0,
        }
        self._meta_set(marker, _safe_json(summary))
        return {"ok": True, "skipped": False, **summary}

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        script = _clean_text(payload.get("script") or payload.get("copy") or payload.get("text"))
        if len(_normalize(script)) < 12:
            return {"ok": False, "saved": False, "reason": "script_too_short"}
        topic = _clean_text(payload.get("topic"))
        title = _clean_text(payload.get("title"))
        hook = _clean_text(payload.get("hook")) or (_sentences(script)[0] if _sentences(script) else "")
        cta = _clean_text(payload.get("cta"))
        angles = payload.get("angles") if isinstance(payload.get("angles"), list) else classify_angles(topic, title, script)
        angle = _clean_text(payload.get("angle")) or "、".join(angles[:8])
        structure = _clean_text(payload.get("structure")) or classify_structure(script)
        hook_type = _clean_text(payload.get("hook_type")) or classify_hook(hook, script)
        cta_type = _clean_text(payload.get("cta_type")) or classify_cta(cta, script)
        created_at = _clean_text(payload.get("created_at")) or _now()
        updated_at = _now()
        record_id = _clean_text(payload.get("id")) or str(uuid.uuid4())
        fingerprint = _fingerprint(script)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata = dict(metadata)
        if isinstance(payload.get("raw"), dict):
            raw_text = _safe_json(payload.get("raw"))
            if len(raw_text) <= 16000:
                metadata["raw"] = payload.get("raw")
            else:
                metadata["raw_preview"] = raw_text[:16000]
                metadata["raw_truncated"] = True
        metadata_text = _safe_json(metadata)
        if len(metadata_text) > 30000:
            metadata = {
                "metadata_preview": metadata_text[:30000],
                "metadata_truncated": True,
            }
        values = (
            record_id,
            self.workspace_id,
            _clean_text(payload.get("source")) or "unknown",
            topic,
            title,
            hook,
            script,
            cta,
            angle,
            structure,
            hook_type,
            cta_type,
            _clean_text(payload.get("status")) or "generated",
            _clean_text(payload.get("task_id") or payload.get("job_id")),
            fingerprint,
            _normalize(script),
            _safe_json(metadata),
            created_at,
            updated_at,
        )
        with _LOCK, self._connect() as connection:
            # Exact same script from the same source within the workflow is updated,
            # rather than endlessly duplicating rows on blur/retry.
            existing = connection.execute(
                """
                SELECT id FROM script_history
                WHERE workspace_id=? AND fingerprint=? AND source=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (self.workspace_id, fingerprint, values[2]),
            ).fetchone()
            if existing and not payload.get("force_new_record"):
                record_id = str(existing["id"])
                connection.execute(
                    """
                    UPDATE script_history SET
                        topic=?, title=?, hook=?, script=?, cta=?, angle=?, structure=?,
                        hook_type=?, cta_type=?, status=?, task_id=?, normalized_text=?,
                        metadata_json=?, updated_at=?
                    WHERE id=? AND workspace_id=?
                    """,
                    (
                        topic, title, hook, script, cta, angle, structure,
                        hook_type, cta_type, values[12], values[13], values[15],
                        values[16], updated_at, record_id, self.workspace_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO script_history (
                        id, workspace_id, source, topic, title, hook, script, cta,
                        angle, structure, hook_type, cta_type, status, task_id,
                        fingerprint, normalized_text, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
        return {
            "ok": True,
            "saved": True,
            "id": record_id,
            "fingerprint": fingerprint,
            "angle": angle,
            "structure": structure,
            "hook_type": hook_type,
            "cta_type": cta_type,
            "storage": "sqlite+supabase_mirror",
        }

    def list(self, limit: int = 80, *, compare_only: bool = False) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 80), 1000))
        where = "workspace_id=?"
        params: list[Any] = [self.workspace_id]
        if compare_only:
            where += " AND status NOT IN ('rejected_similarity','draft_attempt','deleted')"
        with _LOCK, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM script_history WHERE {where} ORDER BY created_at DESC LIMIT ?",
                (*params, safe_limit),
            ).fetchall()
        return [self._row(row) for row in rows]

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = _parse_json(item.pop("metadata_json", "{}"), {})
        item.pop("normalized_text", None)
        return item

    def recent_usage(self, limit: int = 12) -> dict[str, Any]:
        rows = self.list(limit=limit, compare_only=True)
        angles: list[str] = []
        structures: list[str] = []
        hooks: list[str] = []
        ctas: list[str] = []
        for row in rows:
            for angle in re.split(r"[、,/|]+", str(row.get("angle") or "")):
                angle = angle.strip()
                if angle and angle not in angles:
                    angles.append(angle)
            for key, target in (("structure", structures), ("hook_type", hooks), ("cta_type", ctas)):
                value = _clean_text(row.get(key))
                if value and value not in target:
                    target.append(value)
        return {
            "recent_angles": angles[:10],
            "recent_structures": structures[:8],
            "recent_hook_types": hooks[:8],
            "recent_cta_types": ctas[:8],
            "history_count": len(rows),
        }

    def generation_brief(
        self,
        *,
        topic: str = "",
        requested_angle: str = "",
        requested_structure: str = "",
        force_new_angle: bool = False,
    ) -> dict[str, Any]:
        recent = self.recent_usage(16)
        topic_angles = classify_angles(topic)
        angle_candidates = [name for name in ANGLE_POOL if name not in recent["recent_angles"]]
        if requested_angle:
            angle = requested_angle
        elif force_new_angle and angle_candidates:
            angle = angle_candidates[0]
        else:
            angle = next((name for name in topic_angles if name not in recent["recent_angles"]), "")
            angle = angle or (angle_candidates[0] if angle_candidates else topic_angles[0])
        structure_candidates = [name for name in STRUCTURE_POOL if name not in recent["recent_structures"]]
        structure = requested_structure or (structure_candidates[0] if structure_candidates else STRUCTURE_POOL[0])
        history = self.list(limit=8, compare_only=True)
        avoid_phrases: list[str] = []
        for row in history:
            for sentence in _sentences(row.get("script"))[:2]:
                if 5 <= len(sentence) <= 28 and sentence not in avoid_phrases:
                    avoid_phrases.append(sentence)
        return {
            **recent,
            "recommended_angle": angle,
            "recommended_structure": structure,
            "avoid_phrases": avoid_phrases[:12],
            "requirements": [
                "不得只做同义词替换；核心论证路径必须变化",
                "开头钩子、主体结构和结尾 CTA 至少更换两项",
                "最近使用过的角度进入冷却，不作为本次主角度",
                "事实不足时明确使用判断方法，不编造项目、价格、收益和学校",
            ],
        }

    def analyze(
        self,
        *,
        script: str,
        topic: str = "",
        title: str = "",
        hook: str = "",
        cta: str = "",
        limit: int = 120,
        exclude_ids: Optional[Iterable[str]] = None,
    ) -> dict[str, Any]:
        normalized = _semantic_normalize(script)
        sentences = [_semantic_normalize(item) for item in re.split(r"[。！？!?；;\n]+", str(script or "")) if _semantic_normalize(item)]
        hook_normalized = _normalize(hook or (sentences[0] if sentences else ""))
        cta_normalized = _normalize(cta or (sentences[-1] if sentences else ""))
        angles = classify_angles(topic, title, script)
        structure = classify_structure(script)
        hook_type = classify_hook(hook, script)
        cta_type = classify_cta(cta, script)
        excluded = {str(item) for item in (exclude_ids or [])}
        matches: list[dict[str, Any]] = []

        for row in self.list(limit=limit, compare_only=True):
            if str(row.get("id")) in excluded:
                continue
            historical = _semantic_normalize(row.get("script"))
            if not historical:
                continue
            whole_sequence = _sequence(normalized, historical)
            gram_score = _jaccard(_ngrams(normalized), _ngrams(historical))
            sentence_score = _sentence_similarity(sentences, [_semantic_normalize(item) for item in re.split(r"[。！？!?；;\n]+", str(row.get("script") or "")) if _semantic_normalize(item)])
            current_concepts = set(extract_concepts(script))
            historical_concepts = set(extract_concepts(row.get("script")))
            shared_concepts = current_concepts & historical_concepts
            concept_score = len(shared_concepts) / max(1, len(current_concepts | historical_concepts))
            # Jaccard alone underrates synonym-heavy rewrites when one version adds a
            # few extra concepts. Containment measures whether the smaller content
            # skeleton is substantially reused by the larger one.
            concept_containment = len(shared_concepts) / max(
                1,
                min(len(current_concepts), len(historical_concepts)),
            )
            historical_angles = {
                item.strip()
                for item in re.split(r"[、,/|]+", str(row.get("angle") or ""))
                if item.strip()
            }
            angle_score = len(set(angles) & historical_angles) / max(1, len(set(angles) | historical_angles))
            structure_score = 1.0 if structure == row.get("structure") else 0.0
            hook_score = _sequence(hook_normalized, _normalize(row.get("hook")))
            cta_score = _sequence(cta_normalized, _normalize(row.get("cta")))
            score = (
                whole_sequence * 0.20
                + gram_score * 0.08
                + sentence_score * 0.16
                + concept_score * 0.20
                + concept_containment * 0.20
                + angle_score * 0.10
                + structure_score * 0.03
                + hook_score * 0.02
                + cta_score * 0.01
            )
            # Reusing most of the same semantic concepts and angles is the exact
            # failure mode the user reported: the wording changes, but the content
            # remains "price -> self-use/investment -> renter -> amenities". Force
            # those mother-topic paraphrases into the rewrite lane even when lexical
            # similarity is low.
            semantic_skeleton_score = (
                concept_containment * 0.72
                + angle_score * 0.28
            )
            semantic_skeleton_repeated = bool(
                len(shared_concepts) >= 5
                and concept_containment >= 0.72
                and angle_score >= 0.45
            )
            if semantic_skeleton_repeated:
                score = max(
                    score,
                    REWRITE_THRESHOLD + min(0.12, max(0.0, semantic_skeleton_score - 0.72) * 0.5),
                )
            matches.append({
                "id": row.get("id"),
                "title": row.get("title") or row.get("topic") or "历史文案",
                "source": row.get("source"),
                "created_at": row.get("created_at"),
                "similarity": round(score * 100, 1),
                "whole_text_similarity": round(whole_sequence * 100, 1),
                "sentence_similarity": round(sentence_score * 100, 1),
                "concept_similarity": round(concept_score * 100, 1),
                "concept_containment": round(concept_containment * 100, 1),
                "semantic_skeleton_similarity": round(semantic_skeleton_score * 100, 1),
                "semantic_skeleton_repeated": semantic_skeleton_repeated,
                "shared_concepts": sorted(shared_concepts),
                "hook_similarity": round(hook_score * 100, 1),
                "cta_similarity": round(cta_score * 100, 1),
                "angle": row.get("angle"),
                "structure": row.get("structure"),
                "script_preview": _clean_text(row.get("script"))[:180],
            })

        matches.sort(key=lambda item: (-float(item["similarity"]), str(item.get("created_at") or "")), reverse=False)
        top = matches[:5]
        highest = float(top[0]["similarity"]) / 100 if top else 0.0
        if highest >= BLOCK_THRESHOLD:
            decision = "block"
        elif highest >= REWRITE_THRESHOLD:
            decision = "rewrite"
        elif highest >= WARN_THRESHOLD:
            decision = "warn"
        else:
            decision = "pass"
        recent = self.recent_usage(12)
        return {
            "ok": True,
            "version": VERSION,
            "decision": decision,
            "rewrite_required": decision in {"block", "rewrite"},
            "blocked": decision == "block",
            "similarity_score": round(highest * 100, 1),
            "originality_score": round((1 - highest) * 100, 1),
            "thresholds": {
                "warn": int(WARN_THRESHOLD * 100),
                "rewrite": int(REWRITE_THRESHOLD * 100),
                "block": int(BLOCK_THRESHOLD * 100),
            },
            "angle": "、".join(angles[:3]),
            "angles": angles,
            "structure": structure,
            "hook_type": hook_type,
            "cta_type": cta_type,
            "cooldown": {
                **recent,
                "angle_repeated": any(item in recent["recent_angles"] for item in angles),
                "structure_repeated": structure in recent["recent_structures"],
                "hook_repeated": hook_type in recent["recent_hook_types"],
                "cta_repeated": cta_type in recent["recent_cta_types"],
            },
            "top_matches": top,
            "history_count": len(matches),
        }


def build_rewrite_feedback(report: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    matches = report.get("top_matches") or []
    return {
        "reason": "文案与历史内容过于相似，禁止同义词改写后直接通过。",
        "highest_similarity": report.get("similarity_score"),
        "matched_history": [
            {
                "title": item.get("title"),
                "similarity": item.get("similarity"),
                "preview": item.get("script_preview"),
            }
            for item in matches[:3]
        ],
        "must_use_angle": brief.get("recommended_angle"),
        "must_use_structure": brief.get("recommended_structure"),
        "must_change": ["前三秒钩子", "主体论证路径", "结尾CTA"],
        "forbidden_phrases": brief.get("avoid_phrases") or [],
    }


def persist_script_record(
    settings: Any,
    memory: Any,
    payload: dict[str, Any],
    *,
    report: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    engine = ScriptDedupEngine(settings)
    merged = dict(payload)
    if report:
        merged.setdefault("angle", report.get("angle"))
        merged.setdefault("structure", report.get("structure"))
        merged.setdefault("hook_type", report.get("hook_type"))
        merged.setdefault("cta_type", report.get("cta_type"))
        metadata = dict(merged.get("metadata") or {})
        metadata["dedup_report"] = report
        merged["metadata"] = metadata
    saved = engine.save(merged)
    try:
        raw = dict(merged.get("raw") or {})
        raw["script_dedup"] = {
            "record": saved,
            "report": report or {},
            "metadata": merged.get("metadata") or {},
        }
        memory.save_script_version({
            "title": merged.get("title") or merged.get("topic") or "",
            "hook": merged.get("hook") or "",
            "script": merged.get("script") or "",
            "description": merged.get("description") or "",
            "tags": merged.get("tags") or [],
            "source": merged.get("source") or "script_dedup",
            "topic": merged.get("topic") or "",
            "cta": merged.get("cta") or "",
            "angle": merged.get("angle") or (report or {}).get("angle") or "",
            "structure": merged.get("structure") or (report or {}).get("structure") or "",
            "status": merged.get("status") or "generated",
            "task_id": merged.get("task_id") or "",
            "dedup_report": report or {},
            "raw": raw,
            "_skip_dedup_mirror": True,
        })
    except Exception as exc:
        saved["memory_warning"] = f"Supabase mirror failed: {type(exc).__name__}: {exc}"
    return saved


class ScriptDedupPayload(BaseModel):
    title: str = ""
    topic: str = ""
    hook: str = ""
    script: str = Field(min_length=1, max_length=30000)
    cta: str = ""
    source: str = "manual"
    status: str = "manual_saved"
    task_id: str = ""
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScriptDedupBriefPayload(BaseModel):
    topic: str = ""
    requested_angle: str = ""
    requested_structure: str = ""
    force_new_angle: bool = False


def install_script_dedup(
    app: FastAPI,
    get_settings_dependency: Callable[..., Any],
    get_memory_dependency: Callable[..., Any],
) -> None:
    @app.get("/api/video/script-dedup/health")
    def api_script_dedup_health(
        settings: Any = Depends(get_settings_dependency),
        memory: Any = Depends(get_memory_dependency),
    ) -> dict[str, Any]:
        engine = ScriptDedupEngine(settings)
        backfill = engine.backfill_from_memory(memory)
        history = engine.list(limit=1)
        return {
            "ok": True,
            "version": VERSION,
            "database": str(engine.db_path),
            "history_available": bool(history),
            "history_backfill": backfill,
            "features": {
                "pre_v36_history_backfill": True,
                "persistent_sqlite_history": True,
                "supabase_script_versions_mirror": True,
                "whole_text_similarity": True,
                "sentence_similarity": True,
                "hook_cta_similarity": True,
                "angle_structure_cooldown": True,
                "automatic_rewrite_gate": True,
                "manual_final_script_save": True,
            },
        }

    @app.post("/api/video/script-dedup/check")
    def api_script_dedup_check(
        req: ScriptDedupPayload,
        settings: Any = Depends(get_settings_dependency),
        memory: Any = Depends(get_memory_dependency),
    ) -> dict[str, Any]:
        engine = ScriptDedupEngine(settings)
        engine.backfill_from_memory(memory)
        return engine.analyze(
            script=req.script,
            topic=req.topic,
            title=req.title,
            hook=req.hook,
            cta=req.cta,
        )

    @app.post("/api/video/script-dedup/save")
    def api_script_dedup_save(
        req: ScriptDedupPayload,
        settings: Any = Depends(get_settings_dependency),
        memory: Any = Depends(get_memory_dependency),
    ) -> dict[str, Any]:
        engine = ScriptDedupEngine(settings)
        report = engine.analyze(
            script=req.script,
            topic=req.topic,
            title=req.title,
            hook=req.hook,
            cta=req.cta,
        )
        saved = persist_script_record(settings, memory, req.model_dump(), report=report)
        return {"ok": True, "saved": saved, "dedup_report": report}

    @app.post("/api/video/script-dedup/brief")
    def api_script_dedup_brief(
        req: ScriptDedupBriefPayload,
        settings: Any = Depends(get_settings_dependency),
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "version": VERSION,
            "brief": ScriptDedupEngine(settings).generation_brief(
                topic=req.topic,
                requested_angle=req.requested_angle,
                requested_structure=req.requested_structure,
                force_new_angle=req.force_new_angle,
            ),
        }

    @app.get("/api/video/script-dedup/history")
    def api_script_dedup_history(
        limit: int = Query(default=30, ge=1, le=300),
        settings: Any = Depends(get_settings_dependency),
        memory: Any = Depends(get_memory_dependency),
    ) -> dict[str, Any]:
        engine = ScriptDedupEngine(settings)
        engine.backfill_from_memory(memory)
        return {"ok": True, "version": VERSION, "items": engine.list(limit=limit)}
