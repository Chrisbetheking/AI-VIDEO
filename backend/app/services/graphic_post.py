from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.config import Settings


@dataclass
class GraphicSlide:
    path: Path
    title: str
    caption: str
    role: str


_FONT_CANDIDATES = [
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = _FONT_CANDIDATES if bold else [
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for path in candidates:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _size_for_platform(platform: str) -> tuple[int, int]:
    p = (platform or '').strip().lower()
    if p in {'douyin', '抖音', 'kuaishou', '快手'}:
        return 1080, 1920
    if p in {'wechat', '朋友圈', '视频号', 'shipinhao'}:
        return 1080, 1440
    return 1080, 1440


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int = 5) -> list[str]:
    clean = re.sub(r'\s+', ' ', (text or '').strip())
    if not clean:
        return []
    lines: list[str] = []
    current = ''
    for ch in clean:
        trial = current + ch
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current.strip())
            current = ch
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current.strip())
    if len(lines) == max_lines and len(''.join(lines)) < len(clean):
        lines[-1] = lines[-1].rstrip('，。,.；;：:') + '…'
    return lines


def _draw_multiline(draw: ImageDraw.ImageDraw, lines: Iterable[str], xy: tuple[int, int], font: ImageFont.ImageFont, fill: tuple[int, int, int], spacing: int = 16, stroke_width: int = 0, stroke_fill: tuple[int, int, int] | None = None) -> int:
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill, spacing=spacing, stroke_width=stroke_width, stroke_fill=stroke_fill)
        bbox = draw.textbbox((x, y), line, font=font, stroke_width=stroke_width)
        y = bbox[3] + spacing
    return y


def _split_points(script: str, selling_points: str = '', min_count: int = 5) -> list[str]:
    text = '\n'.join([script or '', selling_points or ''])
    parts = [p.strip(' ，。；;、\n\t') for p in re.split(r'[。！？!?；;\n]+', text) if p.strip()]
    points: list[str] = []
    for p in parts:
        p = re.sub(r'^[\d一二三四五六七八九十]+[、.．]\s*', '', p).strip()
        if 7 <= len(p) <= 58 and p not in points:
            points.append(p)
        elif len(p) > 58:
            for chunk in re.split(r'[，,、]+', p):
                chunk = chunk.strip()
                if 7 <= len(chunk) <= 58 and chunk not in points:
                    points.append(chunk)
        if len(points) >= 12:
            break
    defaults = ['先看清真实需求，再决定内容结构', '标题要解决用户正在担心的问题', '正文每一页只讲一个重点', '最后一页给出明确私信理由', '图片要像资料卡，不要像普通封面']
    for d in defaults:
        if len(points) >= min_count:
            break
        points.append(d)
    return points[:12]


def _safe_title(value: str, fallback: str = '引流图文') -> str:
    text = re.sub(r'\s+', ' ', (value or '').strip())
    return text[:32] if text else fallback


def _background_from_source(source_path: Path | None, size: tuple[int, int], idx: int) -> Image.Image:
    w, h = size
    if source_path and source_path.exists() and source_path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}:
        try:
            image = Image.open(source_path).convert('RGB')
            image = ImageOps.exif_transpose(image)
            image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))
            image = image.filter(ImageFilter.GaussianBlur(radius=1.8 if idx else 0.8))
            overlay = Image.new('RGBA', size, (0, 0, 0, 92 if idx else 72))
            image = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')
            return image
        except Exception:
            pass
    base = Image.new('RGB', size, (20, 28, 54))
    pix = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        for x in range(w):
            s = x / max(1, w - 1)
            r = int(22 + 58 * s + 24 * (1 - t))
            g = int(36 + 56 * (1 - s) + 18 * t)
            b = int(80 + 105 * t)
            pix[x, y] = (r, g, b)
    return base


