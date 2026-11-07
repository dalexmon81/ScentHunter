from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.models import Base, UserAccount, UserSession
from app.api.accounts import router, db_session, hash_password, verify_password
from fastapi import FastAPI


def client_for_test():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[db_session] = override_session
    return TestClient(app), engine, factory


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("a-very-long-test-password")
    second = hash_password("a-very-long-test-password")
    assert first != second
    assert verify_password("a-very-long-test-password", first)
    assert not verify_password("wrong-password", first)


def test_register_login_and_logout_revoke_opaque_session():
    client, engine, factory = client_for_test()
    try:
        response = client.post("/account/register", json={
            "email": " Buyer@Example.com ",
            "password": "a-very-long-test-password",
            "residence_country_code": "lu",
            "residence_postal_code": "L-1234",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["account"]["email"] == "buyer@example.com"
        assert data["account"]["residence_country_code"] == "LU"
        token = data["access_token"]

        with factory() as session:
            user = session.scalar(select(UserAccount))
            saved = session.scalar(select(UserSession))
            assert user.password_hash != "a-very-long-test-password"
            assert token not in saved.token_hash

        assert client.get("/account/me", headers={"Authorization": "Bearer " + token}).status_code == 200
        login = client.post("/account/login", json={
            "email": "BUYER@example.com",
            "password": "a-very-long-test-password",
        })
        assert login.status_code == 200
        login_token = login.json()["access_token"]
        assert client.post("/account/logout", headers={"Authorization": "Bearer " + login_token}).status_code == 200
        assert client.get("/account/me", headers={"Authorization": "Bearer " + login_token}).status_code == 401
    finally:
        engine.dispose()


def test_delivery_destination_is_owned_and_default_is_switchable():
    client, engine, _factory = client_for_test()
    try:
        register = client.post("/account/register", json={
            "email": "owner@example.com",
            "password": "a-very-long-test-password",
            "residence_country_code": "LU",
        })
        token = register.json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        created = client.post("/account/destinations", headers=headers, json={
            "label": "Regalo in Italia",
            "country_code": "it",
            "postal_code": "00100",
            "is_default": True,
        })
        assert created.status_code == 201
        destination = created.json()
        assert destination["country_code"] == "IT"
        assert destination["is_default"] is True
        assert client.put("/account/destinations/" + destination["id"] + "/default",
                          headers=headers).status_code == 200
        assert client.get("/account/me", headers=headers).json()["destinations"][0]["country_code"] == "IT"
    finally:
        engine.dispose()


def test_account_endpoints_require_authentication_and_validate_password_length():
    client, engine, _factory = client_for_test()
    try:
        assert client.get("/account/me").status_code == 401
        short = client.post("/account/register", json={
            "email": "x@example.com", "password": "short",
            "residence_country_code": "LU",
        })
        assert short.status_code == 422
    finally:
        engine.dispose()
