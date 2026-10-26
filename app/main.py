"""智能旅行推荐与行程规划 · RAG 与多轮行程规划系统 — 应用入口。"""
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.api.routes import agent, chat, import_, search, session
from app.config import settings
from app.core.logging import setup_logging, trace_id_var
from app.core.security import is_valid_api_key
from app.models import Chunk, SessionLocal, init_db

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：预热 Embedding 模型 + 建表。

    预热必须在任何数据库操作之前：torch 模型在 pymysql 连接后首次加载会在
    Windows 下触发原生库冲突（段错误），先加载模型即可规避。
    """
    from app.rag.embedder import embed

    embed(["预热"])  # 加载本地 bge 模型，缓存复用
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="面向旅游场景的检索增强生成（RAG）知识库系统",
    lifespan=lifespan,
)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """为每个请求注入 trace_id，贯通结构化日志。"""
    trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:16]
    trace_id_var.set(trace_id)
    if request.url.path.startswith("/api/v1/") and not is_valid_api_key(
        request.headers.get("X-API-Key", ""), settings.app_api_key
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "API Key 无效或缺失"},
            headers={"X-Trace-Id": trace_id},
        )
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


@app.get("/health", tags=["system"])
def health() -> dict:
    """健康检查。"""
    return {"status": "ok", "service": settings.app_name}


@app.get("/ready", tags=["system"])
def ready() -> JSONResponse:
    """检查 MySQL 与本地向量索引是否可共同提供检索。"""
    from app.rag.store import get_vector_store

    try:
        with SessionLocal() as db:
            chunk_count = db.scalar(select(func.count()).select_from(Chunk)) or 0
        index_count = get_vector_store().count()
        matched = chunk_count == index_count
        return JSONResponse(status_code=200 if matched else 503, content={
            "status": "ready" if matched else "index_mismatch",
            "db_chunks": chunk_count, "index_chunks": index_count,
        })
    except Exception:
        return JSONResponse(status_code=503, content={"status": "database_unavailable"})


app.include_router(import_.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(session.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
