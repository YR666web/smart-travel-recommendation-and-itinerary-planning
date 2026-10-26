"""LLM 生成 + 引用 + 查询改写（对应 TDD §5.7、§7.2）。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.config import settings
from app.rag.prompts import QUERY_REWRITE_PROMPT, SYSTEM_PROMPT, build_user_prompt

_client = None


@dataclass
class Answer:
    """问答结果。"""

    text: str
    citations: list[dict[str, Any]]


def _get_client():
    """延迟初始化 OpenAI 兼容客户端（DeepSeek）。"""
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
        )
    return _client


def generate(query: str, context_hits: list[dict[str, Any]]) -> Answer:
    """基于检索片段生成答案，返回答案与引用。"""
    context = _format_context(context_hits)
    prompt = build_user_prompt(query, context)

    client = _get_client()
    resp = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        stream=False,
    )
    text = (resp.choices[0].message.content or "").strip()

    return Answer(text=text, citations=build_citations(context_hits))


async def stream_generate(
    query: str, context_hits: list[dict[str, Any]]
) -> AsyncIterator[str]:
    """流式生成，逐 token yield（异步 httpx，避免与 torch/chromadb 原生库冲突）。"""
    import httpx

    context = _format_context(context_hits)
    prompt = build_user_prompt(query, context)
    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            url,
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if data.get("choices"):
                    delta = data["choices"][0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta


def rewrite_query(question: str, history: list[dict[str, Any]]) -> str:
    """多轮查询改写（结合历史补全指代）。"""
    history_text = _format_history(history)
    prompt = QUERY_REWRITE_PROMPT.format(history=history_text, question=question)

    client = _get_client()
    resp = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    rewritten = (resp.choices[0].message.content or "").strip()
    return rewritten or question


def extract_destination(question: str) -> str:
    """抽取用户明确提及的目的地；没有明确地点时返回空字符串。"""
    known = ("杭州", "成都", "厦门", "三亚", "云南", "张家界")
    for place in known:
        if place in question:
            return place
    try:
        resp = _get_client().chat.completions.create(
            model=settings.deepseek_model,
            messages=[{"role": "user", "content":
                       "从下面的旅游问题中找出用户明确想去的城市或地区。"
                       "只返回 JSON 对象，格式为 {\"destination\":\"上海\"}；"
                       "若没有明确地点则返回 {\"destination\":\"\"}。"
                       f"问题：{question[:300]}"}],
            temperature=0,
            max_tokens=80,
        )
        raw = (resp.choices[0].message.content or "").strip()
        value = json.loads(raw.removeprefix("```json").removesuffix("```").strip())
        destination = value.get("destination", "")
        return destination.strip()[:64] if isinstance(destination, str) else ""
    except Exception:
        return ""


def build_citations(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从命中片段提取引用来源。"""
    return [
        {
            "source_file": hit.get("source_file", ""),
            "heading_path": hit.get("heading_path", ""),
            "score": hit.get("score"),
            "url": hit.get("source_url"),
        }
        for hit in hits
    ]


def _format_context(hits: list[dict[str, Any]]) -> str:
    """格式化检索片段为参考资料文本。"""
    parts = [
        f"[{i}] 来源：{hit.get('source_file', '')}"
        f"{(' (' + hit['source_url'] + ')') if hit.get('source_url') else ''}\n"
        f"{hit.get('content', '')}"
        for i, hit in enumerate(hits, 1)
    ]
    return "\n\n".join(parts)


def _format_history(history: list[dict[str, Any]]) -> str:
    """格式化对话历史（最近 6 条）。"""
    parts = []
    for m in history[-6:]:
        role = "用户" if m.get("role") == "user" else "助手"
        parts.append(f"{role}：{m.get('content', '')}")
    return "\n".join(parts)
