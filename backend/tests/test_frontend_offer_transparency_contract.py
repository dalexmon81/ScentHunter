"""Static frontend contract tests for transparent catalog offer ranking."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "index.html"


def test_offer_cards_disclose_unknown_shipping_and_stale_prices():
    source = FRONTEND.read_text(encoding="utf-8")

    assert "function shOfferMetaHtml(o)" in source
    assert "o.ranking.shipping_cost_known===false" in source
    assert "SPEDIZIONE NON NOTA" in source
    assert "PREZZO NON CONFRONTABILE A PARITÀ DI SPEDIZIONE" in source
    assert "SPEDIZIONE INCLUSA NEL CONFRONTO" in source
    assert "o.ranking.stale" in source
    assert "PREZZO DA VERIFICARE" in source
    assert "${shOfferMetaHtml(o)" in source


def test_unknown_shipping_is_not_labeled_as_a_best_delivered_price():
    source = FRONTEND.read_text(encoding="utf-8")

    assert "shipping_cost_known===false" in source
    assert "price_comparable===true" in source
    assert "SPEDIZIONE NON CONFRONTABILE" in source
