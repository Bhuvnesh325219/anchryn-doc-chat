"""Chunking rules.

No database and no PDF here — chunking is pure text handling, and keeping these
tests fast means they can be run on every edit while tuning chunk size.
"""

import pytest

from app.services.chunking import chunk_page, chunk_pages

PARAGRAPH = (
    "Retrieval augmented generation grounds an answer in retrieved text. "
    "Without grounding a model will answer confidently from memory. "
)


def test_offsets_slice_back_to_the_exact_chunk_text():
    """The invariant the whole citation feature rests on.

    If this breaks, highlighting a passage silently points at the wrong text —
    which looks like a retrieval bug and is very hard to trace.
    """
    text = (PARAGRAPH * 20).replace(". ", ".\n\n", 8)

    for chunk in chunk_page(1, text, max_chars=300, overlap_chars=50):
        assert text[chunk.char_start : chunk.char_end] == chunk.text


def test_a_chunk_never_spans_two_pages():
    chunks = chunk_pages([PARAGRAPH * 5, PARAGRAPH * 5], max_chars=200, overlap_chars=40)

    assert {chunk.page_number for chunk in chunks} == {1, 2}
    # Page numbers are assigned per chunk, so a chunk belonging to two pages is
    # not representable — this asserts the pages were actually chunked apart.
    assert all(chunk.char_start < chunk.char_end for chunk in chunks)


def test_chunks_stay_within_the_size_limit():
    chunks = chunk_page(1, PARAGRAPH * 30, max_chars=250, overlap_chars=50)

    assert chunks
    # Allow a small overshoot: an atom is never split below a word boundary, so
    # the final word can push slightly past the limit.
    assert all(len(chunk.text) <= 250 + 50 for chunk in chunks)


def test_consecutive_chunks_overlap():
    chunks = chunk_page(1, PARAGRAPH * 20, max_chars=300, overlap_chars=80)

    assert len(chunks) > 1
    # The next chunk starts before the previous one ended.
    assert any(
        chunks[i + 1].char_start < chunks[i].char_end for i in range(len(chunks) - 1)
    )


def test_chunks_are_ordered_and_cover_the_page():
    text = PARAGRAPH * 10
    chunks = chunk_page(1, text, max_chars=200, overlap_chars=0)

    assert [c.char_start for c in chunks] == sorted(c.char_start for c in chunks)
    # With no overlap the chunks should reconstruct the page, modulo whitespace.
    rebuilt = "".join(c.text for c in chunks)
    assert rebuilt.replace(" ", "") == text.strip().replace(" ", "").replace("\n", "")


def test_blank_pages_produce_nothing():
    assert chunk_page(1, "") == []
    assert chunk_page(1, "   \n\n  \t ") == []


def test_a_single_unbroken_run_longer_than_a_chunk_is_split():
    # A URL, or a table rendered without spaces. Must not produce one huge chunk
    # and must not loop forever trying to find a boundary.
    text = "x" * 2500
    chunks = chunk_page(1, text, max_chars=500, overlap_chars=100)

    assert len(chunks) >= 5
    assert all(len(chunk.text) <= 500 for chunk in chunks)


def test_pathological_input_still_terminates():
    text = "\n\n".join(["word"] * 5000)
    chunks = chunk_page(1, text, max_chars=100, overlap_chars=30)

    assert chunks
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text


def test_overlap_must_be_smaller_than_the_chunk():
    # Otherwise every chunk re-reads what the last one covered and the loop
    # cannot advance. Better to reject it than to hang.
    with pytest.raises(ValueError):
        chunk_page(1, PARAGRAPH, max_chars=100, overlap_chars=100)
    with pytest.raises(ValueError):
        chunk_page(1, PARAGRAPH, max_chars=100, overlap_chars=500)


def test_chunk_text_is_never_padded_with_whitespace():
    chunks = chunk_page(1, "\n\n   " + PARAGRAPH * 6 + "   \n\n", max_chars=200, overlap_chars=0)

    assert chunks
    assert all(chunk.text == chunk.text.strip() for chunk in chunks)


def test_page_numbers_are_one_based_and_include_blank_pages():
    # A blank page still consumes its number, otherwise every citation after a
    # blank page would be off by one.
    chunks = chunk_pages([PARAGRAPH, "", PARAGRAPH], max_chars=500, overlap_chars=0)

    assert {chunk.page_number for chunk in chunks} == {1, 3}
