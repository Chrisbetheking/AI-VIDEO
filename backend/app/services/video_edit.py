from __future__ import annotations

import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.config import Settings
from app.services.video import create_srt, ffmpeg_subtitle_path


@dataclass
class VideoEditResult:
    output_path: Optional[Path]
    actions: List[str]
    warnings: List[str]


def run_cmd(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def probe_has_audio(path: Path) -> bool:
    proc = run_cmd([
        'ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries',
        'stream=codec_type', '-of', 'csv=p=0', str(path)
    ], timeout=30)
    return proc.returncode == 0 and 'audio' in proc.stdout


def parse_trim_start(instruction: str) -> float:
    text = instruction or ''
    patterns = [
        r'(?:去掉|删掉|裁掉|剪掉|删除|去除).{0,8}(?:开头|前面|前)(\d+(?:\.\d+)?)(秒|s)',
        r'(?:从|保留从)(\d+(?:\.\d+)?)(秒|s).{0,12}(?:开始|之后)',
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.I)
        if m:
            return max(0.0, min(30.0, float(m.group(1))))
    return 0.0


def parse_speed(instruction: str) -> float:
    text = instruction or ''
    m = re.search(r'(\d+(?:\.\d+)?)\s*倍', text)
    if m:
        return max(0.5, min(2.0, float(m.group(1))))
    if any(x in text for x in ['加速', '快一点', '节奏快', '更快', '提速']):
        return 1.12
    if any(x in text for x in ['慢一点', '放慢', '慢下来', '节奏慢']):
        return 0.9
    return 1.0


def should_add_subtitles(instruction: str, script: str) -> bool:
    text = instruction or ''
    if any(x in text for x in ['字幕', '加字', '口播文字', '文案打上去', '烧字幕']):
        return bool(script.strip())
    return False


def _atempo_chain(speed: float) -> str:
    # ffmpeg atempo supports 0.5-2.0; our speed is already clamped there.
    return f'atempo={speed:.3f}'


def apply_video_edit(settings: Settings, source_video: Path, instruction: str, script: str = '') -> VideoEditResult:
    warnings: List[str] = []
    actions: List[str] = []
    if not source_video.exists():
        return VideoEditResult(None, [], ['没有找到要修改的视频文件。'])

    trim_start = parse_trim_start(instruction)
    speed = parse_speed(instruction)
    add_subtitles = should_add_subtitles(instruction, script)
    normalize_916 = any(x in instruction for x in ['9:16', '竖屏', '重新导出', '适配抖音', '抖音比例'])

    if trim_start > 0:
        actions.append(f'裁掉开头 {trim_start:g} 秒')
    if abs(speed - 1.0) > 0.01:
        actions.append(f'调整视频速度为 {speed:.2f} 倍')
    if add_subtitles:
        actions.append('重新烧录字幕')
    if normalize_916 or not actions:
        actions.append('按 9:16 竖屏标准重新导出')

    task_id = uuid.uuid4().hex
    output_path = settings.outputs_dir / f'edited_{task_id}.mp4'
    subtitle_path: Optional[Path] = None

    vf_parts: List[str] = []
    if abs(speed - 1.0) > 0.01:
        vf_parts.append(f'setpts=PTS/{speed:.3f}')
    vf_parts.append('scale=1080:1920:force_original_aspect_ratio=increase')
    vf_parts.append('crop=1080:1920')
    vf_parts.append('setsar=1')
    vf_parts.append('fps=30')
    vf_parts.append('format=yuv420p')

    if add_subtitles and script.strip():
        subtitle_path = settings.tmp_dir / f'edit_sub_{task_id}.srt'
        # 用源视频时长不易稳定获取；这里用 45 秒兜底，ffmpeg 会按视频裁切。
        create_srt(script, 45.0, subtitle_path)
        sub_path = ffmpeg_subtitle_path(subtitle_path)
        style = 'FontName=Noto Sans CJK SC,FontSize=17,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=180'
        vf_parts.append(f"subtitles='{sub_path}':force_style='{style}'")

    cmd = ['ffmpeg', '-y']
    if trim_start > 0:
        cmd += ['-ss', f'{trim_start:.2f}']
    cmd += ['-i', str(source_video), '-vf', ','.join(vf_parts)]

    has_audio = probe_has_audio(source_video)
    cmd += ['-map', '0:v:0']
    if has_audio:
        cmd += ['-map', '0:a:0?']
        if abs(speed - 1.0) > 0.01:
            cmd += ['-filter:a', _atempo_chain(speed)]
        cmd += ['-c:a', 'aac', '-b:a', '128k']
    else:
        cmd += ['-an']
        warnings.append('源视频没有检测到音轨，已导出无声音版本。')

    cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output_path)]
    proc = run_cmd(cmd)
    if subtitle_path:
        subtitle_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        return VideoEditResult(None, actions, [f"FFmpeg 修改失败：{proc.stderr[-1200:]}", 'CMD: ' + ' '.join(shlex.quote(c) for c in cmd)])
    return VideoEditResult(output_path, actions, warnings)
