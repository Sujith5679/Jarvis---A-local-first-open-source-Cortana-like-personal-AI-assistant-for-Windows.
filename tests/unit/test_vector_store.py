from __future__ import annotations

from rag.vector_store import VectorStore

DIM = 4


def test_add_and_search_returns_best_match(tmp_path):
    store = VectorStore(dimension=DIM, index_path=tmp_path / "vectors.faiss")
    store.add(
        ids=[1, 2, 3],
        vectors=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
    )
    results = store.search([0.9, 0.1, 0, 0], top_k=2)
    assert results[0][0] == 1  # closest to [1,0,0,0]
    assert len(results) == 2


def test_empty_store_search_returns_empty(tmp_path):
    store = VectorStore(dimension=DIM, index_path=tmp_path / "vectors.faiss")
    assert store.search([1, 0, 0, 0]) == []
    assert store.size == 0


def test_remove_ids(tmp_path):
    store = VectorStore(dimension=DIM, index_path=tmp_path / "vectors.faiss")
    store.add(ids=[1, 2], vectors=[[1, 0, 0, 0], [0, 1, 0, 0]])
    assert store.size == 2
    store.remove([1])
    assert store.size == 1
    results = store.search([1, 0, 0, 0], top_k=5)
    assert all(r[0] != 1 for r in results)


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "vectors.faiss"
    store1 = VectorStore(dimension=DIM, index_path=path)
    store1.add(ids=[42], vectors=[[0, 0, 0, 1]])

    store2 = VectorStore(dimension=DIM, index_path=path)
    assert store2.size == 1
    results = store2.search([0, 0, 0, 1])
    assert results[0][0] == 42


def test_dimension_mismatch_raises(tmp_path):
    path = tmp_path / "vectors.faiss"
    VectorStore(dimension=DIM, index_path=path).add(ids=[1], vectors=[[1, 0, 0, 0]])

    import pytest

    with pytest.raises(ValueError):
        VectorStore(dimension=8, index_path=path)