def _rounded(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], radius: int, fill: tuple[int, int, int, int] | tuple[int, int, int], outline: tuple[int, int, int] | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _make_slide(settings: Settings, *, idx: int, total: int, title: str, hook: str, points: list[str], cta: str, platform: str, source_path: Path | None, style: str) -> GraphicSlide:
    size = _size_for_platform(platform)
    w, h = size
    img = _background_from_source(source_path, size, idx)
    draw = ImageDraw.Draw(img, 'RGBA')

    margin = 78
    brand_font = _font(34, bold=True)
    small_font = _font(30, bold=False)
    tag_font = _font(34, bold=True)
    title_font = _font(84 if w == 1080 else 78, bold=True)
    hook_font = _font(42, bold=True)
    point_font = _font(43, bold=True)
    body_font = _font(37, bold=False)
    cta_font = _font(44, bold=True)

    accent = (255, 215, 88)
    white = (255, 255, 255)
    dark = (15, 23, 42)
    panel = (255, 255, 255, 228)
    blue = (37, 99, 235)
    orange = (249, 115, 22)

    # 顶部栏目条
    _rounded(draw, (margin, margin, w - margin, margin + 78), 34, (255, 255, 255, 42), outline=(255, 255, 255, 88), width=2)
    draw.text((margin + 28, margin + 22), '图文引流 · 可直接发小红书/朋友圈/抖音图文', font=brand_font, fill=(255, 255, 255))
    count_text = f'{idx + 1}/{total}'
    cb = draw.textbbox((0, 0), count_text, font=tag_font)
    draw.text((w - margin - (cb[2] - cb[0]) - 34, margin + 20), count_text, font=tag_font, fill=accent)

    if idx == 0:
        y = int(h * 0.26)
        title_lines = _wrap_text(draw, title, title_font, w - margin * 2, max_lines=3)
        y = _draw_multiline(draw, title_lines, (margin, y), title_font, white, spacing=18, stroke_width=3, stroke_fill=(0, 0, 0))
        y += 30
        hook_lines = _wrap_text(draw, hook or '先收藏，再决定怎么做。', hook_font, w - margin * 2 - 56, max_lines=3)
        box_h = max(150, len(hook_lines) * 58 + 68)
        _rounded(draw, (margin, y, w - margin, y + box_h), 36, (255, 255, 255, 235))
        _draw_multiline(draw, hook_lines, (margin + 34, y + 34), hook_font, dark, spacing=12)
        footer = '适合：收藏 / 转发 / 私信咨询'
        draw.text((margin, h - margin - 72), footer, font=small_font, fill=(255, 255, 255, 230))
        return GraphicSlide(settings.outputs_dir / f'graphic_post_{uuid.uuid4().hex}_{idx + 1}.jpg', title, hook, '首图强钩子')

    if idx == total - 1:
        card_y = int(h * 0.24)
        _rounded(draw, (margin, card_y, w - margin, h - margin - 110), 42, panel)
        inner_x = margin + 54
        inner_y = card_y + 62
        draw.text((inner_x, inner_y), '最后给你一句实话', font=hook_font, fill=orange)
        inner_y += 82
        lines = _wrap_text(draw, cta or '想要完整清单，私信发你。', title_font, w - margin * 2 - 108, max_lines=4)
        inner_y = _draw_multiline(draw, lines, (inner_x, inner_y), title_font, dark, spacing=18)
        inner_y += 42
        tip = '评论 / 私信：领取清单｜预约咨询｜发你资料'
        _rounded(draw, (inner_x, inner_y, w - margin - 54, inner_y + 98), 32, blue)
        _draw_multiline(draw, _wrap_text(draw, tip, cta_font, w - margin * 2 - 150, 2), (inner_x + 30, inner_y + 24), cta_font, white, spacing=10)
        draw.text((margin, h - margin - 64), '图文引流包 · 系统自动生成', font=small_font, fill=(255, 255, 255, 220))
        return GraphicSlide(settings.outputs_dir / f'graphic_post_{uuid.uuid4().hex}_{idx + 1}.jpg', '引导私信', cta, '结尾转化')

    point_idx = idx - 1
    main = points[point_idx] if point_idx < len(points) else points[-1]
    card_y = int(h * 0.20)
    _rounded(draw, (margin, card_y, w - margin, h - margin - 104), 42, panel)
    inner_x = margin + 54
    inner_y = card_y + 58
    pill = f'第 {idx} 个重点'
    _rounded(draw, (inner_x, inner_y, inner_x + 250, inner_y + 70), 30, orange)
    draw.text((inner_x + 28, inner_y + 17), pill, font=tag_font, fill=white)
    inner_y += 112

    short_head = re.split(r'[，,。；;：:]', main)[0][:18]
    if len(short_head) < 5:
        short_head = '这一点很关键'
    _draw_multiline(draw, _wrap_text(draw, short_head, title_font, w - margin * 2 - 108, 2), (inner_x, inner_y), title_font, dark, spacing=16)
    inner_y += 210
    _draw_multiline(draw, _wrap_text(draw, main, point_font, w - margin * 2 - 108, 4), (inner_x, inner_y), point_font, dark, spacing=18)

    if point_idx + 1 < len(points):
        note = '下一页：' + points[point_idx + 1][:26]
    else:
        note = '下一页：给你行动建议'
    _rounded(draw, (inner_x, h - margin - 210, w - margin - 54, h - margin - 116), 26, (239, 246, 255, 255))
    draw.text((inner_x + 28, h - margin - 184), note, font=body_font, fill=blue)
    return GraphicSlide(settings.outputs_dir / f'graphic_post_{uuid.uuid4().hex}_{idx + 1}.jpg', short_head, main, '内容页')


