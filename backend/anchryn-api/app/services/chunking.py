"""Splitting page text into retrievable chunks.

Two rules drive the design:

1. **A chunk never spans two pages.** A citation has to name one page, and a
   chunk straddling a page boundary could not.

2. **Offsets are exact.** For every chunk produced here,
   ``page_text[chunk.char_start:chunk.char_end] == chunk.text`` holds. That is
   what lets the UI highlight the precise passage in its original context rather
   than just naming the file. The text is never rewritten or normalised, only
   sliced — normalising would break the mapping.
"""

import re
from dataclasses import dataclass

#: Roughly 200-250 tokens. Small enough that a chunk is about one idea, large
#: enough to carry the context needed to answer from it.
DEFAULT_MAX_CHARS = 1000

#: Carried from the end of one chunk into the start of the next, so a sentence
#: split across a boundary is still retrievable from at least one of them.
DEFAULT_OVERLAP_CHARS = 150

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class TextChunk:
    page_number: int
    char_start: int
    char_end: int
    text: str


def chunk_pages(
    pages: list[str],
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[TextChunk]:
    """Chunk every page, in order. Page numbers are 1-based."""
    chunks: list[TextChunk] = []
    for page_number, text in enumerate(pages, start=1):
        chunks.extend(chunk_page(page_number, text, max_chars, overlap_chars))
    return chunks


def chunk_page(
    page_number: int,
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[TextChunk]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        # Overlap at or beyond the chunk size would mean each chunk re-reads
        # everything the last one did, and the loop would never advance.
        raise ValueError("overlap_chars must be >= 0 and < max_chars")
    if not text.strip():
        return []

    spans = _atoms(text, max_chars)
    chunks: list[TextChunk] = []
    current: list[tuple[int, int]] = []

    for span in spans:
        if current and _span_length(current[0][0], span[1]) > max_chars:
            _emit(chunks, page_number, text, current)
            current = _overlap_tail(current, overlap_chars)
        current.append(span)

    if current:
        _emit(chunks, page_number, text, current)

    return chunks


def _atoms(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Break the page into the smallest pieces we are willing to split between.

    Paragraphs first, then sentences, then words — falling through only when a
    piece is still too big to fit a chunk on its own.
    """
    atoms: list[tuple[int, int]] = []
    for start, end in _split_spans(text, _PARAGRAPH_BREAK, 0, len(text)):
        if end - start <= max_chars:
            atoms.append((start, end))
            continue

        for s2, e2 in _split_spans(text, _SENTENCE_BREAK, start, end):
            if e2 - s2 <= max_chars:
                atoms.append((s2, e2))
                continue

            for s3, e3 in _split_spans(text, _WHITESPACE, s2, e2):
                if e3 - s3 <= max_chars:
                    atoms.append((s3, e3))
                else:
                    # A single unbroken run longer than a whole chunk — a URL, a
                    # table rendered without spaces. Cut it at the limit.
                    for cut in range(s3, e3, max_chars):
                        atoms.append((cut, min(cut + max_chars, e3)))

    return [(s, e) for s, e in atoms if text[s:e].strip()]


def _split_spans(
    text: str, pattern: re.Pattern[str], start: int, end: int
) -> list[tuple[int, int]]:
    """Spans between matches of ``pattern`` within ``text[start:end]``."""
    spans: list[tuple[int, int]] = []
    cursor = start
    for match in pattern.finditer(text, start, end):
        if match.start() > cursor:
            spans.append((cursor, match.start()))
        cursor = match.end()
    if cursor < end:
        spans.append((cursor, end))
    return spans or [(start, end)]


def _overlap_tail(
    current: list[tuple[int, int]], overlap_chars: int
) -> list[tuple[int, int]]:
    """Trailing atoms of the emitted chunk to repeat at the start of the next.

    Never returns the whole list: keeping every atom would mean the next chunk
    begins where the last one did and the loop would not advance.
    """
    if overlap_chars == 0 or len(current) < 2:
        return []

    tail: list[tuple[int, int]] = []
    total = 0
    for span in reversed(current[1:]):
        length = span[1] - span[0]
        if total + length > overlap_chars:
            break
        tail.insert(0, span)
        total += length
    return tail


def _emit(
    chunks: list[TextChunk],
    page_number: int,
    text: str,
    spans: list[tuple[int, int]],
) -> None:
    start, end = spans[0][0], spans[-1][1]

    # Trim surrounding whitespace by moving the offsets, not by rewriting the
    # text — that is what keeps text == page_text[char_start:char_end].
    raw = text[start:end]
    start += len(raw) - len(raw.lstrip())
    end -= len(raw) - len(raw.rstrip())

    if end <= start:
        return
    if chunks and chunks[-1].char_start == start and chunks[-1].char_end == end:
        return  # identical span, nothing gained by storing it twice

    chunks.append(
        TextChunk(
            page_number=page_number,
            char_start=start,
            char_end=end,
            text=text[start:end],
        )
    )


def _span_length(start: int, end: int) -> int:
    return end - start
