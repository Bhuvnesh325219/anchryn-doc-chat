"""Grounding behaviour of the answering step.

The model call is stubbed. What is worth testing here is not whether the model
writes well — it is whether the refusal is enforced by our code, whether
citations are mapped honestly, and whether a fabricated reference is dropped.
Those are our decisions, and a live model would make them non-deterministic.
"""

import uuid

import pytest

from app.services.generation import (
    REFUSAL,
    Answer,
    _extract_citations,
    answer_from_chunks,
)
from app.services.retrieval import RetrievedChunk


def chunk(chunk_id: int, text: str = "some text") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=uuid.uuid4(),
        filename="handbook.pdf",
        page_number=1,
        char_start=0,
        char_end=len(text),
        text=text,
        similarity=0.8,
    )


def test_refuses_without_calling_the_model_when_ungrounded(monkeypatch):
    """The refusal must be ours, not the model's.

    Asking a model to decline and trusting it to comply is the failure this
    project exists to avoid — and skipping the call costs no quota.
    """

    def explode(_prompt):
        raise AssertionError("the model must not be called when ungrounded")

    monkeypatch.setattr("app.services.generation._call_model", explode)

    result = answer_from_chunks("anything", [chunk(1)], grounded=False)

    assert result.grounded is False
    assert result.text == REFUSAL
    assert result.cited_chunk_ids == []


def test_refuses_when_there_are_no_chunks_at_all(monkeypatch):
    monkeypatch.setattr(
        "app.services.generation._call_model",
        lambda _p: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    assert answer_from_chunks("anything", [], grounded=True).text == REFUSAL


def test_honours_the_models_own_refusal(monkeypatch):
    """Clearing the similarity threshold is not the same as answering.

    Passages can be topically close and still not contain the answer, so the
    model is given a way to say so and it is taken seriously.
    """
    monkeypatch.setattr(
        "app.services.generation._call_model", lambda _p: "NOT_IN_DOCUMENTS"
    )

    result = answer_from_chunks("what is the refund window?", [chunk(1)], grounded=True)

    assert result.grounded is False
    assert result.text == REFUSAL


def test_maps_citation_markers_to_chunk_ids(monkeypatch):
    monkeypatch.setattr(
        "app.services.generation._call_model",
        lambda _p: "Invoices go out monthly [2]. Payment is due in thirty days [2][3].",
    )

    result = answer_from_chunks(
        "when are invoices sent?", [chunk(101), chunk(202), chunk(303)], grounded=True
    )

    assert result.grounded is True
    # [2] and [3] are 1-based positions, mapping to the 2nd and 3rd chunk ids.
    assert result.cited_chunk_ids == [202, 303]


def test_drops_a_fabricated_citation():
    """A model citing [7] when given three passages invented the reference.

    Passing that through would produce a citation pointing at nothing, which is
    worse than no citation at all.
    """
    chunks = [chunk(11), chunk(22), chunk(33)]

    assert _extract_citations("Supported by [2] and also [7].", chunks) == [22]


def test_citations_are_deduplicated_and_ordered_by_first_use():
    chunks = [chunk(11), chunk(22), chunk(33)]

    assert _extract_citations("[3] then [1] then [3] again.", chunks) == [33, 11]


def test_an_answer_with_no_citations_is_still_returned(monkeypatch):
    # Not ideal, but suppressing the answer would be worse than showing it
    # uncited — the UI can flag the absence.
    monkeypatch.setattr("app.services.generation._call_model", lambda _p: "Monthly.")

    result = answer_from_chunks("how often?", [chunk(1)], grounded=True)

    assert result.text == "Monthly."
    assert result.cited_chunk_ids == []
    assert result.grounded is True


@pytest.mark.parametrize("marker", ["[0]", "[99]", "[-1]"])
def test_out_of_range_markers_never_map(marker):
    assert _extract_citations(f"claim {marker}", [chunk(11)]) == []


def test_returns_the_answer_type():
    result = answer_from_chunks("q", [], grounded=False)
    assert isinstance(result, Answer)
