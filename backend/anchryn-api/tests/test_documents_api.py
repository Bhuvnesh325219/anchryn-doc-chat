"""The upload and inspection endpoints, against a real database and real PDFs."""

from tests.conftest import make_pdf


def _upload(client, created_documents, data: bytes, filename: str = "sample.pdf"):
    response = client.post(
        "/api/documents",
        files={"file": (filename, data, "application/pdf")},
    )
    if response.status_code == 201:
        created_documents.append(response.json()["id"])
    return response


def test_health_reports_the_database_and_model(client):
    body = client.get("/api/health").json()

    assert body["status"] == "UP"
    assert body["database"] == "up"
    assert body["embedding_model"]


def test_uploading_a_pdf_stores_pages_and_chunks(client, created_documents, sample_pdf):
    response = _upload(client, created_documents, sample_pdf)

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "sample.pdf"
    assert body["page_count"] == 2
    assert body["chunk_count"] > 0
    assert body["size_bytes"] == len(sample_pdf)
    # READY only once chunks are embedded — that is what makes it searchable.
    assert body["status"] == "READY"
    assert body["error"] is None


def test_chunk_offsets_slice_back_out_of_the_stored_page(client, created_documents, sample_pdf):
    """End-to-end version of the chunking invariant, through the database.

    Proves the offsets survive extraction, chunking, storage and retrieval —
    which is what a citation highlight actually depends on.
    """
    document_id = _upload(client, created_documents, sample_pdf).json()["id"]

    chunks = client.get(f"/api/documents/{document_id}/chunks").json()
    assert chunks

    for chunk in chunks:
        page = client.get(
            f"/api/documents/{document_id}/pages/{chunk['page_number']}"
        ).json()
        assert page["text"][chunk["char_start"] : chunk["char_end"]] == chunk["text"]


def test_every_chunk_is_embedded_by_upload(client, created_documents, sample_pdf):
    document_id = _upload(client, created_documents, sample_pdf).json()["id"]

    chunks = client.get(f"/api/documents/{document_id}/chunks").json()
    assert chunks
    assert all(chunk["embedded"] is True for chunk in chunks)


def test_backfill_is_a_no_op_when_everything_is_embedded(
    client, created_documents, sample_pdf
):
    document_id = _upload(client, created_documents, sample_pdf).json()["id"]

    response = client.post(f"/api/documents/{document_id}/embed")

    assert response.status_code == 200
    assert response.json()["status"] == "READY"


def test_backfill_fills_in_missing_embeddings(client, created_documents, sample_pdf):
    """The repair path, for chunks stored before embedding or after a failure."""
    from sqlalchemy import update

    from app.db import SessionLocal
    from app.models import Chunk

    document_id = _upload(client, created_documents, sample_pdf).json()["id"]

    # Simulate a half-finished ingest.
    with SessionLocal() as session:
        session.execute(
            update(Chunk).where(Chunk.document_id == document_id).values(embedding=None)
        )
        session.commit()

    assert all(
        chunk["embedded"] is False
        for chunk in client.get(f"/api/documents/{document_id}/chunks").json()
    )

    assert client.post(f"/api/documents/{document_id}/embed").status_code == 200

    assert all(
        chunk["embedded"] is True
        for chunk in client.get(f"/api/documents/{document_id}/chunks").json()
    )


def test_extracted_text_actually_contains_the_document_content(
    client, created_documents
):
    # Guards against "it produced chunks" passing while the text is garbage.
    data = make_pdf(["The capital of France is Paris."])
    document_id = _upload(client, created_documents, data).json()["id"]

    page = client.get(f"/api/documents/{document_id}/pages/1").json()
    assert "capital of France is Paris" in page["text"]


def test_listing_and_fetching_a_document(client, created_documents, sample_pdf):
    document_id = _upload(client, created_documents, sample_pdf).json()["id"]

    listed = client.get("/api/documents").json()
    assert any(doc["id"] == document_id for doc in listed)

    fetched = client.get(f"/api/documents/{document_id}").json()
    assert fetched["id"] == document_id


def test_deleting_a_document_removes_its_chunks(client, created_documents, sample_pdf):
    document_id = _upload(client, created_documents, sample_pdf).json()["id"]

    assert client.delete(f"/api/documents/{document_id}").status_code == 204
    assert client.get(f"/api/documents/{document_id}").status_code == 404
    # Chunks go with it via ON DELETE CASCADE.
    assert client.get(f"/api/documents/{document_id}/chunks").status_code == 404


def test_rejects_a_file_that_is_not_a_pdf(client, created_documents):
    response = _upload(client, created_documents, b"just some text", filename="notes.txt")

    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_rejects_an_empty_file(client, created_documents):
    response = _upload(client, created_documents, b"")

    assert response.status_code == 400


def test_rejects_a_file_that_is_not_really_a_pdf(client, created_documents):
    # Named .pdf but is not one. 422 rather than 400: the request was fine, the
    # content is unusable.
    response = _upload(client, created_documents, b"%PDF-1.4 this is not a real pdf")

    assert response.status_code == 422
    assert "PDF" in response.json()["detail"]


def test_a_rejected_upload_leaves_nothing_behind(client, created_documents):
    """A failed upload must not persist a row.

    Ingestion is synchronous, so the caller already has the error. A stored
    FAILED document would just appear in the list as something the user cannot
    act on or explain.
    """
    before = len(client.get("/api/documents").json())

    assert _upload(client, created_documents, b"%PDF-1.4 not a real pdf").status_code == 422
    assert _upload(client, created_documents, make_pdf(["", ""])).status_code == 422
    assert _upload(client, created_documents, b"x", filename="a.txt").status_code == 400

    assert len(client.get("/api/documents").json()) == before


def test_explains_a_pdf_with_no_text_layer(client, created_documents):
    """A scan is the most common upload that produces nothing.

    "No chunks were created" would send the user looking for the wrong problem,
    so the message has to name OCR.
    """
    blank = make_pdf(["", ""])
    response = _upload(client, created_documents, blank)

    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]


def test_unknown_document_and_page_are_404(client):
    missing = "00000000-0000-0000-0000-000000000000"

    assert client.get(f"/api/documents/{missing}").status_code == 404
    assert client.get(f"/api/documents/{missing}/pages/1").status_code == 404


def test_a_page_beyond_the_document_is_404(client, created_documents, sample_pdf):
    document_id = _upload(client, created_documents, sample_pdf).json()["id"]

    assert client.get(f"/api/documents/{document_id}/pages/99").status_code == 404


def test_the_bare_url_points_somewhere_useful(client):
    """A 404 on / reads as a broken deployment rather than a working API.

    Every route lives under /api, so the root is the first thing anyone opening
    the deployed URL hits.
    """
    body = client.get("/").json()

    assert body["status"] == "running"
    assert body["docs"] == "/docs"
