"""智能行程多轮会话：原子保存已成功的版本，追问后重新校验完整行程。"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import settings
from app.rag.generator import _get_client
from app.services.agent_service import PlanRequest, plan_trip

SESSION_DIR = Path("storage/plan_sessions")
MAX_VERSIONS = 20
_LOCK = threading.RLock()


class PlannerSessionNotFound(LookupError):
    pass


class PlannerVersionConflict(RuntimeError):
    pass


class PlannerSessionLimit(RuntimeError):
    pass


def _path(session_id: str) -> Path:
    try:
        parsed = uuid.UUID(session_id)
    except (ValueError, AttributeError) as exc:
        raise PlannerSessionNotFound("行程会话不存在") from exc
    if str(parsed) != session_id:
        raise PlannerSessionNotFound("行程会话不存在")
    return SESSION_DIR / f"{session_id}.json"


def _write(session: dict[str, Any]) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    target = _path(session["session_id"])
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=SESSION_DIR,
                                         suffix=".tmp", delete=False) as handle:
            temp_path = handle.name
            json.dump(session, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, target)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def get_session(session_id: str) -> dict[str, Any]:
    path = _path(session_id)
    if not path.exists():
        raise PlannerSessionNotFound("行程会话不存在")
    return json.loads(path.read_text(encoding="utf-8"))


def delete_session(session_id: str) -> None:
    path = _path(session_id)
    with _LOCK:
        if not path.exists():
            raise PlannerSessionNotFound("行程会话不存在")
        path.unlink()


def list_sessions() -> list[dict[str, Any]]:
    if not SESSION_DIR.exists():
        return []
    sessions = []
    for path in SESSION_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            latest = data["versions"][-1]
            sessions.append({"session_id": data["session_id"], "title": data["title"],
                             "updated_at": data["updated_at"], "version": latest["version"],
                             "city": latest["request"]["city"]})
        except (ValueError, KeyError, IndexError):
            continue
    return sorted(sessions, key=lambda item: item["updated_at"], reverse=True)[:50]


def _resolve_request(previous: PlanRequest, instruction: str) -> tuple[str, PlanRequest]:
    """区分解释型提问和行程修改，并提取用户明确改变的约束。"""
    response = _get_client().chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content":
             "你负责识别智能行程追问。只输出 JSON 对象 action/city/days/budget/interests。"
             "action 只能是 answer 或 revise：询问原因、费用解释、已有行程细节且未要求改变安排时为 answer；"
             "要求新增、删除、替换、重新安排地点或修改预算、天数、偏好时为 revise，即使写成问句也是 revise。"
             "用户未明确修改的 city、days、budget 必须逐字/逐值保留；新增旅行偏好合并到 interests，"
             "明确取消的偏好才移除。answer 时保持全部字段不变。不要从上一版预算费用推测新的用户预算。"},
            {"role": "user", "content": json.dumps({"current": previous.model_dump(),
                                                    "followup": instruction}, ensure_ascii=False)},
        ], temperature=0,
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        payload = json.loads(raw.removeprefix("```json").removesuffix("```").strip())
        action = payload.get("action")
        if action not in ("answer", "revise"):
            raise ValueError("追问类型无效")
        request = PlanRequest.model_validate(payload)
        return action, (previous if action == "answer" else request)
    except (ValueError, ValidationError, TypeError) as exc:
        raise ValueError("无法可靠理解本轮修改，请具体说明城市、天数、预算或偏好") from exc


def _answer_question(previous: dict[str, Any], question: str) -> str:
    """只解释已保存行程；缺少实时事实时明确说明无法核实。"""
    context = {"request": previous["request"], "plan": previous["result"]["plan"],
               "map_check": previous["result"].get("map_check"),
               "sources": previous["result"].get("sources", [])}
    response = _get_client().chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": "你在回答用户对已生成旅行行程的追问。仅依据给定行程、预算、地图核验和来源元数据解释；"
             "不要编造新的景点、实时开放时间、票价或预订状态。资料不足时明确说无法核实，并建议核对官方信息。"
             "用简短自然语言回答，不使用 Markdown 标记，不输出 JSON，不修改行程。"},
            {"role": "user", "content": json.dumps({"context": context, "question": question}, ensure_ascii=False)},
        ], temperature=0.2,
    )
    answer = (response.choices[0].message.content or "").strip()
    if not answer:
        raise ValueError("本轮问题暂时无法回答，请重试")
    return answer.replace("**", "")[:3000]


def _changes(old: dict, new: dict, old_request: dict, new_request: dict) -> list[str]:
    changes = []
    for key, label in (("city", "目的地"), ("days", "天数"), ("budget", "预算"), ("interests", "偏好")):
        if old_request[key] != new_request[key]:
            changes.append("偏好已调整" if key == "interests" else f"{label}：{old_request[key]} → {new_request[key]}")
    for old_day, new_day in zip(old["days"], new["days"]):
        if any(old_day.get(key) != new_day.get(key) for key in ("morning", "afternoon", "evening", "places")):
            changes.append(f"第{new_day['day']}天安排已调整")
    if len(old["days"]) != len(new["days"]):
        changes.append("行程天数已调整")
    if old["budget_total"] != new["budget_total"]:
        changes.append(f"预估费用：¥{old['budget_total']} → ¥{new['budget_total']}")
    return changes or ["已按追问重新核验行程"]


def create_session(request: PlanRequest) -> dict[str, Any]:
    result = plan_trip(request)
    now = datetime.now(timezone.utc).isoformat()
    session = {"session_id": str(uuid.uuid4()), "title": f"{request.city} · {request.days}日行程",
               "created_at": now, "updated_at": now,
               "questions": [],
               "versions": [{"version": 1, "message": "生成初版行程", "request": request.model_dump(),
                             "result": result, "changes": ["初版行程"], "created_at": now}]}
    with _LOCK:
        _write(session)
    return session


def revise_session(session_id: str, instruction: str, base_version: int) -> dict[str, Any]:
    session = get_session(session_id)
    previous = session["versions"][-1]
    if previous["version"] != base_version:
        raise PlannerVersionConflict("行程已有更新，请刷新后再修改")
    if len(session["versions"]) >= MAX_VERSIONS:
        raise PlannerSessionLimit("当前行程已达到版本上限，请新建行程")
    old_request = PlanRequest.model_validate(previous["request"])
    action, request = _resolve_request(old_request, instruction)
    if action == "answer":
        answer = _answer_question(previous, instruction)
        now = datetime.now(timezone.utc).isoformat()
        with _LOCK:
            session = get_session(session_id)
            if session["versions"][-1]["version"] != base_version:
                raise PlannerVersionConflict("行程已有更新，请刷新后再提问")
            session.setdefault("questions", []).append({"question": instruction, "answer": answer,
                                                       "version": base_version, "created_at": now})
            session["updated_at"] = now
            _write(session)
        return session
    context = {"instruction": instruction, "previous_plan": previous["result"]["plan"],
               "previous_city": old_request.city, "previous_run_id": previous["result"]["run_id"]}
    result = plan_trip(request, revision_context=context)
    now = datetime.now(timezone.utc).isoformat()
    version = {"version": base_version + 1, "message": instruction,
               "request": request.model_dump(), "result": result,
               "changes": _changes(previous["result"]["plan"], result["plan"],
                                   old_request.model_dump(), request.model_dump()),
               "created_at": now}
    with _LOCK:
        session = get_session(session_id)
        if session["versions"][-1]["version"] != base_version:
            raise PlannerVersionConflict("行程已有更新，请刷新后再修改")
        session["versions"].append(version)
        session["updated_at"] = now
        session["title"] = f"{request.city} · {request.days}日行程"
        _write(session)
    return session
