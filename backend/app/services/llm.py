from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, Optional

import httpx

from app.config import Settings


class LLMError(RuntimeError):
    pass


def safe_json_loads(text: str) -> Dict[str, Any]:
    cleaned = (text or '').strip()
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```(?:json)?', '', cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r'```$', '', cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _clean_provider(value: str) -> str:
    return (value or '').strip().lower().replace('_', '-').replace(' ', '-')


def _provider_key(settings: Settings, provider: str, override: Optional[str] = None) -> str:
    provider = _clean_provider(provider)
    if override:
        return override.strip()
    if provider in {'qwen', 'dashscope', 'aliyun', 'bailian'}:
        return settings.dashscope_api_key.strip()
    if provider in {'gemini', 'google'}:
        return settings.gemini_api_key.strip()
    if provider in {'deepseek'}:
        return settings.deepseek_api_key.strip()
    return ''


def _candidate_providers(settings: Settings) -> list[str]:
    providers: list[str] = []
    for p in [settings.ai_provider, settings.ai_backup_provider, 'qwen', 'gemini', 'deepseek']:
        p = _clean_provider(p)
        if not p or p in providers:
            continue
        if _provider_key(settings, p):
            providers.append(p)
    return providers


def _provider_model(settings: Settings, provider: str, *, backup: bool = False) -> str:
    provider = _clean_provider(provider)
    if backup and settings.ai_backup_model.strip():
        return settings.ai_backup_model.strip()
    if settings.ai_text_model.strip() and provider not in {'gemini', 'google'}:
        return settings.ai_text_model.strip()
    if provider in {'qwen', 'dashscope', 'aliyun', 'bailian'}:
        return settings.ai_text_model.strip() or settings.qwen_model.strip() or 'qwen-max'
    if provider in {'gemini', 'google'}:
        return settings.ai_backup_model.strip() or settings.gemini_model.strip() or 'gemini-2.5-pro'
    if provider in {'deepseek'}:
        return settings.deepseek_model.strip() or 'deepseek-chat'
    return settings.ai_text_model.strip() or provider


def _openai_compatible_url(settings: Settings, provider: str) -> str:
    provider = _clean_provider(provider)
    if provider in {'qwen', 'dashscope', 'aliyun', 'bailian'}:
        return settings.dashscope_base_url.rstrip('/') + '/chat/completions'
    if provider == 'deepseek':
        return settings.deepseek_base_url.rstrip('/') + '/chat/completions'
    raise LLMError(f'未知 OpenAI 兼容模型供应商：{provider}')


async def _chat_openai_compatible(
    settings: Settings,
    provider: str,
    system: str,
    user: str,
    *,
    model: str,
    temperature: float,
    timeout: int,
    api_key_override: Optional[str] = None,
) -> Dict[str, Any]:
    api_key = _provider_key(settings, provider, api_key_override)
    if not api_key:
        raise LLMError(f'缺少 {provider} API Key。')
    url = _openai_compatible_url(settings, provider)
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    base_body: Dict[str, Any] = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
        'temperature': temperature,
        'stream': False,
    }
    # 有些模型支持 response_format，有些会 400；失败时自动去掉再试一次。
    bodies = [{**base_body, 'response_format': {'type': 'json_object'}}, base_body]
    last_error = ''
    async with httpx.AsyncClient(timeout=timeout) as client:
        for body in bodies:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                last_error = f'{provider} 返回 {resp.status_code}，model={model}，url={url}，原始返回：{resp.text[:500]}'
                continue
            data = resp.json()
            try:
                content = data['choices'][0]['message']['content']
                return safe_json_loads(content)
            except Exception as exc:
                raise LLMError(f'{provider} 输出 JSON 解析失败：{data}') from exc
    raise LLMError(last_error or f'{provider} 调用失败。')


async def _chat_gemini(
    settings: Settings,
    system: str,
    user: str,
    *,
    model: str,
    temperature: float,
    timeout: int,
    api_key_override: Optional[str] = None,
) -> Dict[str, Any]:
    api_key = _provider_key(settings, 'gemini', api_key_override)
    if not api_key:
        raise LLMError('缺少 GEMINI_API_KEY。')
    base = settings.gemini_base_url.rstrip('/')
    url = f'{base}/models/{model}:generateContent?key={api_key}'
    body = {
        'systemInstruction': {'parts': [{'text': system}]},
        'contents': [{'role': 'user', 'parts': [{'text': user}]}],
        'generationConfig': {
            'temperature': temperature,
            'responseMimeType': 'application/json',
        },
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body)
    if resp.status_code >= 400:
        raise LLMError(f'Gemini 返回 {resp.status_code}，model={model}。原始返回：{resp.text[:500]}')
    data = resp.json()
    try:
        parts = data['candidates'][0]['content']['parts']
        content = ''.join(str(p.get('text', '')) for p in parts)
        return safe_json_loads(content)
    except Exception as exc:
        raise LLMError(f'Gemini 输出 JSON 解析失败：{data}') from exc


async def chat_json(
    settings: Settings,
    system: str,
    user: str,
    *,
    temperature: float = 0.7,
    timeout: int = 90,
    api_key_override: Optional[str] = None,
) -> Dict[str, Any]:
    errors: list[str] = []
    providers = _candidate_providers(settings)
    if api_key_override:
        providers = [_clean_provider(settings.ai_provider or 'qwen')]
    if not providers:
        raise LLMError('缺少 AI 模型 Key。请至少设置 DASHSCOPE_API_KEY，或设置 GEMINI_API_KEY / DEEPSEEK_API_KEY。')

    for i, provider in enumerate(providers):
        is_backup = i > 0 and provider == _clean_provider(settings.ai_backup_provider)
        model = _provider_model(settings, provider, backup=is_backup)
        try:
            if provider in {'qwen', 'dashscope', 'aliyun', 'bailian', 'deepseek'}:
                return await _chat_openai_compatible(settings, provider, system, user, model=model, temperature=temperature, timeout=timeout, api_key_override=api_key_override)
            if provider in {'gemini', 'google'}:
                return await _chat_gemini(settings, system, user, model=model, temperature=temperature, timeout=timeout, api_key_override=api_key_override)
            errors.append(f'未知供应商：{provider}')
        except Exception as exc:
            errors.append(f'{provider}/{model}: {exc}')
            continue
    raise LLMError('；'.join(errors) or '所有 AI 模型调用失败。')


async def test_llm(settings: Settings, api_key_override: Optional[str] = None) -> Dict[str, Any]:
    provider = _clean_provider(settings.ai_provider or 'qwen')
    model = _provider_model(settings, provider)
    payload = await chat_json(
        settings,
        '你是接口连通性测试助手。必须输出严格 JSON。',
        '只输出 JSON：{"ok": true, "reply": "成功"}',
        temperature=0,
        timeout=45,
        api_key_override=api_key_override,
    )
    return {
        'ok': bool(payload.get('ok', True)),
        'provider': provider,
        'model': model,
        'reply': str(payload.get('reply') or payload)[:200],
        'backup_provider': settings.ai_backup_provider,
        'backup_model': settings.ai_backup_model,
    }
