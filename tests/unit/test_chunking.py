from __future__ import annotations

import pytest
from documents.base import ExtractedSegment
from rag.chunking import chunk_segments


def test_short_segment_becomes_single_chunk():
    segments = [ExtractedSegment(text="one two three", page=1)]
    chunks = chunk_segments(segments, chunk_size=10, overlap=2)
    assert len(chunks) == 1
    assert chunks[0].text == "one two three"
    assert chunks[0].page == 1
    assert chunks[0].chunk_index == 0


def test_long_segment_splits_with_overlap():
    words = [f"w{i}" for i in range(25)]
    segments = [ExtractedSegment(text=" ".join(words))]
    chunks = chunk_segments(segments, chunk_size=10, overlap=3)

    assert len(chunks) == 4  # step=7: 0-10, 7-17, 14-24, 21-25
    assert chunks[0].text.split()[0] == "w0"
    # second chunk starts 7 words in, overlapping the tail of the first
    assert chunks[1].text.split()[0] == "w7"
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1


def test_chunks_never_span_segments():
    segments = [
        ExtractedSegment(text="page one content here", page=1),
        ExtractedSegment(text="page two content here", page=2),
    ]
    chunks = chunk_segments(segments, chunk_size=100, overlap=0)
    assert len(chunks) == 2
    assert chunks[0].page == 1
    assert chunks[1].page == 2


def test_empty_segments_produce_no_chunks():
    segments = [ExtractedSegment(text="   "), ExtractedSegment(text="")]
    assert chunk_segments(segments) == []


def test_invalid_overlap_rejected():
    with pytest.raises(ValueError):
        chunk_segments([ExtractedSegment(text="a b c")], chunk_size=10, overlap=10)
    with pytest.raises(ValueError):
        chunk_segments([ExtractedSegment(text="a b c")], chunk_size=0, overlap=0)


def test_section_metadata_preserved():
    segments = [ExtractedSegment(text="risk assessment findings", section="Risk Assessment")]
    chunks = chunk_segments(segments, chunk_size=50, overlap=0)
    assert chunks[0].section == "Risk Assessment"
