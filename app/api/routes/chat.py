"""知识问答接口。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.services import chat_service

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


@router.post("/chat")
def chat(req: ChatRequest) -> dict:
    """单轮/多轮问答（非流式）。"""
    return chat_service.chat(req.query, session_id=req.session_id)


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> EventSourceResponse:
    """问答流式（SSE）。"""
    return EventSourceResponse(chat_service.chat_stream(req.query, req.session_id))
