from __future__ import annotations

import re
import subprocess
import time
import random
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

W, H = 1242, 1660
ACCENT = (218, 166, 52)
DARK = (17, 24, 39)
MUTED = (76, 86, 103)
CREAM = (246, 243, 236)


def _font(size: int, bold: bool = True):
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _fit(draw: ImageDraw.ImageDraw, text: str, width: int, start: int, minimum: int):
    size = start
    while size > minimum:
        font = _font(size, True)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= width:
            return font
        size -= 4
    return _font(minimum, True)


def _duration(video: Path | None) -> float:
    if not video or not video.exists():
        return 0.0
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
        return max(0.0, float((result.stdout or "0").strip() or 0))
    except Exception:
        return 0.0


def _extract(video: Path | None, out: Path, second: float) -> Path | None:
    if not video or not video.exists():
        return None
    temp = out.with_suffix(".frame.jpg")
    cmd = [
        "ffmpeg", "-y", "-ss", f"{second:.2f}", "-i", str(video),
        "-vframes", "1",
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
        str(temp),
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45)
        if temp.exists() and temp.stat().st_size > 2048:
            return temp
    except Exception:
        pass
    return None


def _frames(video: Path | None, package_dir: Path) -> List[Path | None]:
    duration = _duration(video)
    ratios = [0.06, 0.18, 0.32, 0.47, 0.62, 0.77, 0.90]
    if duration <= 0:
        seconds = [2.0, 5.0, 8.0, 11.0, 14.0, 17.0, 20.0]
    else:
        end = max(0.8, duration - 0.7)
        seconds = [min(end, max(0.5, duration * ratio)) for ratio in ratios]
    result: List[Path | None] = []
    for index, second in enumerate(seconds, 1):
        result.append(_extract(video, package_dir / f"story_{index:02d}.jpg", second))
    return result


def _crop(frame: Path | None, width: int, height: int) -> Image.Image:
    if frame and frame.exists():
        image = Image.open(frame).convert("RGB")
        image = ImageEnhance.Contrast(image).enhance(1.06)
        ratio = image.width / max(1, image.height)
        target = width / max(1, height)
        if ratio > target:
            new_width = int(image.height * target)
            left = max(0, (image.width - new_width) // 2)
            image = image.crop((left, 0, left + new_width, image.height))
        else:
            new_height = int(image.width / target)
            top = max(0, (image.height - new_height) // 2)
            image = image.crop((0, top, image.width, top + new_height))
        return image.resize((width, height))

    fallback = Image.new("RGB", (width, height), (30, 42, 60))
    draw = ImageDraw.Draw(fallback)
    for y in range(height):
        ratio = y / max(1, height)
        draw.line([(0, y), (width, y)], fill=(int(28 + ratio * 32), int(40 + ratio * 24), int(59 + ratio * 28)))
    return fallback


def _paste_round(canvas: Image.Image, frame: Path | None, box: Tuple[int, int, int, int], radius: int = 34):
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    image = _crop(frame, width, height)
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    canvas.paste(image, (left, top), mask)


def _base() -> Image.Image:
    image = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((44, 44, W - 44, H - 44), radius=44, fill=(255, 255, 255), outline=(230, 220, 201), width=2)
    return image


def _label(draw: ImageDraw.ImageDraw, page: int, text: str):
    draw.rounded_rectangle((78, 72, 280, 134), radius=22, fill=ACCENT)
    draw.text((104, 84), f"{page:02d}  {text}", font=_font(29, True), fill=(25, 31, 42))


def _shadow(draw: ImageDraw.ImageDraw, xy: Tuple[int, int], text: str, font):
    x, y = xy
    draw.text((x + 5, y + 5), text, font=font, fill=(0, 0, 0, 150))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))


def _location(text: str) -> str:
    for name in ["吉隆坡", "马来西亚", "新加坡", "曼谷", "迪拜", "东京", "大阪", "香港"]:
        if name in text:
            return name
    return "海外"


def _regions(text: str) -> List[str]:
    aliases = [
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
    ]
    found: List[str] = []
    low = text.lower()
    for label, words in aliases:
        if any(word.lower() in low for word in words):
            found.append(label)
        if len(found) == 3:
            return found
    for fallback in ["核心区", "成熟社区", "外溢区"]:
        if fallback not in found:
            found.append(fallback)
        if len(found) == 3:
            break
    return found


