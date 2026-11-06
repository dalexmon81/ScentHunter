"""Explicit currency support policy for enabled catalog markets.

Only EUR is enabled initially: the first supported launch markets are
Luxembourg, Belgium, France, Germany, Italy and the Netherlands. Adding a
currency requires an explicit market/FX policy review; a three-letter shape
check alone is not sufficient for publication.
"""

SUPPORTED_CURRENCY_CODES = frozenset({"EUR"})


def is_supported_currency_code(value: object) -> bool:
    """Return True only for an explicitly enabled, canonical currency code."""
    return isinstance(value, str) and value == value.strip().upper() and value in SUPPORTED_CURRENCY_CODES
