"""智能行程的多轮状态、版本保护与失败回退。"""
from types import SimpleNamespace

import pytest

from app.services import planner_session_service as sessions
from app.services.agent_service import PlanRequest


def _result(request: PlanRequest, run_id: str, place: str) -> dict:
    return {"run_id": run_id, "plan": {"city": request.city, "summary": place,
            "days": [{"day": day, "morning": place, "afternoon": place,
                      "evening": place, "estimated_cost": 100,
                      "places": [{"name": place, "period": "morning", "visit_minutes": 90}]}
                     for day in range(1, request.days + 1)],
            "budget_total": min(100, request.budget), "budget_note": "估算",
            "reminders": [], "cited_sources": [1]}, "sources": [{"id": 1}],
            "source_mode": "local", "map_check": {"status": "checked", "issues": [], "days": []},
            "steps": [], "usage": {}, "elapsed_ms": 1}


def test_create_followup_and_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    seen_contexts = []

    def fake_plan(request, revision_context=None):
        seen_contexts.append(revision_context)
        return _result(request, f"run-{len(seen_contexts)}", "西湖" if not revision_context else "灵隐寺")

    monkeypatch.setattr(sessions, "plan_trip", fake_plan)
    monkeypatch.setattr(sessions, "_resolve_request", lambda old, message: ("revise", old.model_copy(update={"budget": 1200})))
    created = sessions.create_session(PlanRequest(city="杭州", days=2, budget=1500))
    revised = sessions.revise_session(created["session_id"], "预算降到1200，第二天少走路", 1)
    assert len(revised["versions"]) == 2
    assert revised["versions"][-1]["request"]["budget"] == 1200
    assert "预算：1500 → 1200" in revised["versions"][-1]["changes"]
    assert seen_contexts[1]["previous_plan"]["summary"] == "西湖"
    assert sessions.get_session(created["session_id"])["versions"][-1]["result"]["plan"]["summary"] == "灵隐寺"
    assert sessions.list_sessions()[0]["version"] == 2
    sessions.delete_session(created["session_id"])
    with pytest.raises(sessions.PlannerSessionNotFound):
        sessions.get_session(created["session_id"])


def test_failed_followup_preserves_previous_version(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(sessions, "plan_trip", lambda request, revision_context=None: _result(request, "first", "西湖") if revision_context is None else (_ for _ in ()).throw(RuntimeError("模型故障")))
    monkeypatch.setattr(sessions, "_resolve_request", lambda old, message: ("revise", old))
    created = sessions.create_session(PlanRequest(city="杭州", days=1, budget=500))
    with pytest.raises(RuntimeError, match="模型故障"):
        sessions.revise_session(created["session_id"], "换一个景点", 1)
    assert len(sessions.get_session(created["session_id"])["versions"]) == 1
    with pytest.raises(sessions.PlannerVersionConflict):
        sessions.revise_session(created["session_id"], "再换一次", 0)


def test_invalid_session_id_cannot_access_other_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    with pytest.raises(sessions.PlannerSessionNotFound):
        sessions.get_session("../secrets")


def test_followup_constraint_extraction_keeps_unspecified_fields(monkeypatch):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"revise","city":"杭州","days":2,"budget":1200,"interests":"自然风景，少走路"}'))])
    monkeypatch.setattr(sessions, "_get_client", lambda: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: response))))
    action, updated = sessions._resolve_request(PlanRequest(city="杭州", days=2, budget=1500,
                                                            interests="自然风景"), "预算降到1200，少走路")
    assert action == "revise"
    assert updated.city == "杭州" and updated.days == 2
    assert updated.budget == 1200 and "少走路" in updated.interests


def test_question_adds_answer_without_new_plan_version(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(sessions, "plan_trip", lambda request, revision_context=None: _result(request, "first", "西湖"))
    monkeypatch.setattr(sessions, "_resolve_request", lambda old, message: ("answer", old))
    monkeypatch.setattr(sessions, "_answer_question", lambda previous, question: "因为第一天景点距离较近。")
    created = sessions.create_session(PlanRequest(city="杭州", days=1, budget=500))
    updated = sessions.revise_session(created["session_id"], "为什么这样安排？", 1)
    assert len(updated["versions"]) == 1
    assert updated["questions"][0]["answer"] == "因为第一天景点距离较近。"
    assert sessions.get_session(created["session_id"])["questions"][0]["version"] == 1


def test_answer_intent_never_changes_plan_constraints(monkeypatch):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"answer","city":"成都","days":3,"budget":9999,"interests":"别的偏好"}'))])
    monkeypatch.setattr(sessions, "_get_client", lambda: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: response))))
    previous = PlanRequest(city="杭州", days=2, budget=1500, interests="自然风景")
    action, resolved = sessions._resolve_request(previous, "为什么这样安排？")
    assert action == "answer"
    assert resolved == previous
