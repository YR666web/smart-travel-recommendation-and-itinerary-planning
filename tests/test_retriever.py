"""语义候选的关键词重排，保留原相似度阈值语义。"""
from app.rag import retriever


def test_lexical_rerank_changes_order_without_changing_cosine_score(monkeypatch):
    monkeypatch.setattr(retriever, "embed", lambda texts: [[0.0]])

    class Store:
        def query(self, embedding, top_k, where):
            assert top_k >= 20
            return {"ids": [["a", "b"]],
                    "documents": [["普通旅游介绍", "西湖游览指南与景点建议"]],
                    "metadatas": [[{}, {}]], "distances": [[0.2, 0.22]]}

    monkeypatch.setattr(retriever, "get_vector_store", lambda: Store())
    hits = retriever.retrieve("西湖景点", top_k=1)
    assert hits[0]["id"] == "b"
    assert hits[0]["score"] == 0.78
