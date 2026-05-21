from __future__ import annotations

import textwrap
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import Settings


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/simhei.ttf',
    ]
    for p in candidates:
        try:
            if Path(p).exists():
                return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap_zh(text: str, width: int) -> str:
    text = (text or '').strip()
    if not text:
        return ''
    return '\n'.join(textwrap.wrap(text, width=width, break_long_words=True, replace_whitespace=False))


def create_cover(settings: Settings, title: str, hook: str = '', subtitle: str = '', brand: str = '') -> tuple[Path, str]:
    output = settings.outputs_dir / f'cover_{uuid.uuid4().hex}.png'
    img = Image.new('RGB', (1080, 1920), (15, 23, 42))
    draw = ImageDraw.Draw(img)

    # 背景块
    draw.rounded_rectangle([70, 120, 1010, 1780], radius=48, fill=(248, 250, 252))
    draw.rounded_rectangle([90, 140, 990, 520], radius=42, fill=(37, 99, 235))
    draw.rounded_rectangle([90, 1450, 990, 1720], radius=42, fill=(239, 246, 255))

    title_font = _font(82)
    hook_font = _font(48)
    sub_font = _font(40)
    brand_font = _font(34)

    draw.text((130, 210), _wrap_zh(title, 10), fill=(255, 255, 255), font=title_font, spacing=18)
    if hook:
        draw.text((130, 640), _wrap_zh(hook, 14), fill=(15, 23, 42), font=hook_font, spacing=12)
    if subtitle:
        draw.text((130, 1120), _wrap_zh(subtitle, 18), fill=(51, 65, 85), font=sub_font, spacing=10)
    draw.text((130, 1525), brand or 'AI 短视频自动化', fill=(37, 99, 235), font=brand_font)
    draw.text((130, 1610), '标题 · 钩子 · 配音 · 剪辑 · 发布包', fill=(71, 85, 105), font=brand_font)

    img.save(output, 'PNG')
    prompt = f'竖版 9:16 商业短视频封面，主标题：{title}；钩子：{hook}；风格：专业、强对比、适合抖音信息流。'
    return output, prompt
