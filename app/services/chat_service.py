"""问答服务：检索 → 生成 → 返回答案与引用（对应 TDD §5.8）。"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from app.config import settings
from app.rag import generator
from app.rag import web_search
from app.rag.retriever import retrieve
from app.services import session_service


def chat(query: str, session_id: str | None = None, top_k: int = 5) -> dict[str, Any]:
    """单轮/多轮问答（非流式）。"""
    rewrite = _maybe_rewrite(query, session_id)
    hits = _find_hits(rewrite, top_k)

    if not hits:
        answer_text, citations = "根据现有知识库无法回答。", []
    else:
        answer = generator.generate(query, hits)
        answer_text, citations = answer.text, answer.citations

    _record(session_id, query, answer_text, citations)
    return {"answer": answer_text, "citations": citations}


async def chat_stream(
    query: str, session_id: str | None = None, top_k: int = 5
) -> AsyncIterator[dict[str, Any]]:
    """流式问答：SSE 事件流，异常降级为非流式。"""
    try:
        rewrite = _maybe_rewrite(query, session_id)
        hits = _find_hits(rewrite, top_k)

        if not hits:
            answer_text = "根据现有知识库无法回答。"
            _record(session_id, query, answer_text, [])
            yield _sse("token", {"delta": answer_text})
            yield _sse("done", {"citations": []})
            return

        citations = generator.build_citations(hits)
        full_text = ""
        async for delta in generator.stream_generate(query, hits):
            full_text += delta
            yield _sse("token", {"delta": delta})

        if not full_text.strip():
            raise RuntimeError("模型返回了空的流式回答")

        _record(session_id, query, full_text, citations)
        yield _sse("done", {"citations": citations})
    except Exception as exc:  # noqa: BLE001
        # 已发送部分 token 时不重新检索或写入第二轮记录。
        try:
            if "hits" not in locals() or not hits:
                raise exc
            answer = generator.generate(query, hits)
            _record(session_id, query, answer.text, answer.citations)
            yield _sse("message", {"answer": answer.text})
            yield _sse("done", {"citations": answer.citations})
        except Exception:
            yield _sse("error", {"detail": "问答服务暂时不可用"})


def _find_hits(query: str, top_k: int) -> list[dict[str, Any]]:
    """优先使用知识库；无命中时以联网结果作为带 URL 的参考资料。"""
    destination = generator.extract_destination(query)
    hits = [
        hit for hit in retrieve(query, top_k=top_k, region=destination or None)
        if (hit.get("score") or 0) >= settings.retrieve_min_score
    ]
    if hits:
        return hits
    return [
        {
            "content": item["content"],
            "source_file": item["title"] or item["url"],
            "source_url": item["url"],
            "heading_path": "联网搜索",
        }
        for item in web_search.search(query, max_results=min(top_k, 3))
        if item.get("content") and item.get("url")
    ]


def _maybe_rewrite(query: str, session_id: str | None) -> str:
    """多轮场景下做查询改写。"""
    if not session_id:
        return query
    history = session_service.get_messages(session_id)
    if not history:
        return query
    return generator.rewrite_query(query, history)


def _record(
    session_id: str | None,
    query: str,
    answer: str,
    citations: list[dict[str, Any]],
) -> None:
    """记录一轮对话（用户 + 助手）。"""
    if not session_id:
        return
    session_service.add_message(session_id, "user", query)
    session_service.add_message(session_id, "assistant", answer, citations)


def _sse(event: str, data: dict[str, Any]) -> dict[str, Any]:
    """构造 SSE 事件。"""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}
