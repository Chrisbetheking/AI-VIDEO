from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from app.config import Settings
from app.schemas import CopyRequest, GeneratedCopy


class DeepSeekError(RuntimeError):
    pass


def _safe_json_loads(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_copy(payload: Dict[str, Any], fallback_topic: str) -> GeneratedCopy:
    def as_str(name: str, default: str = "") -> str:
        value = payload.get(name, default)
        if isinstance(value, list):
            return "\n".join(str(x) for x in value)
        return str(value or default).strip()

    def as_list(name: str) -> List[str]:
        value = payload.get(name, [])
        if isinstance(value, str):
            return [x.strip(" #，,\n\t") for x in re.split(r"[,，#\n]", value) if x.strip(" #，,\n\t")]
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return []

    title = as_str("title", fallback_topic)[:80]
    hook = as_str("hook", title)
    script = as_str("script") or as_str("口播稿") or f"今天给大家分享：{fallback_topic}。"
    description = as_str("description", title)
    tags = as_list("tags")[:12] or ["短视频", "老板口播"]
    shots = as_list("shots")[:12] or ["老板正面口播", "产品/服务细节", "客户或案例画面", "结尾引导咨询"]
    kb_refs = as_list("kb_refs")[:8]
    return GeneratedCopy(
        title=title,
        hook=hook,
        script=script,
        description=description,
        tags=tags,
        shots=shots,
        kb_refs=kb_refs,
    )


async def generate_copy(settings: Settings, req: CopyRequest, knowledge_texts: List[str]) -> GeneratedCopy:
    api_key = (req.api_key or settings.deepseek_api_key or "").strip()
    if not api_key:
        raise DeepSeekError("缺少 DeepSeek API Key。请在 backend/.env 设置 DEEPSEEK_API_KEY，或在页面临时输入。")

    kb_block = "\n\n---\n\n".join(knowledge_texts + req.knowledge_examples[:10])
    system = (
        "你是中国短视频增长团队的资深编导和投流策划。"
        "你擅长老板口播、商业服务、门店/企业宣传、线索转化类短视频。"
        "必须输出严格 JSON，不要 Markdown，不要多余解释。"
    )
    user = f"""
请根据下面信息生成一条适合抖音/视频号的 9:16 短视频文案。

主题：{req.topic}
行业：{req.industry or '未填写'}
目标受众：{req.audience or '未填写'}
核心卖点：{req.selling_points or '未填写'}
风格：{req.style}
期望时长：{req.duration_seconds} 秒

参考文案知识库（模仿表达方式，不要照抄）：
{kb_block or '暂无'}

输出 JSON 字段：
{{
  "title": "不超过 30 字的标题",
  "hook": "前 3 秒钩子",
  "script": "完整口播稿，适合直接配音，中文自然口语化",
  "description": "发布简介/文案",
  "tags": ["话题标签，不带#"],
  "shots": ["镜头建议，按时间顺序"],
  "kb_refs": ["借鉴了哪些知识库风格点"]
}}
""".strip()

    url = settings.deepseek_base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body: Dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.75,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise DeepSeekError(f"DeepSeek 请求失败：{exc}") from exc

    if resp.status_code >= 400:
        raise DeepSeekError(f"DeepSeek 返回错误 {resp.status_code}：{resp.text[:500]}")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
        payload = _safe_json_loads(content)
    except Exception as exc:  # noqa: BLE001
        raise DeepSeekError(f"DeepSeek 输出解析失败：{data}") from exc

    return normalize_copy(payload, req.topic)
