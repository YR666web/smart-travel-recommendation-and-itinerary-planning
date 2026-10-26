"""测试全局 fixture。"""
import pytest


@pytest.fixture(scope="session")
def warmup_model():
    """预热 Embedding 模型，规避 torch 与 pymysql 在 Windows 下的原生库冲突。"""
    from app.rag.embedder import embed

    embed(["预热"])
    yield


@pytest.fixture(scope="session")
def live_database():
    """仅端到端测试依赖真实 MySQL；服务未启动时明确跳过。"""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from app.models import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"MySQL 不可用：{exc.orig}")
