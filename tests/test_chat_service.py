"""问答兜底与流式边界测试，不依赖真实数据库或外部 API。"""
import asyncio
import json

from app.rag.generator import Answer
from app.services import chat_service


def test_web_fallback_only_when_local_empty(monkeypatch):
    monkeypatch.setattr(chat_service.generator, "extract_destination", lambda query: "")
    monkeypatch.setattr(chat_service, "retrieve", lambda *args, **kwargs: [{"content": "无关片段", "score": 0.2}])
    monkeypatch.setattr(
        chat_service.web_search,
        "search",
        lambda *args, **kwargs: [{"title": "景区官网", "url": "https://example.org/a", "content": "开放时间 9 点"}],
    )
    hits = chat_service._find_hits("开放时间", 5)
    assert hits[0]["source_url"] == "https://example.org/a"
    assert hits[0]["content"] == "开放时间 9 点"


def test_relevant_local_hit_skips_web(monkeypatch):
    monkeypatch.setattr(chat_service.generator, "extract_destination", lambda query: "")
    local = {"content": "景点资料", "score": 0.8}
    monkeypatch.setattr(chat_service, "retrieve", lambda *args, **kwargs: [local])
    monkeypatch.setattr(chat_service.web_search, "search", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected web search")))
    assert chat_service._find_hits("景点", 5) == [local]


def test_other_city_does_not_use_local_documents(monkeypatch):
    seen = []
    monkeypatch.setattr(chat_service.generator, "extract_destination", lambda query: "上海")
    monkeypatch.setattr(chat_service, "retrieve", lambda query, top_k, region: seen.append(region) or [])
    monkeypatch.setattr(chat_service.web_search, "search", lambda *args, **kwargs: [
        {"title": "上海景点资料", "url": "https://example.org/shanghai", "content": "上海旅游资料"}
    ])
    hits = chat_service._find_hits("上海有什么景点", 5)
    assert seen == ["上海"]
    assert hits[0]["source_url"] == "https://example.org/shanghai"


def test_stream_no_hits_records_history(monkeypatch):
    recorded = []
    monkeypatch.setattr(chat_service, "_maybe_rewrite", lambda query, session_id: query)
    monkeypatch.setattr(chat_service, "_find_hits", lambda *args: [])
    monkeypatch.setattr(chat_service, "_record", lambda *args: recorded.append(args))

    async def collect():
        return [event async for event in chat_service.chat_stream("问题", "session-1")]

    events = asyncio.run(collect())
    assert recorded == [("session-1", "问题", "根据现有知识库无法回答。", [])]
    assert json.loads(events[-1]["data"])["citations"] == []


def test_stream_failure_falls_back_once(monkeypatch):
    recorded = []
    monkeypatch.setattr(chat_service, "_maybe_rewrite", lambda query, session_id: query)
    monkeypatch.setattr(chat_service, "_find_hits", lambda *args: [{"content": "资料", "source_file": "a.md"}])
    monkeypatch.setattr(chat_service, "_record", lambda *args: recorded.append(args))
    monkeypatch.setattr(chat_service.generator, "build_citations", lambda hits: [{"source_file": "a.md"}])
    monkeypatch.setattr(chat_service.generator, "generate", lambda *args: Answer("完整回答", [{"source_file": "a.md"}]))

    async def broken_stream(*args):
        yield "部分"
        raise RuntimeError("upstream failed")

    monkeypatch.setattr(chat_service.generator, "stream_generate", broken_stream)

    async def collect():
        return [event async for event in chat_service.chat_stream("问题", "session-1")]

    events = asyncio.run(collect())
    assert [event["event"] for event in events] == ["token", "message", "done"]
    assert json.loads(events[1]["data"])["answer"] == "完整回答"
    assert len(recorded) == 1
