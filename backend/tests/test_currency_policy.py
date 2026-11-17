from app.services.currency_policy import (
    SUPPORTED_CURRENCY_CODES,
    is_supported_currency_code,
)


def test_initial_supported_currency_policy_is_explicit_euro_only():
    assert SUPPORTED_CURRENCY_CODES == frozenset({"EUR"})
    assert is_supported_currency_code("EUR") is True


@pytest.mark.parametrize("value", ["USD", "GBP", "eur", " EUR", "EU", "EURO", "", None, 123])
def test_unenabled_or_noncanonical_currency_is_rejected(value):
    assert is_supported_currency_code(value) is False