def create_graphic_post(
    settings: Settings,
    *,
    title: str,
    hook: str,
    script: str,
    selling_points: str = '',
    cta: str = '',
    platform: str = 'xiaohongshu',
    slide_count: int = 5,
    source_path: Path | None = None,
    style: str = '',
) -> list[GraphicSlide]:
    slide_count = max(3, min(int(slide_count or 5), 8))
    safe_title = _safe_title(title)
    safe_hook = _safe_title(hook, '这几件事一定要先弄懂')
    points = _split_points(script, selling_points, min_count=slide_count)
    safe_cta = cta.strip() or '想要完整避坑清单，私信发你。'
    slides: list[GraphicSlide] = []
    for idx in range(slide_count):
        slide = _make_slide(settings, idx=idx, total=slide_count, title=safe_title, hook=safe_hook, points=points, cta=safe_cta, platform=platform, source_path=source_path, style=style)
        # _make_slide returns path before saving; draw the same image again would be wasteful. Rebuild logic inline by re-opening? Instead save the image from draw scope.
        # The actual image object is local in _make_slide; it writes below by storing the rendered bytes in a hidden attribute.
        slides.append(slide)
    # The helper above returns metadata but not images; regenerate and save in one pass to keep signatures simple.
    saved: list[GraphicSlide] = []
    for idx in range(slide_count):
        size = _size_for_platform(platform)
        img = _render_slide_image(settings, idx=idx, total=slide_count, title=safe_title, hook=safe_hook, points=points, cta=safe_cta, platform=platform, source_path=source_path, style=style)
        if idx == 0:
            role, caption = '首图强钩子', safe_hook
            stitle = safe_title
        elif idx == slide_count - 1:
            role, caption = '结尾转化', safe_cta
            stitle = '引导私信'
        else:
            role = '内容页'
            caption = points[idx - 1] if idx - 1 < len(points) else points[-1]
            stitle = re.split(r'[，,。；;：:]', caption)[0][:18] or '重点'
        path = settings.outputs_dir / f'graphic_post_{uuid.uuid4().hex}_{idx + 1}.jpg'
        img.save(path, 'JPEG', quality=94, optimize=True)
        saved.append(GraphicSlide(path=path, title=stitle, caption=caption, role=role))
    return saved


