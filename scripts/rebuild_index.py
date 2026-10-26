"""从 MySQL 文档片段重建本地向量索引。运行前备份 storage/vector_index.npz。"""
from app.rag.embedder import embed

embed(["预热"])

from app.models import Chunk, Document, SessionLocal  # noqa: E402
from app.rag.store import get_vector_store  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .order_by(Document.id, Chunk.chunk_index)
            .all()
        )
        if not rows:
            raise RuntimeError("数据库中没有片段，拒绝清空现有向量索引")

        ids = []
        documents = []
        metadatas = []
        for chunk, doc in rows:
            ids.append(chunk.vector_id or f"doc-{doc.id}-chunk-{chunk.chunk_index}")
            documents.append(chunk.content)
            metadatas.append({
                "document_id": doc.id,
                "content_type": doc.content_type,
                "region": doc.region or "",
                "name": doc.name or "",
                "heading_path": chunk.heading_path or "",
                "source_file": doc.source_file,
            })
    finally:
        db.close()

    embeddings = []
    for start in range(0, len(documents), 32):
        embeddings.extend(embed(documents[start:start + 32]))
    get_vector_store().replace_all(ids, documents, embeddings, metadatas)
    print(f"已从数据库重建 {len(ids)} 个向量片段")


if __name__ == "__main__":
    main()
