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
