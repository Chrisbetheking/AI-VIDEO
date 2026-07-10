from __future__ import annotations

import hashlib
import json
import os
import re
import time
import random
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

from PIL import Image, ImageDraw

from app.services import xhs_visual_story_v10_37 as v37


VERSION = "10.38"
STYLE = "v5_xhs_fact_checked_visual_story"
JOB_ROOT = Path(
    os.getenv(
        "AI_VIDEO_JOB_ROOT",
        "/opt/ai-video/storage/v10_34/final_jobs",
    )
)

SCRIPT_KEYS = {
    "script",
    "script_text",
    "original_script",
    "tts_script",
    "voiceover",
    "voiceover_text",
    "narration",
    "narration_text",
    "copywriting",
    "transcript",
    "subtitle_text",
    "spoken_text",
    "content_text",
    "segments",
    "script_segments",
    "tts_segments",
    "sentences",
    "paragraphs",
}

REGION_ALIASES: List[Tuple[str, List[str]]] = [
    ("KLCC", ["KLCC", "双子塔"]),
    ("满家乐", ["满家乐", "Mont Kiara", "MontKiara"]),
    ("武吉免登", ["武吉免登", "Bukit Bintang"]),
    ("孟沙", ["孟沙", "Bangsar"]),
    ("TRX", ["TRX", "敦拉萨国际贸易中心"]),
    ("蕉赖", ["蕉赖", "Cheras"]),
    ("旧巴生路", ["旧巴生路", "Old Klang Road"]),
    ("白沙罗", ["白沙罗", "Damansara"]),
    ("安邦", ["安邦", "Ampang"]),
    ("甲洞", ["甲洞", "Kepong"]),
    ("梳邦再也", ["梳邦再也", "Subang Jaya"]),
    ("八打灵再也", ["八打灵再也", "Petaling Jaya"]),
    ("赛城", ["赛城", "Cyberjaya"]),
    ("布城", ["布城", "Putrajaya"]),
]

BUDGET_PATTERNS = [
    r"(?<!\d)(\d{1,4}(?:\.\d+)?\s*万元?)(?!\d)",
    r"(?<!\d)(RM\s*\d[\d,]*(?:\.\d+)?)",
    r"(?<!\d)(MYR\s*\d[\d,]*(?:\.\d+)?)",
    r"(?<!\d)(\d[\d,]*(?:\.\d+)?\s*马币)",
    r"(低预算|中预算|高预算|预算有限|预算充足|预算不高|预算较高)",
]

RELATION_WORDS = [
    "适合",
    "对应",
    "可以看",
    "可看",
    "优先看",
    "建议看",
    "选择",
    "考虑",
    "买在",
    "买",
]

PURPOSE_WORDS = {
    "investment": ["投资", "升值", "回报", "租金", "出租", "租客"],
    "self_use": ["自住", "通勤", "生活配套", "学校", "家庭", "居住"],
    "rental": ["出租", "租客", "租金", "空置率"],
}


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\u3000", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _dedupe(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for raw in values:
        value = _clean_text(raw)
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _collect_script_values(
    value: Any,
    key_hint: str = "",
    depth: int = 0,
) -> List[str]:
    if depth > 8:
        return []

    result: List[str] = []
    hint = key_hint.lower()
    in_script = any(token in hint for token in SCRIPT_KEYS)

    if isinstance(value, str):
        text = _clean_text(value)
        if in_script and len(text) >= 4:
            result.append(text)
        return result

    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and in_script:
                text = _clean_text(item)
                if len(text) >= 2:
                    result.append(text)
            elif isinstance(item, (dict, list)):
                result.extend(
                    _collect_script_values(
                        item,
                        key_hint=key_hint,
                        depth=depth + 1,
                    )
                )
        return result

    if not isinstance(value, dict):
        return result

    for key, item in value.items():
        key_lower = str(key).lower()
        is_script_key = (
            key_lower in SCRIPT_KEYS
            or any(token in key_lower for token in SCRIPT_KEYS)
        )

        if is_script_key:
            result.extend(
                _collect_script_values(
                    item,
                    key_hint=key_lower,
                    depth=depth + 1,
                )
            )
        elif key_lower in {
            "result",
            "data",
            "payload",
            "job",
            "output",
            "metadata",
            "content",
        }:
            result.extend(
                _collect_script_values(
                    item,
                    key_hint=key_lower,
                    depth=depth + 1,
                )
            )

    return result


