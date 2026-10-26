"""向量库封装：本地 numpy 向量索引（余弦相似度暴力检索）。

数据量级（数百 chunk）下暴力检索即可满足，规避原生向量库在 Windows 下的稳定性问题。
"""
from __future__ import annotations

import os
import threading
import tempfile
from typing import Any

import numpy as np

_INDEX_FILE = os.path.join("storage", "vector_index.npz")

_vector_store: "VectorStore | None" = None
_vector_store_lock = threading.Lock()


class VectorStore:
    """numpy 向量索引（线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids: list[str] = []
        self._documents: list[str] = []
        self._metadatas: list[dict[str, Any]] = []
        self._embeddings: np.ndarray | None = None
        self._load()

    # ---- 持久化 ----
    def _load(self) -> None:
        if not os.path.exists(_INDEX_FILE):
            return
        data = np.load(_INDEX_FILE, allow_pickle=True)
        self._ids = list(data["ids"])
        self._documents = list(data["documents"])
        self._metadatas = list(data["metadatas"])
        self._embeddings = data["embeddings"]

    def _save(self) -> None:
        os.makedirs(os.path.dirname(_INDEX_FILE), exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(_INDEX_FILE), suffix=".npz", delete=False) as f:
                temp_path = f.name
                np.savez(
                    f,
                    ids=np.array(self._ids, dtype=object),
                    documents=np.array(self._documents, dtype=object),
                    metadatas=np.array(self._metadatas, dtype=object),
                    embeddings=self._embeddings if self._embeddings is not None else np.zeros((0, 0)),
                )
            os.replace(temp_path, _INDEX_FILE)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    # ---- 对外接口 ----
    def add(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """写入向量片段（含 metadata）。"""
        with self._lock:
            old_count = len(self._ids)
            old_embeddings = self._embeddings
            emb = np.array(embeddings, dtype=np.float32)
            self._embeddings = (
                emb if self._embeddings is None else np.vstack([self._embeddings, emb])
            )
            self._ids.extend(ids)
            self._documents.extend(documents)
            self._metadatas.extend(metadatas)
            try:
                self._save()
            except Exception:
                del self._ids[old_count:]
                del self._documents[old_count:]
                del self._metadatas[old_count:]
                self._embeddings = old_embeddings
                raise

    def get_by_document(self, document_id: int) -> dict[str, Any]:
        """获取文档向量快照，用于数据库删除失败时恢复。"""
        with self._lock:
            indexes = [i for i, m in enumerate(self._metadatas) if m.get("document_id") == document_id]
            return {
                "ids": [self._ids[i] for i in indexes],
                "documents": [self._documents[i] for i in indexes],
                "metadatas": [self._metadatas[i].copy() for i in indexes],
                "embeddings": [self._embeddings[i].tolist() for i in indexes] if self._embeddings is not None else [],
            }

    def replace_all(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """一次性重建索引，保存失败时保留原索引。"""
        if not (len(ids) == len(documents) == len(embeddings) == len(metadatas)):
            raise ValueError("索引字段数量不一致")
        with self._lock:
            old_state = (self._ids, self._documents, self._metadatas, self._embeddings)
            self._ids = list(ids)
            self._documents = list(documents)
            self._metadatas = [m.copy() for m in metadatas]
            self._embeddings = np.asarray(embeddings, dtype=np.float32) if embeddings else None
            try:
                self._save()
            except Exception:
                self._ids, self._documents, self._metadatas, self._embeddings = old_state
                raise

    def query(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """余弦相似度检索，支持元数据过滤。"""
        with self._lock:
            return self._query_unlocked(query_embedding, top_k, where)

    def _query_unlocked(
        self,
        query_embedding: list[float],
        top_k: int,
        where: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if self._embeddings is None or len(self._ids) == 0:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        q = np.array(query_embedding, dtype=np.float32)
        sims = self._embeddings @ q  # 向量已归一化，点积即余弦相似度

        mask = np.ones(len(self._ids), dtype=bool)
        if where:
            for cond in self._flatten_where(where):
                mask &= self._match_where(cond)

        valid = np.where(mask)[0]
        if len(valid) == 0:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        order = np.argsort(-sims[valid])[:top_k]
        idx = valid[order]

        return {
            "ids": [[self._ids[i] for i in idx]],
            "documents": [[self._documents[i] for i in idx]],
            "metadatas": [[self._metadatas[i] for i in idx]],
            "distances": [[float(1 - sims[i]) for i in idx]],
        }

    def delete_by_document(self, document_id: int) -> None:
        """按文档删除向量片段。"""
        with self._lock:
            old_state = (self._ids, self._documents, self._metadatas, self._embeddings)
            keep = [
                i for i, m in enumerate(self._metadatas)
                if m.get("document_id") != document_id
            ]
            if len(keep) == len(self._ids):
                return
            self._ids = [self._ids[i] for i in keep]
            self._documents = [self._documents[i] for i in keep]
            self._metadatas = [self._metadatas[i] for i in keep]
            self._embeddings = (
                self._embeddings[keep] if self._embeddings is not None else None
            )
            try:
                self._save()
            except Exception:
                self._ids, self._documents, self._metadatas, self._embeddings = old_state
                raise

    def count(self) -> int:
        """片段总数。"""
        with self._lock:
            return len(self._ids)

    def has_region(self, region: str) -> bool:
        """该目的地是否已有本地资料。"""
        with self._lock:
            return bool(self._match_where({"region": region}).any())

    # ---- where 语法 ----
    @staticmethod
    def _flatten_where(where: dict[str, Any]) -> list[dict[str, Any]]:
        if "$and" in where:
            return where["$and"]
        return [where]

    def _match_where(self, cond: dict[str, Any]) -> np.ndarray:
        mask = np.ones(len(self._ids), dtype=bool)
        for k, v in cond.items():
            if k == "region":
                # 一份线路可能覆盖多个城市，区域名称也可能出现在文档名中。
                mask &= np.array([
                    str(v) in str(m.get("region") or "") or
                    str(v) in str(m.get("source_file") or "")
                    for m in self._metadatas
                ])
            else:
                mask &= np.array([m.get(k) == v for m in self._metadatas])
        return mask


def get_vector_store() -> VectorStore:
    """获取向量库单例（延迟初始化）。"""
    global _vector_store
    if _vector_store is None:
        with _vector_store_lock:
            if _vector_store is None:
                _vector_store = VectorStore()
    return _vector_store
