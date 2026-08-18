from __future__ import annotations

from tools import file_search


def test_invalidate_cache_clears_cached_retriever(real_db):
    file_search._get_retriever.cache_clear()
    first = file_search._get_retriever()
    second = file_search._get_retriever()
    assert first is second  # cached: same instance

    file_search.invalidate_cache()
    third = file_search._get_retriever()
    assert third is not first  # rebuilt after invalidation

    file_search._get_retriever.cache_clear()
