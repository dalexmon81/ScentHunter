from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.models import Base, UserAccount, UserSession
from app.api.accounts import (
    router, db_session, hash_password, verify_password,
    SESSION_COOKIE, CSRF_COOKIE, CSRF_HEADER,
)


def client_for_test():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[db_session] = override_session
    return TestClient(app, base_url="https://testserver.local"), engine, factory


def csrf_headers(client):
    token = client.cookies.get(CSRF_COOKIE)
    assert token
    return {"Origin": "https://testserver.local", CSRF_HEADER: token}


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("a-very-long-test-password")
    second = hash_password("a-very-long-test-password")
    assert first != second
    assert verify_password("a-very-long-test-password", first)
    assert not verify_password("wrong-password", first)


def test_register_issues_httponly_secure_cookie_and_persists_session():
    client, engine, factory = client_for_test()
    try:
        response = client.post("/account/register", headers={"Origin": "https://testserver.local"}, json={
            "email": " Buyer@Example.com ",
            "password": "a-very-long-test-password",
            "residence_country_code": "lu",
            "residence_postal_code": "L-1234",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["account"]["email"] == "buyer@example.com"
        assert data["account"]["residence_country_code"] == "LU"
        assert "access_token" not in data
        cookie = next(v for k, v in client.cookies.items() if k == SESSION_COOKIE)
        assert cookie
        set_cookie = response.headers.get_list("set-cookie")
        session_cookie = next(x for x in set_cookie if SESSION_COOKIE in x)
        assert "httponly" in session_cookie.lower()
        assert "secure" in session_cookie.lower()
        assert "samesite=lax" in session_cookie.lower()

        with factory() as session:
            user = session.scalar(select(UserAccount))
            saved = session.scalar(select(UserSession))
            assert user.password_hash != "a-very-long-test-password"
            assert saved.token_hash != cookie
            assert len(saved.token_hash) == 64

        assert client.get("/account/me").status_code == 200
        assert client.post("/account/logout", headers=csrf_headers(client)).status_code == 200
        assert client.get("/account/me").status_code == 401
        assert SESSION_COOKIE not in client.cookies
    finally:
        engine.dispose()


def test_login_sets_new_browser_session_and_logout_revokes_it():
    client, engine, _factory = client_for_test()
    try:
        client.post("/account/register", headers={"Origin": "https://testserver.local"}, json={
            "email": "owner@example.com",
            "password": "a-very-long-test-password",
            "residence_country_code": "LU",
        })
        client.post("/account/logout", headers=csrf_headers(client))
        login = client.post("/account/login", headers={"Origin": "https://testserver.local"}, json={
            "email": "OWNER@example.com",
            "password": "a-very-long-test-password",
        })
        assert login.status_code == 200
        assert login.json()["session_type"] == "http_only_cookie"
        assert client.get("/account/me").status_code == 200
        assert client.post("/account/logout", headers=csrf_headers(client)).status_code == 200
        assert client.get("/account/me").status_code == 401
    finally:
        engine.dispose()


def test_cookie_authenticated_mutations_require_csrf_and_same_origin():
    client, engine, _factory = client_for_test()
    try:
        client.post("/account/register", headers={"Origin": "https://testserver.local"}, json={
            "email": "csrf@example.com",
            "password": "a-very-long-test-password",
            "residence_country_code": "LU",
        })
        payload = {"label": "Casa", "country_code": "IT", "postal_code": "00100"}
        assert client.post("/account/destinations", json=payload).status_code == 403
        assert client.post(
            "/account/destinations", json=payload,
            headers={**csrf_headers(client), "Origin": "https://evil.example"},
        ).status_code == 403
        created = client.post("/account/destinations", json=payload, headers=csrf_headers(client))
        assert created.status_code == 201
    finally:
        engine.dispose()


def test_delivery_destination_is_owned_and_default_is_switchable():
    client, engine, _factory = client_for_test()
    try:
        client.post("/account/register", headers={"Origin": "https://testserver.local"}, json={
            "email": "owner@example.com",
            "password": "a-very-long-test-password",
            "residence_country_code": "LU",
        })
        headers = csrf_headers(client)
        created = client.post("/account/destinations", headers=headers, json={
            "label": "Regalo in Italia", "country_code": "it",
            "postal_code": "00100", "is_default": True,
        })
        assert created.status_code == 201
        destination = created.json()
        assert destination["country_code"] == "IT"
        assert destination["is_default"] is True
        assert client.put(
            "/account/destinations/" + destination["id"] + "/default",
            headers=csrf_headers(client),
        ).status_code == 200
        assert client.get("/account/me").json()["destinations"][0]["country_code"] == "IT"
    finally:
        engine.dispose()


def test_account_endpoints_require_authentication_and_validate_password_length():
    client, engine, _factory = client_for_test()
    try:
        assert client.get("/account/me").status_code == 401
        short = client.post("/account/register", headers={"Origin": "https://testserver.local"}, json={
            "email": "x@example.com", "password": "short", "residence_country_code": "LU",
        })
        assert short.status_code == 422
    finally:
        engine.dispose()


def test_account_session_factory_reuses_process_scoped_pool(monkeypatch):
    from app.api import accounts

    created = []
    sentinel_factory = object()

    def build_factory():
        created.append(True)
        return sentinel_factory

    accounts._account_session_factory.cache_clear()
    monkeypatch.setattr(accounts, "make_session_factory", build_factory)
    try:
        assert accounts._account_session_factory() is sentinel_factory
        assert accounts._account_session_factory() is sentinel_factory
        assert created == [True]
    finally:
        accounts._account_session_factory.cache_clear()