def _strip_subtitle(text: str) -> str:
    lines: List[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if "-->" in line:
            continue
        if re.match(r"^\d{1,2}:\d{2}:\d{2}", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def _read_sidecars(job_id: str) -> Tuple[List[str], List[str]]:
    values: List[str] = []
    origins: List[str] = []
    candidates: List[Path] = []

    job_dir = JOB_ROOT / job_id
    job_json = JOB_ROOT / f"{job_id}.json"

    if job_json.exists():
        candidates.append(job_json)

    if job_dir.exists():
        for pattern in [
            "*script*.json",
            "*script*.txt",
            "*tts*.json",
            "*narration*.txt",
            "*transcript*.txt",
            "*subtitle*.srt",
            "*.srt",
            "*.vtt",
        ]:
            candidates.extend(job_dir.rglob(pattern))

    unique: List[Path] = []
    seen = set()

    for path in candidates:
        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)

        if key in seen:
            continue
        seen.add(key)
        unique.append(path)

    for path in unique[:80]:
        try:
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue

            raw = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
            suffix = path.suffix.lower()

            if suffix == ".json":
                extracted = _collect_script_values(json.loads(raw))
            elif suffix in {".srt", ".vtt"}:
                extracted = [_strip_subtitle(raw)]
            else:
                extracted = [raw]

            cleaned = [
                _clean_text(item)
                for item in extracted
                if len(_clean_text(item)) >= 4
            ]

            if cleaned:
                values.extend(cleaned)
                origins.append(str(path))
        except Exception:
            continue

    return values, origins


def _source_bundle(
    payload: Dict[str, Any],
    job: Dict[str, Any],
) -> Dict[str, Any]:
    job_id = str(payload.get("job_id") or "").strip()
    values: List[str] = []
    origins: List[str] = []

    payload_script = _clean_text(payload.get("script_text") or "")
    if payload_script:
        values.append(payload_script)
        origins.append("payload.script_text")

    job_values = _collect_script_values(job)
    if job_values:
        values.extend(job_values)
        origins.append("job.json")

    sidecar_values, sidecar_origins = _read_sidecars(job_id)
    values.extend(sidecar_values)
    origins.extend(sidecar_origins)

    values = _dedupe(values)
    full_text = _clean_text("\n".join(values))

    return {
        "text": full_text,
        "origins": _dedupe(origins),
        "char_count": len(full_text),
        "sha256": (
            hashlib.sha256(
                full_text.encode("utf-8")
            ).hexdigest()
            if full_text
            else ""
        ),
    }


def _sentences(text: str) -> List[str]:
    chunks = re.split(
        r"(?<=[。！？!?；;])|\n+",
        _clean_text(text),
    )

    return _dedupe(
        chunk.strip(" \t\r\n-—")
        for chunk in chunks
        if 4 <= len(chunk.strip()) <= 180
    )


def _budget_tokens(sentence: str) -> List[str]:
    result: List[str] = []

    for pattern in BUDGET_PATTERNS:
        for match in re.findall(
            pattern,
            sentence,
            flags=re.IGNORECASE,
        ):
            if isinstance(match, tuple):
                match = next(
                    (part for part in match if part),
                    "",
                )

            value = re.sub(r"\s+", "", str(match))
            if value and value not in result:
                result.append(value)

    return result


def _region_tokens(sentence: str) -> List[str]:
    low = sentence.lower()
    return [
        canonical
        for canonical, aliases in REGION_ALIASES
        if any(alias.lower() in low for alias in aliases)
    ]


def _purpose_flags(text: str) -> Dict[str, bool]:
    return {
        key: any(word in text for word in words)
        for key, words in PURPOSE_WORDS.items()
    }


def _quote_score(sentence: str) -> int:
    score = 0
    if _budget_tokens(sentence):
        score += 5
    if _region_tokens(sentence):
        score += 5
    if any(word in sentence for word in ["投资", "自住", "出租", "预算"]):
        score += 3
    if any(word in sentence for word in ["不要", "别", "先", "更适合", "区别"]):
        score += 2
    if 12 <= len(sentence) <= 70:
        score += 2
    return score


def _analyse(source: Dict[str, Any]) -> Dict[str, Any]:
    sentences = _sentences(source["text"])

    budget_evidence: List[Dict[str, Any]] = []
    region_evidence: List[Dict[str, Any]] = []
    pairs: List[Dict[str, Any]] = []
    blocked: List[str] = []

    for index, sentence in enumerate(sentences):
        budgets = _budget_tokens(sentence)
        regions = _region_tokens(sentence)

        for budget in budgets:
            budget_evidence.append(
                {
                    "value": budget,
                    "quote": sentence,
                    "sentence_index": index,
                }
            )

        for region in regions:
            region_evidence.append(
                {
                    "value": region,
                    "quote": sentence,
                    "sentence_index": index,
                }
            )

        if budgets and regions:
            has_relation = any(
                word in sentence
                for word in RELATION_WORDS
            )

            if not has_relation:
                blocked.append(
                    f"同句出现预算与区域但关系不明确：{sentence}"
                )
                continue

            if len(budgets) == 1 and len(regions) == 1:
                pairs.append(
                    {
                        "budget": budgets[0],
                        "region": regions[0],
                        "quote": sentence,
                        "confidence": "explicit_same_sentence",
                    }
                )
            elif len(budgets) == len(regions):
                for budget, region in zip(budgets, regions):
                    pairs.append(
                        {
                            "budget": budget,
                            "region": region,
                            "quote": sentence,
                            "confidence": "ordered_same_sentence",
                        }
                    )
            else:
                blocked.append(
                    f"预算与区域数量不一致，禁止自动配对：{sentence}"
                )

    budget_evidence = list(
        {
            (item["value"], item["quote"]): item
            for item in budget_evidence
        }.values()
    )
    region_evidence = list(
        {
            (item["value"], item["quote"]): item
            for item in region_evidence
        }.values()
    )
    pairs = list(
        {
            (
                item["budget"],
                item["region"],
                item["quote"],
            ): item
            for item in pairs
        }.values()
    )

    ranked = sorted(
        sentences,
        key=lambda item: (
            _quote_score(item),
            -len(item),
        ),
        reverse=True,
    )
    key_quotes = [
        quote
        for quote in _dedupe(ranked)
        if _quote_score(quote) > 0
    ][:5]

    budgets = _dedupe(
        item["value"]
        for item in budget_evidence
    )
    regions = _dedupe(
        item["value"]
        for item in region_evidence
    )

    mapping_mode = (
        "explicit_evidence"
        if len(pairs) >= 2
        else "disabled_no_clear_relation"
    )

    if not budgets:
        blocked.append("口播没有明确预算金额或档位，禁止虚构预算数字")
    if not regions:
        blocked.append("口播没有点名具体区域，禁止虚构区域名称")
    if mapping_mode != "explicit_evidence":
        blocked.append("预算与区域关系证据不足，禁止生成预算→区域对应表")

    return {
        "budgets": budgets,
        "regions": regions,
        "budget_evidence": budget_evidence,
        "region_evidence": region_evidence,
        "explicit_budget_region_pairs": pairs,
        "purposes": _purpose_flags(source["text"]),
        "key_quotes": key_quotes,
        "mapping_mode": mapping_mode,
        "blocked_claims": _dedupe(blocked),
        "sentence_count": len(sentences),
    }


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: int,
    max_lines: int = 4,
) -> List[str]:
    lines: List[str] = []
    current = ""

    for char in str(text or ""):
        candidate = current + char
        box = draw.textbbox((0, 0), candidate, font=font)

        if box[2] - box[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char

        if len(lines) >= max_lines:
            break

    if current and len(lines) < max_lines:
        lines.append(current)

    return lines[:max_lines]


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: List[str],
    x: int,
    y: int,
    font,
    fill,
    gap: int = 12,
) -> int:
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + gap
    return y


