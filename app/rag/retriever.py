"""检索器：向量检索 + 元数据过滤 + 联网兜底（对应 TDD §5.6）。"""
from __future__ import annotations

from typing import Any

from app.rag.embedder import embed
from app.rag.store import get_vector_store


def retrieve(
    query: str,
    top_k: int = 5,
    content_type: str | None = None,
    region: str | None = None,
) -> list[dict[str, Any]]:
    """向量检索，支持 content_type / region 元数据过滤。"""
    store = get_vector_store()
    query_embedding = embed([query])[0]

    where = _build_where(content_type, region)
    # 先扩大语义候选集，再用轻量中文字符二元组匹配调整排序。
    # score 仍保留原余弦相似度，供下游阈值过滤。
    result = store.query(query_embedding, top_k=max(20, top_k * 4), where=where)
    hits = _parse_result(result)
    terms = _bigrams(query)
    for hit in hits:
        overlap = len(terms & _bigrams(hit.get("content", ""))) / max(len(terms), 1)
        hit["ranking_score"] = round(hit.get("score", 0) + 0.08 * overlap, 4)
    return sorted(hits, key=lambda hit: hit["ranking_score"], reverse=True)[:top_k]


def _bigrams(text: str) -> set[str]:
    compact = "".join(char.lower() for char in text if char.isalnum())
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def _build_where(
    content_type: str | None, region: str | None
) -> dict[str, Any] | None:
    """构造 chromadb 元数据过滤条件。"""
    conditions: list[dict[str, Any]] = []
    if content_type:
        conditions.append({"content_type": content_type})
    if region:
        conditions.append({"region": region})
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _parse_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 chromadb 查询结果为标准 hit 列表。"""
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0] if result.get("distances") else None

    hits: list[dict[str, Any]] = []
    for i, doc_id in enumerate(ids):
        hit: dict[str, Any] = {"id": doc_id}
        if i < len(documents):
            hit["content"] = documents[i]
        if i < len(metadatas) and metadatas[i]:
            hit.update(metadatas[i])
        if distances and i < len(distances) and distances[i] is not None:
            hit["score"] = round(1 - distances[i], 4)  # cosine 距离 → 相似度
        hits.append(hit)
    return hits
