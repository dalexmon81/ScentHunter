from pathlib import Path


def test_frontend_requires_and_sends_a_delivery_destination():
    root = Path(__file__).resolve().parents[2]
    source = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'id="deliveryCountry"' in source
    assert 'id="deliveryPostalCode"' in source
    assert "Seleziona il Paese di consegna" in source
    assert 'params.set("country_code",country)' in source
    assert 'params.set("postal_code",postal)' in source
    assert "TOTALE CONSEGNATO" in source
    assert "SPEDIZIONE NON DISPONIBILE" in source
    assert "delivered_total_verified" in source


def test_frontend_account_profile_connects_auth_and_saved_destinations():
    root = Path(__file__).resolve().parents[2]
    source = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'id="profileView"' in source
    assert 'data-view="profile"' in source
    assert 'id="profileEmail"' in source
    assert 'id="profileResidence"' in source
    assert 'id="profileAddDestination"' in source
    assert 'id="profileLogout"' in source
    assert 'profileApi(profileRegisterMode?"/account/register":"/account/login"' in source
    assert 'profileApi("/account/me")' in source
    assert 'profileApi("/account/destinations"' in source
    assert 'data-profile-default' in source
    assert 'data-profile-delete' in source
    assert 'scentHunterAccessToken=""' in source


def test_signed_in_search_uses_default_destination_then_residence_fallback():
    root = Path(__file__).resolve().parents[2]
    source = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'destinations.find(d=>d.is_default)' in source
    assert 'preferred?.country_code||a.residence_country_code' in source
    assert 'preferred?.postal_code||a.residence_postal_code' in source
    assert 'if(deliveryCountry&&!deliveryCountry.value)' in source