def _page_hook(
    path: Path,
    frame: Path | None,
    location: str,
    budgets: List[str],
):
    image = v37._crop(frame, v37.W, v37.H).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    for y in range(v37.H):
        alpha = 0 if y < 520 else int(
            min(220, (y - 520) / 1140 * 220)
        )
        overlay_draw.line(
            [(0, y), (v37.W, y)],
            fill=(0, 0, 0, alpha),
        )

    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (76, 86, 470, 156),
        radius=24,
        fill=v37.ACCENT + (250,),
    )
    draw.text(
        (108, 100),
        f"{location}买房事实版",
        font=v37._font(34, True),
        fill=(24, 29, 39, 255),
    )

    if budgets:
        headline = " / ".join(budgets[:3])
        second = f"在{location}怎么选？"
    else:
        headline = "预算不同"
        second = "选区逻辑不同"

    y = 1070

    for line in [headline, second]:
        font = v37._fit(draw, line, 1080, 108, 70)
        v37._shadow(draw, (76, y), line, font)
        y += font.size + 32

    draw.text(
        (80, y + 8),
        "只使用口播出现的信息，不替你乱配区域",
        font=v37._font(40, False),
        fill=v37.ACCENT + (255,),
    )

    image.convert("RGB").save(path, quality=95)


