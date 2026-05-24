from __future__ import annotations

import subprocess
import textwrap
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from app.config import Settings

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.webm', '.mkv'}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc' if bold else '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc' if bold else '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        'C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/simhei.ttf',
    ]
    for p in candidates:
        try:
            if p and Path(p).exists():
                return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap_zh(text: str, width: int, max_lines: int = 3) -> list[str]:
    text = (text or '').strip().replace('\n', ' ')
    if not text:
        return []
    lines = textwrap.wrap(text, width=width, break_long_words=True, replace_whitespace=False)
    return lines[:max_lines]


def _center_crop(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    src_w, src_h = img.size
    scale = max(target_w / max(1, src_w), target_h / max(1, src_h))
    resized = img.resize((int(src_w * scale), int(src_h * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _extract_video_frame(settings: Settings, video_path: Path) -> Optional[Path]:
    if not video_path.exists():
        return None
    out = settings.tmp_dir / f'cover_frame_{uuid.uuid4().hex}.jpg'
    cmd = [
        'ffmpeg', '-y', '-ss', '1.2', '-i', str(video_path),
        '-frames:v', '1', '-q:v', '2', str(out)
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if proc.returncode == 0 and out.exists() and out.stat().st_size > 1024:
        return out
    return None


def _load_background(settings: Settings, source_path: Optional[Path]) -> Image.Image:
    if source_path and source_path.exists():
        src = source_path
        if src.suffix.lower() in VIDEO_EXTS:
            frame = _extract_video_frame(settings, src)
            if frame:
                src = frame
        if src.suffix.lower() in IMAGE_EXTS and src.exists():
            try:
                img = Image.open(src).convert('RGB')
                return _center_crop(img, (1080, 1920))
            except Exception:
                pass

    # Fallback: clean gradient background, not PPT/card style.
    img = Image.new('RGB', (1080, 1920), (16, 24, 39))
    draw = ImageDraw.Draw(img)
    for y in range(1920):
        t = y / 1920
        r = int(16 + 15 * t)
        g = int(24 + 42 * t)
        b = int(39 + 90 * t)
        draw.line([(0, y), (1080, y)], fill=(r, g, b))
    return img


def _rounded_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont) -> None:
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.rounded_rectangle([x, y, x + w + 44, y + h + 26], radius=28, fill=(255, 255, 255, 230))
    draw.text((x + 22, y + 11), text, fill=(15, 23, 42), font=font)


def create_cover(
    settings: Settings,
    title: str,
    hook: str = '',
    subtitle: str = '',
    brand: str = '',
    source_path: Optional[Path] = None,
    template: str = 'douyin',
) -> tuple[Path, str]:
    """Create a Douyin-style cover: real frame/background + big title.

    The old card/phone-shell cover looked like a PPT. This version follows the
    short-video convention: one strong image, huge 1-2 line title, tiny hook and
    account/industry label. Source can be an uploaded image/video or an AI image.
    """
    output = settings.outputs_dir / f'cover_{uuid.uuid4().hex}.png'
    img = _load_background(settings, source_path).convert('RGBA')

    # Slight blur/dim creates contrast while keeping real material visible.
    bg_blur = img.filter(ImageFilter.GaussianBlur(radius=2.2))
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, 0, 1080, 1920], fill=(0, 0, 0, 88))
    od.rectangle([0, 0, 1080, 580], fill=(0, 0, 0, 92))
    od.rectangle([0, 1260, 1080, 1920], fill=(0, 0, 0, 128))
    img = Image.alpha_composite(bg_blur, overlay)
    draw = ImageDraw.Draw(img)

    title = (title or '短视频标题').strip()[:48]
    hook = (hook or '').strip()[:80]
    brand = (brand or 'AI Growth Studio').strip()[:24]

    title_font = _font(96, bold=True)
    title_font_small = _font(82, bold=True)
    hook_font = _font(40, bold=True)
    meta_font = _font(32, bold=True)
    small_font = _font(28)

    _rounded_label(draw, (64, 90), brand, small_font)

    lines = _wrap_zh(title, 9, max_lines=3)
    y = 230
    # If title is long, reduce size to keep it in top safe area.
    font_for_title = title_font if sum(len(x) for x in lines) <= 20 else title_font_small
    for line in lines:
        # Text shadow/stroke for Douyin-like readability.
        draw.text((64, y), line, fill=(255, 255, 255), font=font_for_title, stroke_width=5, stroke_fill=(0, 0, 0, 185))
        y += 112 if font_for_title is title_font else 98

    if hook:
        hook_lines = _wrap_zh(hook, 15, max_lines=2)
        hook_y = 1450
        draw.rounded_rectangle([54, hook_y - 28, 1026, hook_y + 188], radius=34, fill=(0, 0, 0, 150))
        for line in hook_lines:
            draw.text((82, hook_y), line, fill=(255, 238, 88), font=hook_font, stroke_width=3, stroke_fill=(0, 0, 0, 160))
            hook_y += 58

    if subtitle:
        draw.text((82, 1720), _wrap_zh(subtitle, 20, max_lines=1)[0] if _wrap_zh(subtitle, 20, max_lines=1) else '', fill=(226, 232, 240), font=meta_font, stroke_width=2, stroke_fill=(0, 0, 0, 120))

    # Safe border gives a finished commercial-poster look.
    draw.rounded_rectangle([36, 36, 1044, 1884], radius=54, outline=(255, 255, 255, 170), width=5)
    img.convert('RGB').save(output, 'PNG', optimize=True)
    prompt = f'抖音 9:16 封面：素材截图/真实背景 + 大标题「{title}」+ 钩子「{hook}」，不使用手机壳卡片。'
    return output, prompt