def _budgets(text: str) -> List[str]:
    patterns = [
        r"(?<!\d)(\d{1,4}(?:\.\d+)?\s*万元?)(?!\d)",
        r"(?<!\d)(RM\s*\d[\d,]*(?:\.\d+)?)",
        r"(?<!\d)(MYR\s*\d[\d,]*(?:\.\d+)?)",
        r"(?<!\d)(\d[\d,]*(?:\.\d+)?\s*马币)",
    ]
    found: List[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = re.sub(r"\s+", "", str(match))
            if value and value not in found:
                found.append(value)
            if len(found) == 3:
                return found
    return ["低预算", "中预算", "高预算"]


def _page_hook(path: Path, frame: Path | None, location: str, budgets: List[str]):
    image = _crop(frame, W, H).convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    for y in range(H):
        alpha = 0 if y < 520 else int(min(220, (y - 520) / 1140 * 220))
        draw_overlay.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((76, 86, 410, 156), radius=24, fill=ACCENT + (250,))
    draw.text((108, 100), f"{location}买房选区", font=_font(34, True), fill=(24, 29, 39, 255))
    first = " / ".join(budgets) if all("预算" not in item for item in budgets) else "三档预算"
    y = 1070
    for line in [first, "分别买哪里？"]:
        font = _fit(draw, line, 1080, 110, 74)
        _shadow(draw, (76, y), line, font)
        y += font.size + 32
    draw.text((80, y + 8), "自住、出租、升值，选择逻辑完全不同", font=_font(43, False), fill=ACCENT + (255,))
    image.convert("RGB").save(path, quality=95)


def _page_first_step(path: Path, frame: Path | None):
    image = _base()
    draw = ImageDraw.Draw(image)
    _label(draw, 2, "第一步")
    _paste_round(image, frame, (76, 175, 1166, 870), 38)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle((76, 640, 1166, 870), radius=38, fill=(0, 0, 0, 145))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image)
    draw.text((118, 696), "很多人第一步就错了", font=_font(72, True), fill=(255, 255, 255, 255))
    draw.rounded_rectangle((76, 930, 1166, 1485), radius=38, fill=(248, 244, 234, 255), outline=(231, 215, 176, 255), width=3)
    draw.text((124, 1000), "不是先看哪里便宜", font=_font(68, True), fill=DARK + (255,))
    draw.text((124, 1105), "而是先定用途", font=_font(88, True), fill=(172, 117, 22, 255))
    draw.rounded_rectangle((124, 1260, 1118, 1418), radius=28, fill=(255, 255, 255, 255))
    draw.text((164, 1305), "投资看租客与流动性｜自住看通勤与生活", font=_font(38, True), fill=MUTED + (255,))
    image.convert("RGB").save(path, quality=95)


def _page_regions(path: Path, frame: Path | None, regions: List[str]):
    image = _base()
    draw = ImageDraw.Draw(image)
    _label(draw, 3, "区域")
    _paste_round(image, frame, (76, 175, 1166, 600), 38)
    draw.text((78, 655), "区域怎么判断？", font=_font(76, True), fill=DARK)
    draw.text((82, 755), "先看用途，再看预算和通勤", font=_font(42, False), fill=MUTED)
    centers = [(225, 1060), (621, 925), (1017, 1105)]
    colors = [(246, 226, 178), (222, 235, 248), (232, 229, 247)]
    draw.line(centers, fill=(194, 160, 84), width=10, joint="curve")
    details = [("投资出租", "租客与流动性"), ("自住生活", "通勤与配套"), ("预算友好", "总价与潜力")]
    for index, ((x, y), region, color, detail) in enumerate(zip(centers, regions, colors, details), 1):
        draw.ellipse((x - 76, y - 76, x + 76, y + 76), fill=color, outline=(193, 151, 56), width=5)
        draw.text((x - 13, y - 28), str(index), font=_font(38, True), fill=DARK)
        font = _fit(draw, region, 290, 44, 32)
        box = draw.textbbox((0, 0), region, font=font)
        draw.text((x - (box[2] - box[0]) / 2, y + 105), region, font=font, fill=DARK)
        draw.text((x - 95, y + 165), detail[0], font=_font(30, True), fill=(151, 102, 24))
        draw.text((x - 105, y + 210), detail[1], font=_font(27, False), fill=MUTED)
    draw.text((82, 1510), "区域关系示意｜不代表精确距离", font=_font(28, False), fill=(122, 128, 140))
    image.save(path, quality=95)


