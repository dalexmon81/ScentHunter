"""Account registration, secure browser sessions and saved delivery destinations."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import make_session_factory
from app.models import UserAccount, UserDeliveryDestination, UserSession

router = APIRouter(prefix="/account", tags=["account"])
bearer = HTTPBearer(auto_error=False)
ITERATIONS = 600_000
SESSION_DAYS = 30
SESSION_COOKIE = "__Host-scenthunter_session"
CSRF_COOKIE = "__Host-scenthunter_csrf"
CSRF_HEADER = "x-csrf-token"


def now():
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256" + "$" + str(ITERATIONS) + "$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt, expected = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def _account_session_factory():
    """Reuse one process-scoped SQLAlchemy engine/pool for account requests."""
    return make_session_factory()


def db_session():
    with _account_session_factory()() as session:
        yield session


def new_session(session: Session, user: UserAccount) -> str:
    token = secrets.token_urlsafe(48)
    session.add(UserSession(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=now() + timedelta(days=SESSION_DAYS),
    ))
    return token


def set_browser_session(response: Response, token: str) -> None:
    csrf_token = secrets.token_urlsafe(32)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    max_age = SESSION_DAYS * 86400
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True,
        secure=True, samesite="lax", path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, max_age=max_age, httponly=False,
        secure=True, samesite="lax", path="/",
    )


def clear_browser_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, httponly=False, samesite="lax")


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(403, "csrf_origin_required")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if not hmac.compare_digest(origin.rstrip("/"), expected.rstrip("/")):
        raise HTTPException(403, "csrf_origin_mismatch")


def require_csrf(request: Request, csrf_cookie: str | None, csrf_header: str | None) -> None:
    require_same_origin(request)
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(403, "csrf_token_invalid")


def account_json(user):
    return {
        "id": str(user.id), "email": user.email,
        "residence_country_code": user.residence_country_code,
        "residence_postal_code": user.residence_postal_code,
    }


def destination_json(row):
    return {
        "id": str(row.id), "label": row.label, "country_code": row.country_code,
        "postal_code": row.postal_code, "is_default": row.is_default,
    }


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    browser_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias=CSRF_HEADER),
    session: Session = Depends(db_session),
):
    token = None
    cookie_auth = False
    if browser_token:
        token = browser_token
        cookie_auth = True
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            require_csrf(request, csrf_cookie, csrf_header)
    elif credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    if not token:
        raise HTTPException(401, "authentication_required")

    digest = hashlib.sha256(token.encode()).hexdigest()
    saved = session.scalar(select(UserSession).where(
        UserSession.token_hash == digest,
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > now(),
    ))
    if saved is None:
        raise HTTPException(401, "invalid_or_expired_session")
    user = session.get(UserAccount, saved.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "account_unavailable")
    saved.last_used_at = now()
    session.commit()
    return user


class RegisterBody(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    residence_country_code: str = Field(min_length=2, max_length=2)
    residence_postal_code: str | None = Field(default=None, max_length=24)

    @field_validator("email")
    @classmethod
    def email_normalized(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("invalid_email")
        return value

    @field_validator("residence_country_code")
    @classmethod
    def country_normalized(cls, value):
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha():
            raise ValueError("invalid_country_code")
        return value


class LoginBody(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class DestinationBody(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    country_code: str = Field(min_length=2, max_length=2)
    postal_code: str | None = Field(default=None, max_length=24)
    is_default: bool = False

    @field_validator("country_code")
    @classmethod
    def country_normalized(cls, value):
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha():
            raise ValueError("invalid_country_code")
        return value

    @field_validator("label")
    @classmethod
    def label_normalized(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("destination_label_required")
        return value


@router.post("/register", status_code=201)
def register(body: RegisterBody, request: Request, response: Response, session: Session = Depends(db_session)):
    require_same_origin(request)
    user = UserAccount(
        email=body.email,
        password_hash=hash_password(body.password),
        residence_country_code=body.residence_country_code,
        residence_postal_code=(body.residence_postal_code or "").strip() or None,
    )
    session.add(user)
    try:
        session.flush()
        token = new_session(session, user)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "email_already_registered") from None
    set_browser_session(response, token)
    return {"account": account_json(user), "expires_in": SESSION_DAYS * 86400, "session_type": "http_only_cookie"}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, session: Session = Depends(db_session)):
    require_same_origin(request)
    user = session.scalar(select(UserAccount).where(UserAccount.email == body.email.strip().lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid_email_or_password")
    token = new_session(session, user)
    session.commit()
    set_browser_session(response, token)
    return {"account": account_json(user), "expires_in": SESSION_DAYS * 86400, "session_type": "http_only_cookie"}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    browser_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias=CSRF_HEADER),
    session: Session = Depends(db_session),
):
    token = browser_token or (credentials.credentials if credentials is not None else None)
    if not token:
        raise HTTPException(401, "authentication_required")
    if browser_token:
        require_csrf(request, csrf_cookie, csrf_header)
    digest = hashlib.sha256(token.encode()).hexdigest()
    saved = session.scalar(select(UserSession).where(
        UserSession.token_hash == digest, UserSession.revoked_at.is_(None)
    ))
    if saved:
        saved.revoked_at = now()
        session.commit()
    clear_browser_session(response)
    return {"logged_out": True}


@router.get("/me")
def me(user: UserAccount = Depends(current_user), session: Session = Depends(db_session)):
    rows = session.scalars(select(UserDeliveryDestination).where(
        UserDeliveryDestination.user_id == user.id
    ).order_by(UserDeliveryDestination.is_default.desc(), UserDeliveryDestination.created_at)).all()
    return {"account": account_json(user), "destinations": [destination_json(row) for row in rows]}


@router.get("/destinations")
def destinations(user: UserAccount = Depends(current_user), session: Session = Depends(db_session)):
    rows = session.scalars(select(UserDeliveryDestination).where(
        UserDeliveryDestination.user_id == user.id
    ).order_by(UserDeliveryDestination.is_default.desc(), UserDeliveryDestination.created_at)).all()
    return {"destinations": [destination_json(row) for row in rows]}


@router.post("/destinations", status_code=201)
def add_destination(body: DestinationBody, user: UserAccount = Depends(current_user),
                    session: Session = Depends(db_session)):
    if body.is_default:
        session.query(UserDeliveryDestination).filter(
            UserDeliveryDestination.user_id == user.id
        ).update({UserDeliveryDestination.is_default: False}, synchronize_session=False)
    row = UserDeliveryDestination(
        user_id=user.id, label=body.label, country_code=body.country_code,
        postal_code=(body.postal_code or "").strip() or None, is_default=body.is_default,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return destination_json(row)


@router.put("/destinations/{destination_id}/default")
def set_default(destination_id: uuid.UUID, user: UserAccount = Depends(current_user),
                session: Session = Depends(db_session)):
    row = session.scalar(select(UserDeliveryDestination).where(
        UserDeliveryDestination.id == destination_id, UserDeliveryDestination.user_id == user.id
    ))
    if row is None:
        raise HTTPException(404, "destination_not_found")
    session.query(UserDeliveryDestination).filter(
        UserDeliveryDestination.user_id == user.id
    ).update({UserDeliveryDestination.is_default: False}, synchronize_session=False)
    row.is_default = True
    session.commit()
    session.refresh(row)
    return destination_json(row)


@router.delete("/destinations/{destination_id}")
def delete_destination(destination_id: uuid.UUID, user: UserAccount = Depends(current_user),
                       session: Session = Depends(db_session)):
    row = session.scalar(select(UserDeliveryDestination).where(
        UserDeliveryDestination.id == destination_id, UserDeliveryDestination.user_id == user.id
    ))
    if row is None:
        raise HTTPException(404, "destination_not_found")
    session.delete(row)
    session.commit()
    return {"deleted": True}
