from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path
from typing import Iterable

from app.config import Settings


def create_publish_package(
    settings: Settings,
    title: str,
    description: str,
    tags: Iterable[str],
    video_path: Path | None,
    cover_path: Path | None,
) -> tuple[Path, list[str]]:
    package_path = settings.outputs_dir / f'publish_package_{uuid.uuid4().hex}.zip'
    metadata = {
        'title': title,
        'description': description,
        'tags': list(tags),
        'platform': ['抖音', '视频号'],
        'status': 'manual_publish_ready',
    }
    checklist = [
        '检查标题是否夸大宣传',
        '检查口播是否涉及违规承诺或敏感行业表述',
        '确认素材和配音均已授权',
        '确认封面文字清晰，无遮挡',
        '发布后记录播放、完播、点赞、评论、私信/线索数',
    ]
    with zipfile.ZipFile(package_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
        zf.writestr('publish_checklist.txt', '\n'.join(checklist))
        zf.writestr('title.txt', title)
        zf.writestr('description.txt', description)
        zf.writestr('tags.txt', '\n'.join(f'#{t.strip("# ")}' for t in tags if t.strip()))
        if video_path and video_path.exists():
            zf.write(video_path, arcname=f'video{video_path.suffix}')
        if cover_path and cover_path.exists():
            zf.write(cover_path, arcname=f'cover{cover_path.suffix}')
    return package_path, checklist
