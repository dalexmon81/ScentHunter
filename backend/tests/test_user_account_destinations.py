from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Base, UserAccount, UserDeliveryDestination


def test_account_stores_hash_and_residence_separately_from_delivery_destination():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        account = UserAccount(
            email="piero@example.test",
            password_hash="$argon2id$test-hash-only",
            residence_country_code="LU",
            residence_postal_code="1234",
        )
        session.add(account)
        session.flush()
        destination = UserDeliveryDestination(
            user_id=account.id,
            label="Gift in Italy",
            country_code="IT",
            postal_code="00100",
            is_default=True,
        )
        session.add(destination)
        session.commit()

        assert account.password_hash.startswith("$argon2id$")
        assert account.residence_country_code == "LU"
        assert destination.country_code == "IT"
        assert destination.postal_code == "00100"


def test_only_one_default_delivery_destination_per_account():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        account = UserAccount(
            email="buyer@example.test",
            password_hash="hashed",
            residence_country_code="LU",
        )
        session.add(account)
        session.flush()
        session.add_all([
            UserDeliveryDestination(user_id=account.id, label="Home", country_code="LU", is_default=True),
            UserDeliveryDestination(user_id=account.id, label="Gift", country_code="IT", is_default=True),
        ])
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("database must reject two default destinations")
    engine.dispose()


def test_account_schema_does_not_store_plaintext_password_column():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("user_accounts")}
    assert "password_hash" in columns
    assert "password" not in columns
    engine.dispose()