def _page_quote(
    path: Path,
    frame: Path | None,
    page: int,
    label: str,
    title: str,
    quote: str,
    note: str,
):
    image = v37._base()
    draw = ImageDraw.Draw(image)
    v37._label(draw, page, label)
    v37._paste_round(
        image,
        frame,
        (76, 175, 1166, 700),
        38,
    )

    draw.text(
        (78, 770),
        title,
        font=v37._font(68, True),
        fill=v37.DARK,
    )

    draw.rounded_rectangle(
        (76, 885, 1166, 1385),
        radius=38,
        fill=(248, 244, 234),
        outline=(231, 215, 176),
        width=3,
    )

    quote_font = v37._font(48, True)
    _draw_lines(
        draw,
        _wrap(
            draw,
            f"“{quote}”",
            quote_font,
            950,
            5,
        ),
        126,
        960,
        quote_font,
        v37.DARK,
        20,
    )

    draw.text(
        (92, 1460),
        note,
        font=v37._font(30, False),
        fill=(122, 128, 140),
    )

    image.save(path, quality=95)


def _page_regions(
    path: Path,
    frame: Path | None,
    regions: List[str],
    evidence: List[Dict[str, Any]],
):
    image = v37._base()
    draw = ImageDraw.Draw(image)
    v37._label(draw, 3, "区域")
    v37._paste_round(
        image,
        frame,
        (76, 175, 1166, 600),
        38,
    )

    if regions:
        draw.text(
            (78, 655),
            "口播点名了哪些区域？",
            font=v37._font(70, True),
            fill=v37.DARK,
        )
        draw.text(
            (82, 752),
            "只展示原文真实出现的名称",
            font=v37._font(38, False),
            fill=v37.MUTED,
        )

        y = 860

        for index, region in enumerate(regions[:3], 1):
            draw.rounded_rectangle(
                (76, y, 1166, y + 160),
                radius=30,
                fill=(249, 247, 241),
                outline=(231, 220, 198),
                width=2,
            )
            draw.ellipse(
                (112, y + 42, 188, y + 118),
                fill=v37.ACCENT,
            )
            draw.text(
                (137, y + 52),
                str(index),
                font=v37._font(34, True),
                fill=(255, 255, 255),
            )
            draw.text(
                (230, y + 35),
                region,
                font=v37._font(48, True),
                fill=v37.DARK,
            )

            quote = next(
                (
                    item["quote"]
                    for item in evidence
                    if item["value"] == region
                ),
                "",
            )
            short = quote[:34] + (
                "…" if len(quote) > 34 else ""
            )
            draw.text(
                (230, y + 98),
                short,
                font=v37._font(28, False),
                fill=v37.MUTED,
            )
            y += 200
    else:
        draw.text(
            (78, 655),
            "没有点名具体区域",
            font=v37._font(74, True),
            fill=v37.DARK,
        )
        draw.text(
            (82, 755),
            "所以这一页不硬编地名",
            font=v37._font(42, False),
            fill=(172, 117, 22),
        )

        items = [
            ("01", "先定用途"),
            ("02", "再定预算上限"),
            ("03", "最后看通勤与租客"),
        ]
        y = 900

        for number, text in items:
            draw.rounded_rectangle(
                (76, y, 1166, y + 150),
                radius=30,
                fill=(248, 244, 234),
            )
            draw.text(
                (120, y + 43),
                number,
                font=v37._font(34, True),
                fill=(159, 108, 23),
            )
            draw.text(
                (240, y + 32),
                text,
                font=v37._font(48, True),
                fill=v37.DARK,
            )
            y += 185

    draw.text(
        (82, 1510),
        "没有原文证据就不生成具体区域结论",
        font=v37._font(27, False),
        fill=(122, 128, 140),
    )
    image.save(path, quality=95)


