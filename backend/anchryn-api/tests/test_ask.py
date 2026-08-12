"""Retrieval, judged on whether it finds the right passage.

These are the tests that matter most in the project. Everything downstream is
capped by retrieval: if the answering passage is not in these results, no prompt
can produce a correct answer.
"""

import pytest

from tests.conftest import make_pdf

# Four clearly distinct topics, so "the right chunk" is unambiguous.
CORPUS = [
    ("Password Reset\n"
    "To change your password, open account settings and choose Reset Password. "
    "A confirmation email arrives within five minutes."),
    ("Billing Cycles\n"
    "Invoices are issued on the first day of each month. "
    "Payment is due within thirty days of the invoice date."),
    ("Data Retention\n"
    "Uploaded files are kept for ninety days and then deleted automatically. "
    "Deleted files cannot be recovered."),
    ("Rate Limits\n"
    "The API allows one hundred requests per minute per key. "
    "Exceeding the limit returns HTTP 429 with a Retry-After header."),
]


@pytest.fixture
def corpus_document(client, created_documents):
    response = client.post(
        "/api/documents",
        files={"file": ("handbook.pdf", make_pdf(CORPUS), "application/pdf")},
    )
    assert response.status_code == 201
    created_documents.append(response.json()["id"])
    return response.json()


def ask(client, question: str, **kwargs):
    body = {"question": question, **kwargs}
    response = client.post("/api/ask", json=body)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("question", "expected_page"),
    [
        ("How do I reset my password?", 1),
        ("When are invoices sent out?", 2),
        ("How long do you keep my files?", 3),
        ("What happens if I make too many API calls?", 4),
    ],
)
def test_the_answering_passage_ranks_first(client, corpus_document, question, expected_page):
    """Each question must retrieve the page that actually answers it.

    Phrased differently from the source text on purpose — matching keywords is
    not the point, matching meaning is.
    """
    body = ask(client, question)

    assert body["results"], "retrieval returned nothing"
    assert body["results"][0]["page_number"] == expected_page
    assert body["grounded"] is True


def test_a_question_the_documents_do_not_answer_is_not_grounded(client, corpus_document):
    """The refusal signal.

    Without this the bot answers everything, which is exactly the failure the
    project exists to avoid.
    """
    body = ask(client, "What is the best recipe for sourdough bread?")

    assert body["grounded"] is False
    assert body["best_similarity"] < body["threshold"]


def test_results_are_ordered_by_similarity(client, corpus_document):
    body = ask(client, "How do I reset my password?", top_k=4)

    scores = [result["similarity"] for result in body["results"]]
    assert scores == sorted(scores, reverse=True)


def test_a_grounded_question_scores_clearly_above_an_ungrounded_one(client, corpus_document):
    # A margin, not just an ordering — a threshold sitting in a narrow gap would
    # be far too fragile to rely on.
    answerable = ask(client, "How do I reset my password?")["best_similarity"]
    unanswerable = ask(client, "What is the best recipe for sourdough bread?")["best_similarity"]

    assert answerable - unanswerable > 0.2


def test_top_k_is_respected(client, corpus_document):
    assert len(ask(client, "billing", top_k=2)["results"]) == 2
    assert len(ask(client, "billing", top_k=1)["results"]) == 1


def test_citations_slice_back_out_of_the_page(client, corpus_document):
    """A citation has to point at real text, not approximately.

    This is the end-to-end version: question, retrieval, citation, page lookup.
    """
    body = ask(client, "How long do you keep my files?")
    citation = body["results"][0]

    page = client.get(
        f"/api/documents/{citation['document_id']}/pages/{citation['page_number']}"
    ).json()

    assert page["text"][citation["char_start"] : citation["char_end"]] == citation["text"]


def test_search_can_be_limited_to_one_document(client, created_documents, corpus_document):
    other = client.post(
        "/api/documents",
        files={"file": ("other.pdf", make_pdf(["Sourdough needs a starter and a long proof."]), "application/pdf")},
    ).json()
    created_documents.append(other["id"])

    everywhere = ask(client, "How do I make sourdough?")
    assert any(r["document_id"] == other["id"] for r in everywhere["results"])

    scoped = ask(client, "How do I make sourdough?", document_id=corpus_document["id"])
    assert all(r["document_id"] == corpus_document["id"] for r in scoped["results"])


def test_an_empty_question_is_rejected(client):
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ask", json={}).status_code == 422


def test_top_k_is_bounded(client):
    assert client.post("/api/ask", json={"question": "x", "top_k": 0}).status_code == 422
    assert client.post("/api/ask", json={"question": "x", "top_k": 500}).status_code == 422


def test_searching_a_document_with_nothing_in_it_is_not_an_error(client):
    missing = "00000000-0000-0000-0000-000000000000"
    body = ask(client, "anything at all", document_id=missing)

    assert body["results"] == []
    assert body["grounded"] is False
    assert body["best_similarity"] == 0.0