def _render_slide_image(settings: Settings, *, idx: int, total: int, title: str, hook: str, points: list[str], cta: str, platform: str, source_path: Path | None, style: str) -> Image.Image:
    # This is a copy of the visual drawing in _make_slide, but returns the rendered image.
    size = _size_for_platform(platform)
    w, h = size
    img = _background_from_source(source_path, size, idx)
    draw = ImageDraw.Draw(img, 'RGBA')
    margin = 78
    brand_font = _font(34, bold=True)
    small_font = _font(30, bold=False)
    tag_font = _font(34, bold=True)
    title_font = _font(84 if w == 1080 else 78, bold=True)
    hook_font = _font(42, bold=True)
    point_font = _font(43, bold=True)
    body_font = _font(37, bold=False)
    cta_font = _font(44, bold=True)
    accent = (255, 215, 88)
    white = (255, 255, 255)
    dark = (15, 23, 42)
    panel = (255, 255, 255, 228)
    blue = (37, 99, 235)
    orange = (249, 115, 22)

    _rounded(draw, (margin, margin, w - margin, margin + 78), 34, (255, 255, 255, 42), outline=(255, 255, 255, 88), width=2)
    draw.text((margin + 28, margin + 22), '图文引流 · 可直接发小红书/朋友圈/抖音图文', font=brand_font, fill=(255, 255, 255))
    count_text = f'{idx + 1}/{total}'
    cb = draw.textbbox((0, 0), count_text, font=tag_font)
    draw.text((w - margin - (cb[2] - cb[0]) - 34, margin + 20), count_text, font=tag_font, fill=accent)

    if idx == 0:
        y = int(h * 0.26)
        y = _draw_multiline(draw, _wrap_text(draw, title, title_font, w - margin * 2, max_lines=3), (margin, y), title_font, white, spacing=18, stroke_width=3, stroke_fill=(0, 0, 0))
        y += 30
        hook_lines = _wrap_text(draw, hook or '先收藏，再决定怎么做。', hook_font, w - margin * 2 - 56, max_lines=3)
        box_h = max(150, len(hook_lines) * 58 + 68)
        _rounded(draw, (margin, y, w - margin, y + box_h), 36, (255, 255, 255, 235))
        _draw_multiline(draw, hook_lines, (margin + 34, y + 34), hook_font, dark, spacing=12)
        draw.text((margin, h - margin - 72), '适合：收藏 / 转发 / 私信咨询', font=small_font, fill=(255, 255, 255, 230))
        return img

    if idx == total - 1:
        card_y = int(h * 0.24)
        _rounded(draw, (margin, card_y, w - margin, h - margin - 110), 42, panel)
        inner_x = margin + 54
        inner_y = card_y + 62
        draw.text((inner_x, inner_y), '最后给你一句实话', font=hook_font, fill=orange)
        inner_y += 82
        inner_y = _draw_multiline(draw, _wrap_text(draw, cta or '想要完整清单，私信发你。', title_font, w - margin * 2 - 108, max_lines=4), (inner_x, inner_y), title_font, dark, spacing=18)
        inner_y += 42
        tip = '评论 / 私信：领取清单｜预约咨询｜发你资料'
        _rounded(draw, (inner_x, inner_y, w - margin - 54, inner_y + 98), 32, blue)
        _draw_multiline(draw, _wrap_text(draw, tip, cta_font, w - margin * 2 - 150, 2), (inner_x + 30, inner_y + 24), cta_font, white, spacing=10)
        draw.text((margin, h - margin - 64), '图文引流包 · 系统自动生成', font=small_font, fill=(255, 255, 255, 220))
        return img

    point_idx = idx - 1
    main = points[point_idx] if point_idx < len(points) else points[-1]
    card_y = int(h * 0.20)
    _rounded(draw, (margin, card_y, w - margin, h - margin - 104), 42, panel)
    inner_x = margin + 54
    inner_y = card_y + 58
    _rounded(draw, (inner_x, inner_y, inner_x + 250, inner_y + 70), 30, orange)
    draw.text((inner_x + 28, inner_y + 17), f'第 {idx} 个重点', font=tag_font, fill=white)
    inner_y += 112
    short_head = re.split(r'[，,。；;：:]', main)[0][:18]
    if len(short_head) < 5:
        short_head = '这一点很关键'
    _draw_multiline(draw, _wrap_text(draw, short_head, title_font, w - margin * 2 - 108, 2), (inner_x, inner_y), title_font, dark, spacing=16)
    inner_y += 210
    _draw_multiline(draw, _wrap_text(draw, main, point_font, w - margin * 2 - 108, 4), (inner_x, inner_y), point_font, dark, spacing=18)
    if point_idx + 1 < len(points):
        note = '下一页：' + points[point_idx + 1][:26]
    else:
        note = '下一页：给你行动建议'
    _rounded(draw, (inner_x, h - margin - 210, w - margin - 54, h - margin - 116), 26, (239, 246, 255, 255))
    draw.text((inner_x + 28, h - margin - 184), note, font=body_font, fill=blue)
    return img
