"""旅行规划 Agent 的工具边界和执行循环。"""
import json
from types import SimpleNamespace

import pytest

from app.services import agent_service as agent


def test_budget_is_deterministic_and_enforces_days():
    args = agent.BudgetArgs(days=2, lodging_per_night=300, food_per_day=100,
                            local_transport_per_day=50, tickets_total=200,
                            intercity_transport_total=400)
    result = agent._budget(args, 2, 1200)
    assert result["total"] == 1200
    assert result["within_budget"] is True
    with pytest.raises(ValueError, match="天数"):
        agent._budget(args, 3, 1200)


def test_search_rejects_other_city(monkeypatch):
    monkeypatch.setattr(agent, "retrieve", lambda *a, **kw: pytest.fail("不应检索其他城市"))
    with pytest.raises(ValueError, match="城市"):
        agent._search("attractions", agent.SearchArgs(query="景点", city="成都"), "杭州")


def test_search_unknown_city_uses_web_with_url(monkeypatch):
    monkeypatch.setattr(agent, "retrieve", lambda *a, **kw: [])
    monkeypatch.setattr(agent.web_search, "search", lambda query, max_results: [
        {"title": "上海旅游攻略", "url": "https://example.org/shanghai", "content": "上海有外滩等景点。"}
    ])
    result = agent._search("attractions", agent.SearchArgs(query="推荐景点", city="上海"), "上海")
    assert result["hits"][0]["source_type"] == "web"
    assert result["hits"][0]["source_url"] == "https://example.org/shanghai"


def test_search_unknown_city_without_web_source_returns_empty(monkeypatch):
    monkeypatch.setattr(agent, "retrieve", lambda *a, **kw: [])
    monkeypatch.setattr(agent.web_search, "search", lambda *a, **kw: [])
    assert agent._search("attractions", agent.SearchArgs(query="景点", city="上海"), "上海")["hits"] == []


def test_agent_calls_tools_and_records_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "TRACE_DIR", tmp_path)
    monkeypatch.setattr(agent.settings, "amap_web_key", "")
    monkeypatch.setattr(agent, "get_vector_store", lambda: SimpleNamespace(has_region=lambda city: True))
    monkeypatch.setattr(agent, "retrieve", lambda *a, **kw: [{
        "id": "chunk-1", "source_file": "杭州景点.md", "heading_path": "西湖",
        "score": 0.9, "content": "西湖适合游览。",
    }])

    def call(call_id, name, arguments):
        return SimpleNamespace(id=call_id, function=SimpleNamespace(
            name=name, arguments=json.dumps(arguments, ensure_ascii=False)))

    tool_response = SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(
        content=None, tool_calls=[
            call("a", "search_attractions", {"query": "杭州西湖", "city": "杭州"}),
            call("b", "calculate_budget", {"days": 1, "lodging_per_night": 0,
                "food_per_day": 100, "local_transport_per_day": 50,
                "tickets_total": 0, "intercity_transport_total": 0}),
        ]))])
    final_response = SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps({"city": "杭州", "summary": "游览西湖", "days": [
            {"day": 1, "morning": "西湖", "afternoon": "湖边", "evening": "晚餐", "estimated_cost": 150,
             "places": [{"name": "西湖风景名胜区", "period": "morning", "visit_minutes": 120}]}],
            "budget_total": 150, "budget_note": "估算", "reminders": ["确认开放时间"],
            "cited_sources": [1]}, ensure_ascii=False), tool_calls=None))])
    responses = iter([tool_response, final_response])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: next(responses))))
    monkeypatch.setattr(agent, "_get_client", lambda: client)

    result = agent.plan_trip(agent.PlanRequest(city="杭州", days=1, budget=500))
    assert [step["tool"] for step in result["steps"]] == ["search_attractions", "calculate_budget", "check_itinerary"]
    assert result["plan"]["days"][0]["morning"] == "西湖"
    assert result["sources"][0]["category"] == "attractions"
    assert agent.get_trace(result["run_id"])["status"] == "success"
    assert result["map_check"]["status"] == "unavailable"


def test_agent_rejects_unfounded_citation(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "TRACE_DIR", tmp_path)
    monkeypatch.setattr(agent, "get_vector_store", lambda: SimpleNamespace(has_region=lambda city: True))
    monkeypatch.setattr(agent, "_get_client", lambda: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(
            usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content="{}", tool_calls=None))])))))
    with pytest.raises(agent.AgentRunError, match="必要"):
        agent.plan_trip(agent.PlanRequest(city="杭州", days=1, budget=500))
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_map_warning_triggers_one_plan_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "TRACE_DIR", tmp_path)
    monkeypatch.setattr(agent, "get_vector_store", lambda: SimpleNamespace(has_region=lambda city: True))
    monkeypatch.setattr(agent, "retrieve", lambda *a, **kw: [{"id": "one", "source_file": "攻略.md",
                                                          "heading_path": "景点", "score": 0.9, "content": "景点资料"}])
    checked = iter([
        {"status": "warning", "message": "路段太长", "issues": ["第1天甲→乙约120分钟，建议调整顺序或拆到不同天。"], "days": []},
        {"status": "checked", "message": "地图核验完成", "issues": [], "days": []},
    ])
    monkeypatch.setattr(agent, "check_itinerary", lambda city, days: next(checked))
    calls = [SimpleNamespace(id="s", function=SimpleNamespace(name="search_attractions",
               arguments=json.dumps({"query": "景点", "city": "杭州"}, ensure_ascii=False))),
             SimpleNamespace(id="b", function=SimpleNamespace(name="calculate_budget",
               arguments=json.dumps({"days": 1, "lodging_per_night": 0, "food_per_day": 100,
                                     "local_transport_per_day": 0, "tickets_total": 0,
                                     "intercity_transport_total": 0})))]
    base = {"city": "杭州", "summary": "游览", "days": [{"day": 1, "morning": "甲", "afternoon": "乙",
            "evening": "晚餐", "estimated_cost": 100,
            "places": [{"name": "景点甲", "period": "morning", "visit_minutes": 90}]}],
            "budget_total": 100, "budget_note": "估算", "reminders": [], "cited_sources": [1]}
    revised = json.loads(json.dumps(base, ensure_ascii=False))
    revised["days"][0]["places"][0]["name"] = "景点乙"
    responses = iter([
        SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=calls))]),
        SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(base, ensure_ascii=False), tool_calls=None))]),
        SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(revised, ensure_ascii=False), tool_calls=None))]),
    ])
    monkeypatch.setattr(agent, "_get_client", lambda: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: next(responses)))))
    result = agent.plan_trip(agent.PlanRequest(city="杭州", days=1, budget=200))
    assert result["plan"]["days"][0]["places"][0]["name"] == "景点乙"
    assert [step["tool"] for step in result["steps"]].count("check_itinerary") == 2


def test_unknown_city_without_online_key_fails_before_model(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "TRACE_DIR", tmp_path)
    monkeypatch.setattr(agent.settings, "tavily_api_key", "")
    monkeypatch.setattr(agent, "get_vector_store", lambda: SimpleNamespace(has_region=lambda city: False))
    monkeypatch.setattr(agent, "_get_client", lambda: pytest.fail("缺少资料时不应调用模型"))
    with pytest.raises(agent.AgentRunError, match="暂无可用资料"):
        agent.plan_trip(agent.PlanRequest(city="上海", days=2, budget=1500))
