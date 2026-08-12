"""Registration, sign-in, and — most importantly — isolation between accounts.

The isolation tests are the reason this file exists. A broken login is obvious
the moment anyone tries it; a missing ownership filter is invisible until
someone else's private document turns up in an answer.
"""

import uuid

import pytest

from tests.conftest import make_pdf


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def register(anon_client, email: str | None = None, password: str = "correct horse battery") -> dict:
    response = anon_client.post(
        "/api/auth/register",
        json={"email": email or unique_email(), "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- registration


def test_registering_returns_a_usable_token(anon_client):
    body = register(anon_client)

    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "password" not in str(body)  # never echo it back, hashed or otherwise

    me = anon_client.get("/api/auth/me", headers=auth_header(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == body["user"]["email"]


def test_the_same_email_cannot_register_twice(anon_client):
    email = unique_email()
    register(anon_client, email)

    again = anon_client.post("/api/auth/register", json={"email": email, "password": "another one!"})

    assert again.status_code == 409


def test_email_case_and_spacing_do_not_create_a_second_account(anon_client):
    email = unique_email()
    register(anon_client, email)

    again = anon_client.post(
        "/api/auth/register",
        json={"email": f"  {email.upper()}  ", "password": "another one!"},
    )

    assert again.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "long enough here"},
        {"email": "a@b.com", "password": "short"},
        {"email": "a@b.com"},
        {"password": "long enough here"},
    ],
)
def test_bad_registrations_are_rejected(anon_client, payload):
    assert anon_client.post("/api/auth/register", json=payload).status_code == 422


# ---------------------------------------------------------------- signing in


def test_signing_in_with_the_right_password(anon_client):
    email = unique_email()
    register(anon_client, email, password="correct horse battery")

    response = anon_client.post(
        "/api/auth/login", json={"email": email, "password": "correct horse battery"}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_a_wrong_password_and_an_unknown_account_are_indistinguishable(anon_client):
    """Different messages here would turn login into an email-enumeration oracle."""
    email = unique_email()
    register(anon_client, email, password="correct horse battery")

    wrong = anon_client.post("/api/auth/login", json={"email": email, "password": "wrong password"})
    unknown = anon_client.post(
        "/api/auth/login", json={"email": unique_email(), "password": "correct horse battery"}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


# ---------------------------------------------------------------- gate


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/documents"),
        ("post", "/api/answer"),
        ("post", "/api/ask"),
        ("get", "/api/auth/me"),
    ],
)
def test_protected_routes_reject_anonymous_callers(anon_client, method, path):
    # Only POST carries a body; TestClient.get() rejects a json argument.
    response = (
        anon_client.post(path, json={"question": "anything"})
        if method == "post"
        else anon_client.get(path)
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer not-a-real-token"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic abc"},
    ],
)
def test_malformed_tokens_are_rejected(anon_client, header):
    assert anon_client.get("/api/auth/me", headers=header).status_code == 401


def test_a_token_for_a_deleted_account_stops_working(anon_client):
    from app.db import SessionLocal
    from app.models import User

    body = register(anon_client)
    token = body["access_token"]
    assert anon_client.get("/api/auth/me", headers=auth_header(token)).status_code == 200

    with SessionLocal() as session:
        session.delete(session.get(User, uuid.UUID(body["user"]["id"])))
        session.commit()

    # The signature is still valid; the account behind it is not.
    assert anon_client.get("/api/auth/me", headers=auth_header(token)).status_code == 401


# ---------------------------------------------------------------- isolation


@pytest.fixture
def two_users(anon_client):
    """Two accounts, the first owning an uploaded document."""
    alice = register(anon_client)
    bob = register(anon_client)

    upload = anon_client.post(
        "/api/documents",
        files={"file": ("alice-private.pdf", make_pdf(["Alice's salary is forty two thousand."]), "application/pdf")},
        headers=auth_header(alice["access_token"]),
    )
    assert upload.status_code == 201

    return alice, bob, upload.json()


def test_a_user_only_sees_their_own_documents(anon_client, two_users):
    alice, bob, document = two_users

    mine = anon_client.get("/api/documents", headers=auth_header(alice["access_token"])).json()
    theirs = anon_client.get("/api/documents", headers=auth_header(bob["access_token"])).json()

    assert any(doc["id"] == document["id"] for doc in mine)
    assert all(doc["id"] != document["id"] for doc in theirs)


@pytest.mark.parametrize(
    "path",
    ["", "/chunks", "/pages/1"],
)
def test_another_users_document_is_not_readable(anon_client, two_users, path):
    _, bob, document = two_users

    response = anon_client.get(
        f"/api/documents/{document['id']}{path}", headers=auth_header(bob["access_token"])
    )

    # 404 rather than 403: a 403 would confirm the id exists.
    assert response.status_code == 404


def test_another_users_document_cannot_be_deleted(anon_client, two_users):
    alice, bob, document = two_users

    assert (
        anon_client.delete(
            f"/api/documents/{document['id']}", headers=auth_header(bob["access_token"])
        ).status_code
        == 404
    )
    # And it is genuinely still there.
    assert (
        anon_client.get(
            f"/api/documents/{document['id']}", headers=auth_header(alice["access_token"])
        ).status_code
        == 200
    )


def test_retrieval_never_reaches_another_users_documents(anon_client, two_users):
    """The leak that would matter most, and the one nobody would notice.

    Search is the only query that deliberately spans documents, so a missing
    filter would put someone else's private text into an answer.
    """
    alice, bob, _ = two_users
    question = {"question": "What is Alice's salary?", "top_k": 5}

    mine = anon_client.post("/api/ask", json=question, headers=auth_header(alice["access_token"])).json()
    theirs = anon_client.post("/api/ask", json=question, headers=auth_header(bob["access_token"])).json()

    assert mine["results"], "the owner should find their own document"
    assert theirs["results"] == [], "another user must retrieve nothing"
    assert theirs["grounded"] is False


def test_scoping_to_another_users_document_returns_nothing(anon_client, two_users):
    _, bob, document = two_users

    body = anon_client.post(
        "/api/ask",
        json={"question": "salary", "document_id": document["id"]},
        headers=auth_header(bob["access_token"]),
    ).json()

    assert body["results"] == []


def test_answers_cannot_be_built_from_another_users_documents(anon_client, two_users):
    _, bob, _ = two_users

    body = anon_client.post(
        "/api/answer",
        json={"question": "What is Alice's salary?"},
        headers=auth_header(bob["access_token"]),
    ).json()

    assert body["grounded"] is False
    assert body["results"] == []
    assert "forty two thousand" not in body["answer"]
