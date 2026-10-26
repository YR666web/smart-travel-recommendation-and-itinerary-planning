"""向量索引写入与失败恢复测试。"""
import pytest

from app.rag import store


def test_store_persists_and_deletes_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_INDEX_FILE", str(tmp_path / "index.npz"))
    index = store.VectorStore()
    index.add(["a"], ["资料"], [[1.0, 0.0]], [{"document_id": 1}])
    assert store.VectorStore().count() == 1
    snapshot = index.get_by_document(1)
    index.delete_by_document(1)
    assert store.VectorStore().count() == 0
    index.add(**snapshot)
    assert index.count() == 1
    index.replace_all(["new"], ["新资料"], [[0.0, 1.0]], [{"document_id": 2}])
    assert store.VectorStore().get_by_document(2)["ids"] == ["new"]


def test_failed_save_restores_in_memory_state(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_INDEX_FILE", str(tmp_path / "index.npz"))
    index = store.VectorStore()
    index.add(["a"], ["资料"], [[1.0, 0.0]], [{"document_id": 1}])

    def fail():
        raise OSError("disk unavailable")

    monkeypatch.setattr(index, "_save", fail)
    with pytest.raises(OSError):
        index.add(["b"], ["资料2"], [[0.0, 1.0]], [{"document_id": 2}])
    assert index.count() == 1
    with pytest.raises(OSError):
        index.delete_by_document(1)
    assert index.count() == 1


def test_region_filter_matches_multicity_document(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_INDEX_FILE", str(tmp_path / "index.npz"))
    index = store.VectorStore()
    index.add(["route", "province"], ["资料1", "资料2"],
              [[1.0, 0.0], [1.0, 0.0]],
              [{"region": "杭州、乌镇", "source_file": "杭州线路推荐.md"},
               {"region": "昆明、大理、丽江", "source_file": "云南线路推荐.md"}])
    assert index.query([1.0, 0.0], where={"region": "杭州"})["ids"] == [["route"]]
    assert index.query([1.0, 0.0], where={"region": "云南"})["ids"] == [["province"]]
    assert index.has_region("杭州") is True
    assert index.has_region("上海") is False
