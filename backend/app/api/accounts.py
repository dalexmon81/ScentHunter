"""Account registration, login and saved delivery destinations."""
from __future__ import annotations
import hashlib, hmac, re, secrets, uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
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

def db_session():
    factory = make_session_factory()
    try:
        with factory() as session:
            yield session
    finally:
        factory.kw["bind"].dispose()

def new_session(session: Session, user: UserAccount) -> str:
    token = secrets.token_urlsafe(48)
    session.add(UserSession(user_id=user.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=now() + timedelta(days=SESSION_DAYS)))
    return token

def account_json(user):
    return {"id": str(user.id), "email": user.email,
        "residence_country_code": user.residence_country_code,
        "residence_postal_code": user.residence_postal_code}

def destination_json(row):
    return {"id": str(row.id), "label": row.label, "country_code": row.country_code,
        "postal_code": row.postal_code, "is_default": row.is_default}

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 session: Session = Depends(db_session)):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "authentication_required")
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    saved = session.scalar(select(UserSession).where(
        UserSession.token_hash == digest, UserSession.revoked_at.is_(None),
        UserSession.expires_at > now()))
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
        if not re.fullmatch(r"[^\\s@]+@[^\\s@]+\\.[^\\s@]+", value):
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
def register(body: RegisterBody, session: Session = Depends(db_session)):
    user = UserAccount(email=body.email, password_hash=hash_password(body.password),
        residence_country_code=body.residence_country_code,
        residence_postal_code=(body.residence_postal_code or "").strip() or None)
    session.add(user)
    try:
        session.flush()
        token = new_session(session, user)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "email_already_registered") from None
    return {"account": account_json(user), "access_token": token,
        "token_type": "bearer", "expires_in": SESSION_DAYS * 86400}

@router.post("/login")
def login(body: LoginBody, session: Session = Depends(db_session)):
    user = session.scalar(select(UserAccount).where(UserAccount.email == body.email.strip().lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid_email_or_password")
    token = new_session(session, user)
    session.commit()
    return {"account": account_json(user), "access_token": token,
        "token_type": "bearer", "expires_in": SESSION_DAYS * 86400}

@router.post("/logout")
def logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
           session: Session = Depends(db_session)):
    if credentials is None:
        raise HTTPException(401, "authentication_required")
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    saved = session.scalar(select(UserSession).where(
        UserSession.token_hash == digest, UserSession.revoked_at.is_(None)))
    if saved:
        saved.revoked_at = now()
        session.commit()
    return {"logged_out": True}

@router.get("/me")
def me(user: UserAccount = Depends(current_user), session: Session = Depends(db_session)):
    rows = session.scalars(select(UserDeliveryDestination).where(
        UserDeliveryDestination.user_id == user.id).order_by(
        UserDeliveryDestination.is_default.desc(), UserDeliveryDestination.created_at)).all()
    return {"account": account_json(user), "destinations": [destination_json(row) for row in rows]}

@router.get("/destinations")
def destinations(user: UserAccount = Depends(current_user), session: Session = Depends(db_session)):
    rows = session.scalars(select(UserDeliveryDestination).where(
        UserDeliveryDestination.user_id == user.id).order_by(
        UserDeliveryDestination.is_default.desc(), UserDeliveryDestination.created_at)).all()
    return {"destinations": [destination_json(row) for row in rows]}

@router.post("/destinations", status_code=201)
def add_destination(body: DestinationBody, user: UserAccount = Depends(current_user),
                    session: Session = Depends(db_session)):
    if body.is_default:
        session.query(UserDeliveryDestination).filter(
            UserDeliveryDestination.user_id == user.id).update(
            {UserDeliveryDestination.is_default: False}, synchronize_session=False)
    row = UserDeliveryDestination(user_id=user.id, label=body.label,
        country_code=body.country_code, postal_code=(body.postal_code or "").strip() or None,
        is_default=body.is_default)
    session.add(row)
    session.commit()
    session.refresh(row)
    return destination_json(row)

@router.put("/destinations/{destination_id}/default")
def set_default(destination_id: uuid.UUID, user: UserAccount = Depends(current_user),
                session: Session = Depends(db_session)):
    row = session.scalar(select(UserDeliveryDestination).where(
        UserDeliveryDestination.id == destination_id,
        UserDeliveryDestination.user_id == user.id))
    if row is None:
        raise HTTPException(404, "destination_not_found")
    session.query(UserDeliveryDestination).filter(
        UserDeliveryDestination.user_id == user.id).update(
        {UserDeliveryDestination.is_default: False}, synchronize_session=False)
    row.is_default = True
    session.commit()
    session.refresh(row)
    return destination_json(row)

@router.delete("/destinations/{destination_id}")
def delete_destination(destination_id: uuid.UUID, user: UserAccount = Depends(current_user),
                       session: Session = Depends(db_session)):
    row = session.scalar(select(UserDeliveryDestination).where(
        UserDeliveryDestination.id == destination_id,
        UserDeliveryDestination.user_id == user.id))
    if row is None:
        raise HTTPException(404, "destination_not_found")
    session.delete(row)
    session.commit()
    return {"deleted": True}
