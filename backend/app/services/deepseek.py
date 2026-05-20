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




def _candidate_models(primary: str) -> List[str]:
    """Return a conservative fallback list so demo does not fail because of model naming/account rollout."""
    models: List[str] = []
    for m in [primary, "deepseek-chat", "deepseek-v4-flash"]:
        m = (m or "").strip()
        if m and m not in models:
            models.append(m)
    return models


def _friendly_error(status_code: int, text: str, url: str, model: str) -> str:
    hint = ""
    if status_code == 401:
        hint = "请检查 DEEPSEEK_API_KEY 是否正确、是否复制了完整 key。"
    elif status_code == 402:
        hint = "DeepSeek 账户余额不足或未开通计费，请到平台充值/开通。"
    elif status_code == 404:
        hint = "请检查 DEEPSEEK_BASE_URL，应为 https://api.deepseek.com；不要手动加错路径。"
    elif status_code in (400, 422):
        hint = "可能是模型名或请求参数不兼容；系统已尝试备用模型。"
    elif status_code in (429, 503):
        hint = "DeepSeek 当前限流或服务繁忙，稍后重试。"
    return f"DeepSeek 返回错误 {status_code}，url={url}，model={model}。{hint} 原始返回：{text[:500]}"


async def test_deepseek(settings: Settings, api_key_override: Optional[str] = None) -> Dict[str, Any]:
    """Small diagnostic call used by /api/ai-test."""
    api_key = (api_key_override or settings.deepseek_api_key or "").strip()
    if not api_key:
        raise DeepSeekError("缺少 DeepSeek API Key。请在 backend/.env 设置 DEEPSEEK_API_KEY，或在页面临时输入。")
    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error = ""
    async with httpx.AsyncClient(timeout=30) as client:
        for model in _candidate_models(settings.deepseek_model):
            body: Dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": "只回复两个字：成功"}],
                "temperature": 0,
                "stream": False,
            }
            try:
                resp = await client.post(url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                raise DeepSeekError(f"DeepSeek 请求失败：{exc}。请确认本机/服务器能访问 https://api.deepseek.com") from exc
            if resp.status_code < 400:
                data = resp.json()
                return {
                    "ok": True,
                    "url": url,
                    "model": model,
                    "reply": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
                }
            last_error = _friendly_error(resp.status_code, resp.text, url, model)
    raise DeepSeekError(last_error)

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

    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error = ""
    async with httpx.AsyncClient(timeout=60) as client:
        for model in _candidate_models(settings.deepseek_model):
            body: Dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.75,
                "stream": False,
                "response_format": {"type": "json_object"},
            }
            try:
                resp = await client.post(url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                raise DeepSeekError(f"DeepSeek 请求失败：{exc}。请确认本机/服务器能访问 https://api.deepseek.com") from exc

            if resp.status_code >= 400:
                last_error = _friendly_error(resp.status_code, resp.text, url, model)
                continue

            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"]
                payload = _safe_json_loads(content)
                result = normalize_copy(payload, req.topic)
                # 把实际成功的模型写入引用，方便你排查现场环境。
                if model != settings.deepseek_model:
                    result.kb_refs.append(f"系统自动切换到可用模型：{model}")
                return result
            except Exception as exc:  # noqa: BLE001
                raise DeepSeekError(f"DeepSeek 输出解析失败：{data}") from exc

    raise DeepSeekError(last_error or "DeepSeek 调用失败，未获得有效响应。")
