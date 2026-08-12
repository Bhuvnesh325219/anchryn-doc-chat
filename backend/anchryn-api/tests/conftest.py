"""Shared test fixtures.

These run against the local development database rather than a throwaway one.
That keeps setup simple, but it means teardown must only remove what a test
created — never everything — or running the suite would wipe documents you
uploaded by hand.
"""

import io
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.db import SessionLocal
from app.main import app
from app.models import Document


@pytest.fixture
def anon_client() -> Iterator[TestClient]:
    """A client with no credentials, for testing the gate itself."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client(anon_client: TestClient) -> TestClient:
    """A client signed in as a fresh account.

    Every test gets its own user, so one test's documents can never be visible
    to another — the same isolation the application provides, applied to the
    suite. It also means tests can run in any order.
    """
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    response = anon_client.post(
        "/api/auth/register", json={"email": email, "password": "test password 123"}
    )
    assert response.status_code == 201, response.text

    anon_client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
    return anon_client


@pytest.fixture
def created_documents() -> Iterator[list[str]]:
    """Register document ids here and they are deleted after the test."""
    ids: list[str] = []
    yield ids

    with SessionLocal() as session:
        for document_id in ids:
            document = session.get(Document, document_id)
            if document is not None:
                session.delete(document)
        session.commit()


def make_pdf(pages: list[str]) -> bytes:
    """A real PDF with known text on each page.

    Generated rather than committed as a fixture file so the expected text lives
    next to the assertion that checks it.
    """
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    for page_text in pages:
        y = 750
        for line in page_text.split("\n"):
            pdf.drawString(72, y, line)
            y -= 14
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@pytest.fixture
def sample_pdf() -> bytes:
    return make_pdf(
        [
            ("Anchryn keeps every answer anchored to a source passage.\n"
            "Retrieval happens before generation, never the other way around."),
            ("Chunks never span two pages, because a citation must name one page.\n"
            "Character offsets index into the stored page text."),
        ]
    )
