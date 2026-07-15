from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import Body
from app.services.xhs_fact_guard_v10_38 import generate_fact_checked_story
# AI_VIDEO_V10_38_XHS_FACT_GUARD_ROUTE
from app.services.xhs_visual_story_v10_37 import generate_visual_story
# AI_VIDEO_V10_37_XHS_VISUAL_STORY_ROUTE
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

BASE = Path("/opt/ai-video")
STORAGE = BASE / "storage"
GRAPHIC_ROOT = STORAGE / "graphic_window"
JOB_ROOT = STORAGE / "v10_34" / "final_jobs"
PUBLIC_BASE = "/storage/graphic_window"

GRAPHIC_ROOT.mkdir(parents=True, exist_ok=True)

ACCENT = (218, 166, 52)
DARK = (17, 24, 39)
MUTED = (71, 85, 105)
CREAM = (249, 246, 238)
CARD = (255, 255, 255)


from app.services.review_packaging_automation_provider import install_review_packaging_automation
# AI_VIDEO_V10_39_REVIEW_AUTO_PACKAGING

from app.services.main_workflow_provider import install_main_workflow_provider
# AI_VIDEO_V10_40_1_REAL_MAIN_ADAPTER
from app.services.integration_hub_v10_40_7 import install_integration_hub_v10_40_7
# AI_VIDEO_V10_40_7_ENGINE_SOURCE_FIX

def _font(size: int, bold: bool = True):
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in candidates:
        if p and Path(p).exists():
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _clean(s: str, limit: int = 28) -> str:
    s = str(s or "").strip()
    s = re.sub(r"[，。！？、,.!?：:；;（）()《》“”‘’\"'\\[\\]{}<>~·`@#$%^&*_+=|/\\\\]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    bads = [
        "AI-VIDEO", "AI VIDEO", "图文窗口", "小红书封面", "强标题封面", "顾问封面",
        "封面结果", "视频封面结果", "1080", "1920", "1242", "1660",
        "模板", "尺寸", "cover", "debug", "无 iframe", "马来西亚房产",
        "9:16", "3:4", "1:1"
    ]
    for b in bads:
        s = s.replace(b, "")
    return s.strip()[:limit]


def _title_strategy(title: str) -> Dict[str, str]:
    title = _clean(title, 40)

    if "预算" in title:
        hook = "预算不同"
        hook2 = "选区完全不同"
    elif "投资" in title and "自住" in title:
        hook = "投资还是自住"
        hook2 = "先别急着看房"
    else:
        hook = "吉隆坡买房"
        hook2 = "先看需求再选区"

    if "吉隆坡" in title and "投资" in title:
        cover = "吉隆坡投资房"
    elif "吉隆坡" in title:
        cover = "吉隆坡买房"
    else:
        cover = "吉隆坡买房"

    return {
        "cover_main": cover,
        "cover_sub": hook + " " + hook2,
        "xhs_hook": "别急着买吉隆坡房",
        "xhs_sub": "预算和用途不同 区域选择完全不一样",
    }


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int = 3) -> List[str]:
    text = _clean(text, 80)
    lines, cur = [], ""
    for ch in text:
        test = cur + ch
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def _draw_lines(draw, lines, x, y, font, fill, gap=12):
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + gap
    return y