def _page_mapping_guard(
    path: Path,
    frames: List[Path | None],
    facts: Dict[str, Any],
):
    pairs = facts["explicit_budget_region_pairs"]

    if facts["mapping_mode"] == "explicit_evidence":
        image = v37._base()
        draw = ImageDraw.Draw(image)
        v37._label(draw, 5, "对应")
        draw.text(
            (78, 190),
            "口播明确说了这些对应",
            font=v37._font(68, True),
            fill=v37.DARK,
        )
        draw.text(
            (82, 285),
            "每一条都保留原句证据",
            font=v37._font(38, False),
            fill=v37.MUTED,
        )

        tops = [390, 760, 1130]

        for index, pair in enumerate(pairs[:3]):
            top = tops[index]
            bottom = top + 310

            draw.rounded_rectangle(
                (76, top, 1166, bottom),
                radius=36,
                fill=(249, 247, 241),
                outline=(231, 220, 198),
                width=2,
            )
            v37._paste_round(
                image,
                frames[index] if index < len(frames) else None,
                (92, top + 16, 450, bottom - 16),
                28,
            )
            draw.text(
                (500, top + 35),
                pair["budget"],
                font=v37._font(50, True),
                fill=(154, 105, 24),
            )
            draw.text(
                (500, top + 105),
                f"→ {pair['region']}",
                font=v37._font(56, True),
                fill=(42, 93, 150),
            )

            quote = pair["quote"][:38]
            if len(pair["quote"]) > 38:
                quote += "…"

            draw.text(
                (500, top + 190),
                quote,
                font=v37._font(28, False),
                fill=v37.MUTED,
            )

        image.save(path, quality=95)
        return

    image = v37._base()
    draw = ImageDraw.Draw(image)
    v37._label(draw, 5, "校验")
    v37._paste_round(
        image,
        frames[0] if frames else None,
        (76, 175, 1166, 650),
        38,
    )

    draw.text(
        (78, 710),
        "不做预算→区域硬配",
        font=v37._font(68, True),
        fill=v37.DARK,
    )
    draw.text(
        (82, 805),
        "因为口播没有给出清楚对应关系",
        font=v37._font(38, False),
        fill=(172, 117, 22),
    )

    items = [
        ("01", "确认总价上限"),
        ("02", "确认自住还是投资"),
        ("03", "再比较通勤、租客与配套"),
    ]
    y = 930

    for number, text in items:
        draw.rounded_rectangle(
            (78, y, 1164, y + 145),
            radius=28,
            fill=(248, 244, 234),
        )
        draw.text(
            (118, y + 40),
            number,
            font=v37._font(34, True),
            fill=(159, 108, 23),
        )
        draw.text(
            (230, y + 30),
            text,
            font=v37._font(46, True),
            fill=v37.DARK,
        )
        y += 170

    draw.text(
        (82, 1510),
        "宁可少一个结论，也不生成错误对应",
        font=v37._font(28, False),
        fill=(122, 128, 140),
    )
    image.save(path, quality=95)


def _page_key_quotes(
    path: Path,
    frame: Path | None,
    quotes: List[str],
):
    image = v37._crop(frame, v37.W, v37.H).convert("RGBA")
    overlay = Image.new(
        "RGBA",
        image.size,
        (7, 12, 20, 125),
    )
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (76, 82, 430, 148),
        radius=24,
        fill=v37.ACCENT + (245,),
    )
    draw.text(
        (105, 95),
        "06  口播重点",
        font=v37._font(31, True),
        fill=(25, 31, 42, 255),
    )
    draw.text(
        (76, 230),
        "最值得记住的 3 句话",
        font=v37._font(72, True),
        fill=(255, 255, 255, 255),
    )

    safe_quotes = list(quotes[:3])

    while len(safe_quotes) < 3:
        safe_quotes.append(
            "先把预算、用途和通勤条件说清楚"
        )

    y = 480

    for index, quote in enumerate(safe_quotes, 1):
        draw.rounded_rectangle(
            (76, y, 1166, y + 300),
            radius=38,
            fill=(13, 20, 31, 205),
            outline=(255, 255, 255, 70),
            width=2,
        )
        draw.text(
            (120, y + 48),
            f"0{index}",
            font=v37._font(42, True),
            fill=v37.ACCENT + (255,),
        )

        font = v37._font(39, True)
        _draw_lines(
            draw,
            _wrap(
                draw,
                quote,
                font,
                820,
                4,
            ),
            250,
            y + 42,
            font,
            (255, 255, 255, 255),
            14,
        )
        y += 340

    image.convert("RGB").save(path, quality=95)


