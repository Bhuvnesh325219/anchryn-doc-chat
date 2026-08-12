"""Registration and sign-in."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user
from app.models import User
from app.schemas import AuthResponse, Credentials, UserProfile
from app.services.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="That email and password combination is not right.",
)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(credentials: Credentials, session: Session = Depends(get_session)) -> AuthResponse:
    email = credentials.normalised_email()

    user = User(email=email, password_hash=hash_password(credentials.password))
    session.add(user)

    try:
        session.commit()
    except IntegrityError:
        # Relying on the unique index rather than a pre-insert check: two
        # simultaneous registrations would both pass a check and one would still
        # have to fail here.
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account already exists for that email.",
        ) from None

    session.refresh(user)
    logger.info("Registered user %s", user.id)

    return AuthResponse(
        access_token=create_access_token(user.id),
        user=UserProfile.model_validate(user),
    )


@router.post("/login", response_model=AuthResponse)
def login(credentials: Credentials, session: Session = Depends(get_session)) -> AuthResponse:
    user = session.scalar(select(User).where(User.email == credentials.normalised_email()))

    # The same error whether the account is missing or the password is wrong,
    # so this endpoint cannot be used to discover which emails are registered.
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise INVALID_CREDENTIALS

    return AuthResponse(
        access_token=create_access_token(user.id),
        user=UserProfile.model_validate(user),
    )


@router.get("/me", response_model=UserProfile)
def me(user: User = Depends(current_user)) -> User:
    """Who the current token belongs to. Used by the UI to restore a session."""
    return user
