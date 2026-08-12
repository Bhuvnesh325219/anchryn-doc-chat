"""Shared FastAPI dependencies.

``current_user`` is the single gate every protected route goes through. Routes
take it as a parameter and then filter their queries by ``user.id`` — there is
no ambient "who am I" state, so a route that forgets ownership is visible in its
own signature.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.services.security import InvalidTokenError, decode_access_token

# auto_error=False so a missing header produces our own 401 with a readable
# message rather than FastAPI's bare "Not authenticated".
_bearer = HTTPBearer(auto_error=False)

UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not signed in, or the session has expired.",
    headers={"WWW-Authenticate": "Bearer"},
)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None or not credentials.credentials:
        raise UNAUTHENTICATED

    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise UNAUTHENTICATED from exc

    user = session.get(User, user_id)
    if user is None:
        # A validly signed token for a deleted account. Same response as an
        # invalid token: the caller does not need to be able to tell them apart.
        raise UNAUTHENTICATED

    return user