def _find_job(job_id: str) -> Dict[str, Any]:
    if job_id:
        p = JOB_ROOT / f"{job_id}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}

    files = sorted(JOB_ROOT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("status") == "completed":
                return data
        except Exception:
            pass
    return {}


def _clean_video_path(job_id: str, job: Dict[str, Any]) -> Path | None:
    candidates = [
        JOB_ROOT / job_id / "fit_audio_exact_rescue" / "video_fit_audio_length.mp4",
        JOB_ROOT / job_id / "fit_audio_exact_rescue" / "video_fit_exact_audio_length.mp4",
        JOB_ROOT / job_id / "compose_video.mp4",
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 1024 * 1024:
            return p

    vals = []
    for k in ["local_path", "final_local_path"]:
        if job.get(k):
            vals.append(str(job.get(k)))
    r = job.get("result") or {}
    for k in ["local_path", "final_local_path"]:
        if r.get(k):
            vals.append(str(r.get(k)))

    for v in vals:
        low = v.lower()
        if "subtitle" in low or "subtitles" in low or "ai_director" in low or "script_locked" in low:
            continue
        p = Path(v)
        if p.exists() and p.suffix == ".mp4":
            return p

    return None


def _extract_frame(video: Path | None, out: Path, width: int, height: int, second: str = "2.8") -> Path | None:
    if not video or not video.exists():
        return None

    tmp = out.with_suffix(".frame.jpg")
    cmd = [
        "ffmpeg", "-y",
        "-ss", second,
        "-i", str(video),
        "-vframes", "1",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
        str(tmp)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45)
        if tmp.exists() and tmp.stat().st_size > 2048:
            return tmp
    except Exception:
        pass
    return None


def _photo_bg(width: int, height: int, frame: Path | None):
    if frame and frame.exists():
        img = Image.open(frame).convert("RGB").resize((width, height))
        img = ImageEnhance.Contrast(img).enhance(1.08)
        img = ImageEnhance.Color(img).enhance(0.92)
        return img

    img = Image.new("RGB", (width, height), (27, 37, 56))
    d = ImageDraw.Draw(img)
    for y in range(height):
        r = int(22 + y / height * 35)
        g = int(32 + y / height * 24)
        b = int(48 + y / height * 36)
        d.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def _gradient_overlay(img: Image.Image, bottom: int = 185):
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    for y in range(h):
        alpha = 0
        if y > h * 0.36:
            alpha = int(bottom * ((y - h * 0.36) / (h * 0.64)))
        if y < h * 0.18:
            alpha = max(alpha, int(65 * (1 - y / (h * 0.18))))
        d.line([(0, y), (w, y)], fill=(0, 0, 0, max(0, min(215, alpha))))

    return Image.alpha_composite(img.convert("RGBA"), overlay)


def _shadow_text(draw, xy, text, font, fill=(255, 255, 255, 255), offset=5):
    x, y = xy
    draw.text((x + offset, y + offset), text, font=font, fill=(0, 0, 0, 150))
    draw.text((x, y), text, font=font, fill=fill)


def _draw_916_cover(path: Path, frame: Path | None, title: Dict[str, str]):
    w, h = 1080, 1920
    img = _gradient_overlay(_photo_bg(w, h, frame), bottom=195)
    draw = ImageDraw.Draw(img)

    main_font = _font(112, True)
    sub_font = _font(46, False)

    x = 82
    y = 1200

    draw.rounded_rectangle((x, y - 58, x + 144, y - 46), radius=6, fill=ACCENT + (255,))

    for line in _wrap(draw, title["cover_main"], main_font, w - 160, 2):
        _shadow_text(draw, (x, y), line, main_font)
        y += 126

    y += 18
    draw.text((x, y), title["cover_sub"], font=sub_font, fill=ACCENT + (255,))

    img.convert("RGB").save(path, quality=95)


def _blank_xhs():
    w, h = 1242, 1660
    img = Image.new("RGB", (w, h), CREAM)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((56, 56, w - 56, h - 56), radius=44, fill=CARD, outline=(232, 224, 207), width=2)
    return img


def _page_no(draw, page: int):
    small = _font(28, False)
    draw.text((92, 92), f"{page:02d}", font=small, fill=(130, 104, 61))
    draw.rounded_rectangle((92, 138, 218, 150), radius=6, fill=ACCENT)


def _draw_xhs_hook(path: Path, title: Dict[str, str], frame: Path | None):
    w, h = 1242, 1660
    img = _gradient_overlay(_photo_bg(w, h, frame), bottom=205)
    draw = ImageDraw.Draw(img)

    main_font = _font(104, True)
    sub_font = _font(44, False)

    x, y = 86, 1040
    draw.rounded_rectangle((x, y - 58, x + 150, y - 46), radius=6, fill=ACCENT + (255,))

    for line in _wrap(draw, title["xhs_hook"], main_font, w - 172, 2):
        _shadow_text(draw, (x, y), line, main_font)
        y += 118

    y += 22
    draw.text((x, y), title["xhs_sub"], font=sub_font, fill=ACCENT + (255,))

    img.convert("RGB").save(path, quality=95)


def _draw_xhs_text(path: Path, page: int, title: str, body: str):
    img = _blank_xhs()
    draw = ImageDraw.Draw(img)
    _page_no(draw, page)

    title_font = _font(86, True)
    body_font = _font(44, False)

    y = 280
    y = _draw_lines(draw, _wrap(draw, title, title_font, 980, 3), 92, y, title_font, DARK, 18)
    y += 48
    _draw_lines(draw, _wrap(draw, body, body_font, 980, 5), 96, y, body_font, MUTED, 18)

    img.save(path, quality=95)


def _draw_xhs_map(path: Path):
    img = _blank_xhs()
    draw = ImageDraw.Draw(img)
    _page_no(draw, 3)

    title_font = _font(78, True)
    body_font = _font(36, False)
    node_font = _font(34, True)

    draw.text((92, 250), "区域怎么判断", font=title_font, fill=DARK)
    draw.text((96, 360), "不要先问哪里便宜 先看你的用途", font=body_font, fill=MUTED)

    # 视觉联想：区域选择路径图
    y = 690
    x1, x2, x3 = 230, 621, 1012
    draw.line((x1, y, x3, y), fill=(207, 180, 112), width=8)

    nodes = [
        (x1, "核心区", "投资出租"),
        (x2, "成熟社区", "自住生活"),
        (x3, "商圈外溢", "预算友好"),
    ]

    for x, name, desc in nodes:
        draw.ellipse((x - 58, y - 58, x + 58, y + 58), fill=(255, 255, 255), outline=ACCENT, width=6)
        bbox = draw.textbbox((0, 0), name, font=node_font)
        draw.text((x - (bbox[2] - bbox[0]) / 2, y + 95), name, font=node_font, fill=DARK)
        bb2 = draw.textbbox((0, 0), desc, font=body_font)
        draw.text((x - (bb2[2] - bb2[0]) / 2, y + 148), desc, font=body_font, fill=MUTED)

    draw.rounded_rectangle((92, 1180, 1150, 1340), radius=28, fill=(250, 247, 238), outline=(235, 218, 170), width=2)
    draw.text((132, 1225), "判断顺序：用途 → 预算 → 通勤 → 出租", font=_font(40, True), fill=DARK)

    img.save(path, quality=95)


def _draw_xhs_compare(path: Path):
    img = _blank_xhs()
    draw = ImageDraw.Draw(img)
    _page_no(draw, 4)

    title_font = _font(78, True)
    head_font = _font(48, True)
    item_font = _font(36, False)

    draw.text((92, 245), "投资和自住", font=title_font, fill=DARK)
    draw.text((96, 350), "看的不是同一套逻辑", font=_font(42, False), fill=MUTED)

    left = (92, 520, 590, 1260)
    right = (652, 520, 1150, 1260)

    draw.rounded_rectangle(left, radius=32, fill=(247, 244, 235), outline=(233, 215, 166), width=3)
    draw.rounded_rectangle(right, radius=32, fill=(244, 247, 251), outline=(202, 213, 226), width=3)

    draw.text((145, 590), "投资", font=head_font, fill=DARK)
    draw.text((705, 590), "自住", font=head_font, fill=DARK)

    for i, t in enumerate(["租金需求", "出租稳定", "转手流动"]):
        draw.text((145, 720 + i * 130), "· " + t, font=item_font, fill=MUTED)

    for i, t in enumerate(["通勤时间", "生活配套", "社区成熟"]):
        draw.text((705, 720 + i * 130), "· " + t, font=item_font, fill=MUTED)

    img.save(path, quality=95)


def _draw_xhs_budget(path: Path):
    img = _blank_xhs()
    draw = ImageDraw.Draw(img)
    _page_no(draw, 5)

    title_font = _font(78, True)
    body_font = _font(38, False)
    head_font = _font(42, True)

    draw.text((92, 245), "预算决定区域", font=title_font, fill=DARK)
    draw.text((96, 350), "不要拿同一个标准看所有房子", font=body_font, fill=MUTED)

    cards = [
        ("高预算", "核心区 / 国际化区域", (250, 247, 238)),
        ("中预算", "交通和配套平衡", (245, 248, 252)),
        ("低预算", "留在商圈辐射范围", (247, 246, 243)),
    ]

    y = 540
    for name, desc, color in cards:
        draw.rounded_rectangle((92, y, 1150, y + 210), radius=30, fill=color, outline=(232, 224, 207), width=2)
        draw.text((140, y + 46), name, font=head_font, fill=DARK)
        draw.text((140, y + 112), desc, font=body_font, fill=MUTED)
        y += 260

    img.save(path, quality=95)


def _draw_xhs_checklist(path: Path):
    img = _blank_xhs()
    draw = ImageDraw.Draw(img)
    _page_no(draw, 6)

    title_font = _font(78, True)
    item_font = _font(42, False)

    draw.text((92, 245), "三个坑别踩", font=title_font, fill=DARK)

    items = [
        "只看价格 不看出租需求",
        "只看新盘 不看生活配套",
        "只看宣传 不看后期转手",
    ]

    y = 500
    for i, t in enumerate(items, 1):
        draw.rounded_rectangle((92, y, 1150, y + 170), radius=30, fill=(250, 247, 238), outline=(233, 215, 166), width=2)
        draw.ellipse((132, y + 50, 202, y + 120), fill=ACCENT)
        draw.text((155, y + 58), str(i), font=_font(34, True), fill=(255, 255, 255))
        draw.text((245, y + 58), t, font=item_font, fill=DARK)
        y += 220

    img.save(path, quality=95)


def _draw_xhs_cta(path: Path, cta: str):
    img = _blank_xhs()
    draw = ImageDraw.Draw(img)
    _page_no(draw, 7)

    title_font = _font(76, True)
    body_font = _font(42, False)
    small_font = _font(36, False)

    draw.text((92, 245), "不知道选哪里", font=title_font, fill=DARK)
    draw.text((96, 350), "把这3个信息发我", font=body_font, fill=MUTED)

    box = (120, 560, 1122, 1160)
    draw.rounded_rectangle(box, radius=36, fill=(247, 244, 235), outline=(233, 215, 166), width=3)

    for i, t in enumerate(["预算", "用途", "自住人数或出租目标"], 1):
        y = 650 + (i - 1) * 140
        draw.text((180, y), f"{i}. {t}", font=body_font, fill=DARK)

    final = _clean(cta, 38) or "评论区告诉我预算和用途 我帮你拆区域"
    draw.text((130, 1280), "评论区留言：", font=small_font, fill=MUTED)
    _draw_lines(draw, _wrap(draw, final, body_font, 980, 2), 130, 1340, body_font, DARK, 16)

    img.save(path, quality=95)


def _zip(pkg_dir: Path, images: List[Dict[str, Any]]):
    zp = pkg_dir / "images.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for img in images:
            p = Path(img["path"])
            if p.exists():
                z.write(p, arcname=p.name)
    return f"{PUBLIC_BASE}/{pkg_dir.name}/images.zip" if zp.exists() else ""


# AI_VIDEO_V10_36_THREE_COVER_VARIANTS
def _cover_location(text: str) -> str:
    raw = str(text or "")
    for name in ["吉隆坡", "马来西亚", "新加坡", "曼谷", "迪拜"]:
        if name in raw:
            return name
    return "海外"


def _extract_budget_tokens(text: str) -> List[str]:
    raw = str(text or "")
    patterns = [
        r"(?<!\d)(\d{1,4}(?:\.\d+)?\s*万元)(?!\d)",
        r"(?<!\d)(\d{1,4}(?:\.\d+)?\s*万)(?!\d)",
        r"(?<!\d)(RM\s*\d[\d,]*(?:\.\d+)?)",
        r"(?<!\d)(MYR\s*\d[\d,]*(?:\.\d+)?)",
        r"(?<!\d)(\d[\d,]*(?:\.\d+)?\s*马币)",
    ]
    found: List[str] = []
    for pattern in patterns:
        for value in re.findall(pattern, raw, flags=re.IGNORECASE):
            cleaned = re.sub(r"\s+", "", str(value))
            if cleaned and cleaned not in found:
                found.append(cleaned)
            if len(found) >= 3:
                return found
    return found


def _cover_variants(title: str, script_text: str, keywords: Any) -> List[Dict[str, Any]]:
    keyword_text = " ".join(str(x) for x in (keywords or []))
    source = " ".join([str(title or ""), str(script_text or ""), keyword_text])
    location = _cover_location(source)
    budgets = _extract_budget_tokens(source)

    if len(budgets) >= 3:
        numeric_lines = [
            f"{budgets[0]} / {budgets[1]}",
            f"{budgets[2]}买哪个区",
        ]
        numeric_sub = f"{location}预算选区对照"
    elif len(budgets) == 2:
        numeric_lines = [
            f"{budgets[0]} / {budgets[1]}",
            f"{location}怎么选区",
        ]
        numeric_sub = "两档预算一次讲清"
    elif len(budgets) == 1:
        numeric_lines = [
            f"预算{budgets[0]}",
            f"{location}买哪个区",
        ]
        numeric_sub = "自住和投资逻辑不同"
    else:
        numeric_lines = [
            "三档预算",
            f"{location}怎么选区",
        ]
        numeric_sub = "低预算 / 中预算 / 高预算"

    return [
        {
            "key": "numeric",
            "name": "数字型",
            "badge": "预算对照",
            "lines": numeric_lines,
            "sub": numeric_sub,
            "reason": "让用户快速对号入座，适合预算选区主题",
        },
        {
            "key": "pitfall",
            "name": "避坑型",
            "badge": "买房避坑",
            "lines": ["预算再高", "也别买错区"],
            "sub": f"{location}买房先看用途",
            "reason": "突出错误成本，增强停留和点击冲动",
        },
        {
            "key": "result",
            "name": "结果型",
            "badge": "选区逻辑",
            "lines": ["自住 / 出租 / 升值", "选区完全不同"],
            "sub": "先定需求 再看房",
            "reason": "直接展示三种结果差异，适合搜索与收藏",
        },
    ]


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int = 102, minimum: int = 62):
    size = start
    while size > minimum:
        font = _font(size, True)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 4
    return _font(minimum, True)


def _draw_916_variant(path: Path, frame: Path | None, variant: Dict[str, Any]):
    w, h = 1080, 1920
    img = _gradient_overlay(_photo_bg(w, h, frame), bottom=205)
    draw = ImageDraw.Draw(img)

    x = 76
    content_top = 1110
    max_width = w - 152

    badge_font = _font(34, True)
    badge = str(variant.get("badge") or "封面候选")
    badge_box = draw.textbbox((0, 0), badge, font=badge_font)
    badge_w = badge_box[2] - badge_box[0] + 54
    draw.rounded_rectangle(
        (x, content_top, x + badge_w, content_top + 66),
        radius=22,
        fill=ACCENT + (245,),
    )
    draw.text(
        (x + 27, content_top + 12),
        badge,
        font=badge_font,
        fill=(26, 31, 42, 255),
    )

    y = content_top + 98
    for raw_line in list(variant.get("lines") or [])[:2]:
        line = _clean(str(raw_line), 30)
        font = _fit_font(draw, line, max_width, start=106, minimum=64)
        _shadow_text(draw, (x, y), line, font)
        y += font.size + 30

    y += 8
    sub = _clean(str(variant.get("sub") or ""), 42)
    sub_font = _fit_font(draw, sub, max_width, start=46, minimum=34)
    draw.text((x, y), sub, font=sub_font, fill=ACCENT + (255,))

    img.convert("RGB").save(path, quality=95)

def install_graphic_window_provider(app):
    if getattr(app.state, "graphic_window_v10_40_7_installed", False):
        return

    app.state.graphic_window_v10_40_7_installed = True
    install_integration_hub_v10_40_7(app)
    install_main_workflow_provider(app)
    install_review_packaging_automation(app)
    @app.get("/api/graphic-window/health")
    def health():
        return {
            "ok": True,
            "mode": "graphic_window_v7_7_engine_source_fix",
            "rule": "cover_only_9_16_xhs_uses_info_cards_maps_tables_budget_checklist_cta",
            "storage": str(GRAPHIC_ROOT),
            "pillow": True,
            "ffmpeg": bool(shutil.which("ffmpeg")),
        }

    @app.get("/api/graphic-window/latest-video-job")
    def latest_video_job():
        job = _find_job("")
        return {
            "ok": bool(job),
            "job_id": job.get("job_id") or job.get("id") or "",
            "title": job.get("topic") or job.get("title") or "吉隆坡买房预算不同区域不同",
            "video_url": job.get("final_video_url") or job.get("video_url") or job.get("output_url") or "",
            "status": job.get("status") or "",
            "stage": job.get("stage") or "",
        }

    @app.post("/api/graphic-window/video-cover/generate")
    def generate_video_cover(payload: Dict[str, Any] = Body(default_factory=dict)):
        job_id = str(payload.get("job_id") or "").strip()
        title = str(payload.get("title") or "").strip()
        script_text = str(payload.get("script_text") or "").strip()
        keywords = payload.get("keywords") or []

        job = _find_job(job_id)
        if not script_text:
            script_text = str(
                job.get("script_text")
                or job.get("script")
                or job.get("tts_script")
                or ""
            )

        video = _clean_video_path(job_id, job)
        variants = _cover_variants(title, script_text, keywords)

        pkg_id = f"cover916_v3_{int(time.time())}_{random.randint(1000,9999)}"
        pkg_dir = GRAPHIC_ROOT / pkg_id
        pkg_dir.mkdir(parents=True, exist_ok=True)

        frame_target = pkg_dir / "cover_frame_source.jpg"
        frame = _extract_frame(video, frame_target, 1080, 1920, "2.8")

        images: List[Dict[str, Any]] = []
        for index, variant in enumerate(variants, 1):
            out = pkg_dir / f"cover_{index:02d}_{variant['key']}.jpg"
            _draw_916_variant(out, frame, variant)
            images.append(
                {
                    "url": f"{PUBLIC_BASE}/{pkg_id}/{out.name}",
                    "path": str(out),
                    "title": " / ".join(variant["lines"]),
                    "role": f"9:16视频封面 · {variant['name']}",
                    "variant_key": variant["key"],
                    "variant_name": variant["name"],
                    "badge": variant["badge"],
                    "subtitle": variant["sub"],
                    "reason": variant["reason"],
                    "width": 1080,
                    "height": 1920,
                }
            )

        zip_url = _zip(pkg_dir, images)
        recommended = "numeric" if ("预算" in title or _extract_budget_tokens(script_text)) else "pitfall"

        return {
            "ok": True,
            "mode": "video_cover",
            "style": "v3_three_click_cover_variants",
            "package_id": pkg_id,
            "job_id": job_id,
            "title": title,
            "cover_count": len(images),
            "recommended_variant": recommended,
            "images": images,
            "cover_variants": variants,
            "publish_title": images[0]["title"] if images else title,
            "publish_description": (
                "已生成3套9:16封面候选：数字型、避坑型、结果型。"
                "数字型只使用文案中真实出现的金额；没有明确金额时使用‘三档预算’，不虚构数字。"
            ),
            "hashtags": ["吉隆坡买房", "马来西亚房产", "海外置业", "房产投资"],
            "download_zip_url": zip_url,
            "warnings": [],
        }

    @app.post("/api/graphic-window/xiaohongshu/generate")
    def generate_xhs(payload: Dict[str, Any] = Body(default_factory=dict)):
        job_id = str(payload.get("job_id") or "").strip()
        job = _find_job(job_id)
        video = _clean_video_path(job_id, job)
        return generate_fact_checked_story(
            payload=payload,
            job=job,
            video=video,
            graphic_root=GRAPHIC_ROOT,
            public_base=PUBLIC_BASE,
            zip_func=_zip,
        )