def _page_compare(path: Path, frame: Path | None):
    image = _base()
    draw = ImageDraw.Draw(image)
    _label(draw, 4, "用途")
    _paste_round(image, frame, (76, 175, 1166, 600), 38)
    draw.text((78, 655), "投资 ≠ 自住", font=_font(82, True), fill=DARK)
    draw.text((82, 760), "看的根本不是同一套逻辑", font=_font(42, False), fill=MUTED)
    left, right = (76, 875, 600, 1490), (642, 875, 1166, 1490)
    draw.rounded_rectangle(left, radius=38, fill=(248, 242, 226), outline=(226, 198, 132), width=3)
    draw.rounded_rectangle(right, radius=38, fill=(238, 245, 252), outline=(188, 208, 230), width=3)
    draw.text((130, 935), "投资", font=_font(62, True), fill=(149, 101, 22))
    draw.text((696, 935), "自住", font=_font(62, True), fill=(42, 93, 150))
    for index, item in enumerate(["租客是谁", "租金稳定吗", "转手容易吗"], 1):
        y = 1065 + (index - 1) * 125
        draw.text((132, y), f"0{index}", font=_font(32, True), fill=(181, 129, 36))
        draw.text((210, y - 7), item, font=_font(42, True), fill=DARK)
    for index, item in enumerate(["通勤多久", "生活方便吗", "社区适合吗"], 1):
        y = 1065 + (index - 1) * 125
        draw.text((698, y), f"0{index}", font=_font(32, True), fill=(60, 113, 172))
        draw.text((776, y - 7), item, font=_font(42, True), fill=DARK)
    image.save(path, quality=95)


def _page_budget(path: Path, frames: List[Path | None], budgets: List[str], regions: List[str]):
    image = _base()
    draw = ImageDraw.Draw(image)
    _label(draw, 5, "预算")
    draw.text((78, 190), "预算决定你该看哪里", font=_font(76, True), fill=DARK)
    draw.text((82, 290), "不要拿同一个标准看所有房子", font=_font(40, False), fill=MUTED)
    tops = [400, 770, 1140]
    notes = ["先保总价", "平衡通勤配套", "看稀缺与流动性"]
    for index, top in enumerate(tops):
        bottom = top + 310
        draw.rounded_rectangle((76, top, 1166, bottom), radius=36, fill=(249, 247, 241), outline=(231, 220, 198), width=2)
        _paste_round(image, frames[index] if index < len(frames) else None, (92, top + 16, 490, bottom - 16), 28)
        draw.text((535, top + 40), f"第{index + 1}档", font=_font(30, True), fill=(154, 105, 24))
        font = _fit(draw, budgets[index], 560, 58, 40)
        draw.text((535, top + 94), budgets[index], font=font, fill=DARK)
        draw.text((535, top + 180), f"优先看：{regions[index]}", font=_font(40, True), fill=(42, 93, 150))
        draw.text((535, top + 240), notes[index], font=_font(32, False), fill=MUTED)
    image.save(path, quality=95)


def _page_pitfalls(path: Path, frame: Path | None):
    image = _crop(frame, W, H).convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 105))
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((76, 82, 370, 148), radius=24, fill=ACCENT + (245,))
    draw.text((105, 95), "06  买房避坑", font=_font(31, True), fill=(25, 31, 42, 255))
    draw.text((76, 230), "三个坑别踩", font=_font(92, True), fill=(255, 255, 255, 255))
    draw.text((82, 350), "看起来便宜，不等于真的适合", font=_font(42, False), fill=(244, 209, 123, 255))
    items = [("01", "只看总价", "不看真实出租需求"), ("02", "只看新盘", "不看生活和通勤"), ("03", "只看宣传", "不看后期转手")]
    y = 565
    for number, title, detail in items:
        draw.rounded_rectangle((76, y, 1166, y + 245), radius=38, fill=(13, 20, 31, 200), outline=(255, 255, 255, 80), width=2)
        draw.text((120, y + 58), number, font=_font(48, True), fill=ACCENT + (255,))
        draw.text((250, y + 42), title, font=_font(58, True), fill=(255, 255, 255, 255))
        draw.text((250, y + 126), detail, font=_font(38, False), fill=(223, 228, 236, 255))
        y += 285
    image.convert("RGB").save(path, quality=95)


