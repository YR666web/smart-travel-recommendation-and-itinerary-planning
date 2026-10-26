"""旅行规划 Agent API。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.services.agent_service import AgentRunError, PlanRequest, get_trace, plan_trip
from app.services import planner_session_service as planner_sessions

router = APIRouter(tags=["agent"])


class PlanFollowupRequest(BaseModel):
    message: str = Field(min_length=2, max_length=500)
    base_version: int = Field(ge=1)

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("请描述想修改的行程内容")
        return value


def _plan_error(exc: AgentRunError) -> HTTPException:
    no_sources = str(exc).startswith("这座城市暂无可用资料")
    return HTTPException(status_code=422 if no_sources else 502,
                         detail={"message": str(exc) if no_sources else "旅行规划失败，请查看执行轨迹",
                                 "run_id": exc.run_id})


@router.post("/agent/plan")
def create_plan(request: PlanRequest) -> dict:
    try:
        return plan_trip(request)
    except AgentRunError as exc:
        raise _plan_error(exc) from exc


@router.get("/agent/sessions")
def list_plan_sessions() -> dict:
    return {"sessions": planner_sessions.list_sessions()}


@router.post("/agent/sessions")
def create_plan_session(request: PlanRequest) -> dict:
    try:
        return planner_sessions.create_session(request)
    except AgentRunError as exc:
        raise _plan_error(exc) from exc


@router.get("/agent/sessions/{session_id}")
def get_plan_session(session_id: str) -> dict:
    try:
        return planner_sessions.get_session(session_id)
    except planner_sessions.PlannerSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/agent/sessions/{session_id}")
def delete_plan_session(session_id: str) -> dict:
    try:
        planner_sessions.delete_session(session_id)
    except planner_sessions.PlannerSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/agent/sessions/{session_id}/messages")
def followup_plan(session_id: str, request: PlanFollowupRequest) -> dict:
    try:
        return planner_sessions.revise_session(session_id, request.message.strip(), request.base_version)
    except planner_sessions.PlannerSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except planner_sessions.PlannerVersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except planner_sessions.PlannerSessionLimit as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentRunError as exc:
        raise _plan_error(exc) from exc


@router.get("/agent/runs/{run_id}")
def read_run(run_id: str) -> dict:
    trace = get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="执行轨迹不存在")
    return trace