def _write_trace(
    package_dir: Path,
    source: Dict[str, Any],
    facts: Dict[str, Any],
    page_plan: List[Dict[str, Any]],
) -> Path:
    trace = {
        "version": VERSION,
        "style": STYLE,
        "generated_at": int(time.time()),
        "source": {
            "origins": source["origins"],
            "char_count": source["char_count"],
            "sha256": source["sha256"],
        },
        "facts": facts,
        "page_plan": page_plan,
        "rules": {
            "invent_budget_numbers": False,
            "invent_region_names": False,
            "budget_region_mapping_requires_explicit_evidence": True,
            "all_dynamic_claims_keep_source_quote": True,
        },
    }

    path = package_dir / "content_trace.json"
    path.write_text(
        json.dumps(
            trace,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _append_trace(package_dir: Path, trace_path: Path) -> None:
    zip_path = package_dir / "images.zip"

    if not zip_path.exists():
        return

    with zipfile.ZipFile(
        zip_path,
        "a",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.write(
            trace_path,
            arcname=trace_path.name,
        )


def generate_fact_checked_story(
    payload: Dict[str, Any],
    job: Dict[str, Any],
    video: Path | None,
    graphic_root: Path,
    public_base: str,
    zip_func: Callable[
        [Path, List[Dict[str, Any]]],
        str,
    ],
) -> Dict[str, Any]:
    job_id = str(payload.get("job_id") or "").strip()
    title = str(payload.get("title") or "").strip()
    cta = str(payload.get("cta") or "").strip()
    keywords = payload.get("keywords") or []

    source = _source_bundle(payload, job)

    if source["char_count"] < 12:
        return {
            "ok": False,
            "error": "source_script_missing",
            "message": (
                "没有读取到完整口播，已停止生成，"
                "避免用标题和模板硬编内容。"
            ),
            "job_id": job_id,
            "source_origins": source["origins"],
            "required_action": (
                "确认任务 JSON、script/tts/subtitle 文件仍保存在任务目录"
            ),
        }

    facts = _analyse(source)
    location = v37._location(
        " ".join(
            [
                title,
                source["text"],
                " ".join(str(item) for item in keywords),
            ]
        )
    )

    package_id = (
        f"xhs_fact_v5_{int(time.time())}_"
        f"{random.randint(1000, 9999)}"
    )
    package_dir = graphic_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    frames = v37._frames(video, package_dir)

    quotes = facts["key_quotes"]
    primary_quote = quotes[0] if quotes else source["text"][:80]
    second_quote = quotes[1] if len(quotes) > 1 else primary_quote

    compare_allowed = (
        facts["purposes"]["investment"]
        and facts["purposes"]["self_use"]
    )

    page_plan = [
        {
            "page": 1,
            "type": "hook",
            "evidence": facts["budgets"][:3],
        },
        {
            "page": 2,
            "type": "source_quote",
            "evidence": primary_quote,
        },
        {
            "page": 3,
            "type": (
                "named_regions"
                if facts["regions"]
                else "safe_method_no_regions"
            ),
            "evidence": facts["region_evidence"],
        },
        {
            "page": 4,
            "type": (
                "investment_self_use_compare"
                if compare_allowed
                else "source_quote"
            ),
            "evidence": (
                facts["purposes"]
                if compare_allowed
                else second_quote
            ),
        },
        {
            "page": 5,
            "type": facts["mapping_mode"],
            "evidence": facts["explicit_budget_region_pairs"],
        },
        {
            "page": 6,
            "type": "key_source_quotes",
            "evidence": quotes[:3],
        },
        {
            "page": 7,
            "type": "cta",
            "evidence": cta,
        },
    ]

    page_defs = [
        (
            "xhs_01_hook.jpg",
            "事实钩子封面",
            "实景 + 真实预算钩子",
            lambda path: _page_hook(
                path,
                frames[0],
                location,
                facts["budgets"],
            ),
        ),
        (
            "xhs_02_source_quote.jpg",
            "口播核心原句",
            "实景 + 原句证据卡",
            lambda path: _page_quote(
                path,
                frames[1],
                2,
                "原句",
                "先看口播怎么说",
                primary_quote,
                "本页文字直接来自完整口播",
            ),
        ),
        (
            "xhs_03_regions_checked.jpg",
            "区域事实校验",
            "实景 + 真实区域或安全方法页",
            lambda path: _page_regions(
                path,
                frames[2],
                facts["regions"],
                facts["region_evidence"],
            ),
        ),
        (
            "xhs_04_purpose_checked.jpg",
            (
                "投资与自住对比"
                if compare_allowed
                else "第二条口播原句"
            ),
            (
                "实景 + 用途对比"
                if compare_allowed
                else "实景 + 原句证据卡"
            ),
            (
                lambda path: v37._page_compare(
                    path,
                    frames[3],
                )
                if compare_allowed
                else _page_quote(
                    path,
                    frames[3],
                    4,
                    "证据",
                    "继续看口播重点",
                    second_quote,
                    "未同时出现投资和自住时，不强行生成对比结论",
                )
            ),
        ),
        (
            "xhs_05_mapping_guard.jpg",
            "预算区域关系校验",
            "证据对应表或安全清单",
            lambda path: _page_mapping_guard(
                path,
                [
                    frames[2],
                    frames[4],
                    frames[5],
                ],
                facts,
            ),
        ),
        (
            "xhs_06_key_quotes.jpg",
            "口播重点三条",
            "全屏实景 + 原句重点卡",
            lambda path: _page_key_quotes(
                path,
                frames[5],
                quotes,
            ),
        ),
        (
            "xhs_07_save_and_comment.jpg",
            "收藏清单与CTA",
            "实景 + 收藏清单 + 引流",
            lambda path: v37._page_cta(
                path,
                frames[6],
                cta,
            ),
        ),
    ]

    images: List[Dict[str, Any]] = []

    for page, (
        filename,
        page_title,
        role,
        drawer,
    ) in enumerate(page_defs, 1):
        output = package_dir / filename
        drawer(output)

        images.append(
            {
                "url": (
                    f"{public_base}/"
                    f"{package_id}/"
                    f"{filename}"
                ),
                "path": str(output),
                "title": page_title,
                "role": f"第{page}页 · {role}",
                "page": page,
                "visual_type": role,
                "width": v37.W,
                "height": v37.H,
            }
        )

    trace_path = _write_trace(
        package_dir,
        source,
        facts,
        page_plan,
    )

    zip_url = zip_func(package_dir, images)
    _append_trace(package_dir, trace_path)

    return {
        "ok": True,
        "mode": "xiaohongshu",
        "style": STYLE,
        "version": VERSION,
        "package_id": package_id,
        "job_id": job_id,
        "title": title,
        "page_count": len(images),
        "location": location,
        "images": images,
        "fact_guard": {
            "source_char_count": source["char_count"],
            "source_sha256": source["sha256"],
            "source_origins": source["origins"],
            "budgets": facts["budgets"],
            "regions": facts["regions"],
            "purposes": facts["purposes"],
            "mapping_mode": facts["mapping_mode"],
            "explicit_pair_count": len(
                facts["explicit_budget_region_pairs"]
            ),
            "blocked_claims": facts["blocked_claims"],
        },
        "content_trace_url": (
            f"{public_base}/"
            f"{package_id}/"
            "content_trace.json"
        ),
        "publish_title": (
            (
                " / ".join(facts["budgets"][:3])
                + f"，在{location}怎么选？"
            )
            if facts["budgets"]
            else f"{location}买房：预算不同，选区逻辑不同"
        ),
        "publish_description": (
            f"根据完整口播整理{location}买房重点。"
            "没有原文证据的预算、区域和对应关系不会生成。"
        ),
        "hashtags": [
            f"{location}买房",
            "海外置业",
            "房产投资",
            "买房避坑",
            "小红书房产",
        ],
        "download_zip_url": zip_url,
        "warnings": facts["blocked_claims"],
        "visual_rules": {
            "photo_pages": [1, 2, 3, 4, 5, 6, 7],
            "max_pure_text_pages": 0,
            "invent_budget_numbers": False,
            "invent_region_names": False,
            "mapping_requires_evidence": True,
            "fal_called": False,
        },
    }