def _page_cta(path: Path, frame: Path | None, cta: str):
    image = _base()
    draw = ImageDraw.Draw(image)
    _label(draw, 7, "收藏")
    _paste_round(image, frame, (76, 175, 1166, 720), 38)
    draw.text((78, 785), "不知道选哪里？", font=_font(76, True), fill=DARK)
    draw.text((82, 885), "先把这 3 个信息写下来", font=_font(42, False), fill=MUTED)
    items = [("01", "预算范围"), ("02", "自住还是投资"), ("03", "通勤或目标租客")]
    y = 990
    for number, item in items:
        draw.rounded_rectangle((78, y, 1164, y + 125), radius=28, fill=(248, 244, 234))
        draw.text((118, y + 34), number, font=_font(34, True), fill=(159, 108, 23))
        draw.text((230, y + 25), item, font=_font(48, True), fill=DARK)
        y += 145
    final = cta.strip() or "评论区告诉我预算和用途，我按你的需求拆解区域"
    draw.rounded_rectangle((78, 1430, 1164, 1565), radius=32, fill=(29, 128, 82))
    font = _fit(draw, final, 980, 38, 28)
    box = draw.textbbox((0, 0), final, font=font)
    draw.text(((W - (box[2] - box[0])) / 2, 1472), final, font=font, fill=(255, 255, 255))
    image.save(path, quality=95)


def generate_visual_story(
    payload: Dict[str, Any],
    job: Dict[str, Any],
    video: Path | None,
    graphic_root: Path,
    public_base: str,
    zip_func: Callable[[Path, List[Dict[str, Any]]], str],
) -> Dict[str, Any]:
    job_id = str(payload.get("job_id") or "").strip()
    title = str(payload.get("title") or "").strip()
    cta = str(payload.get("cta") or "").strip()
    keywords = payload.get("keywords") or []
    script_text = str(payload.get("script_text") or "").strip()
    if not script_text:
        values: List[str] = []
        for key in ["script_text", "script", "tts_script", "original_script", "voiceover_text", "narration"]:
            value = job.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
        script_text = "\n".join(values)

    source = " ".join([title, script_text, " ".join(str(item) for item in keywords)])
    location = _location(source)
    regions = _regions(source)
    budgets = _budgets(source)

    package_id = f"xhs_visual_v4_{int(time.time())}_{random.randint(1000, 9999)}"
    package_dir = graphic_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    frames = _frames(video, package_dir)

    page_defs = [
        ("xhs_01_hook.jpg", "强钩子封面", "全屏实景 + 预算钩子", lambda p: _page_hook(p, frames[0], location, budgets)),
        ("xhs_02_first_step.jpg", "第一步判断", "实景 + 大结论卡", lambda p: _page_first_step(p, frames[1])),
        ("xhs_03_region_map.jpg", "区域关系示意", "实景 + 区域关系图", lambda p: _page_regions(p, frames[2], regions)),
        ("xhs_04_invest_vs_live.jpg", "投资与自住对比", "实景 + 双栏对比卡", lambda p: _page_compare(p, frames[3])),
        ("xhs_05_budget_tiers.jpg", "预算分档", "三帧实景 + 预算区域卡", lambda p: _page_budget(p, [frames[2], frames[4], frames[5]], budgets, regions)),
        ("xhs_06_pitfalls.jpg", "三个避坑点", "全屏实景 + 高对比避坑卡", lambda p: _page_pitfalls(p, frames[5])),
        ("xhs_07_save_and_comment.jpg", "收藏清单与CTA", "实景 + 收藏清单 + 引流", lambda p: _page_cta(p, frames[6], cta)),
    ]

    images: List[Dict[str, Any]] = []
    for page, (filename, page_title, role, drawer) in enumerate(page_defs, 1):
        output = package_dir / filename
        drawer(output)
        images.append({
            "url": f"{public_base}/{package_id}/{filename}",
            "path": str(output),
            "title": page_title,
            "role": f"第{page}页 · {role}",
            "page": page,
            "visual_type": role,
            "width": W,
            "height": H,
        })

    return {
        "ok": True,
        "mode": "xiaohongshu",
        "style": "v4_xhs_visual_story_mixed_media",
        "package_id": package_id,
        "job_id": job_id,
        "title": title,
        "page_count": len(images),
        "location": location,
        "regions": regions,
        "budget_labels": budgets,
        "images": images,
        "visual_rules": {
            "photo_pages": [1, 2, 3, 4, 5, 6, 7],
            "full_photo_pages": [1, 6],
            "diagram_pages": [3, 4, 5],
            "max_pure_text_pages": 0,
            "one_conclusion_per_page": True,
            "fal_called": False,
        },
        "publish_title": f"三档预算，在{location}分别买哪里？",
        "publish_description": f"{location}买房别只看价格。预算、用途和目标租客不同，区域选择逻辑完全不同。",
        "hashtags": [f"{location}买房", "海外置业", "房产投资", "小红书房产", "买房避坑"],
        "download_zip_url": zip_func(package_dir, images),
        "warnings": ["区域关系页为逻辑示意，不代表精确地理距离"],
    }
