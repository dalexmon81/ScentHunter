"""GTIN check-digit validation for GTIN-8/12/13/14 identifiers."""
from __future__ import annotations

import re


def is_valid_gtin(value: str) -> bool:
    """Return True only for numeric GTIN-8/12/13/14 values with a valid GS1 check digit."""
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})", value):
        return False
    weighted_sum = 0
    weight = 3
    for digit in reversed(value[:-1]):
        weighted_sum += int(digit) * weight
        weight = 1 if weight == 3 else 3
    expected = (10 - weighted_sum % 10) % 10
    return expected == int(value[-1])
