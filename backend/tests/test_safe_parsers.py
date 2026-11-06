import math

import pytest

from app.services.safe_parsers import safe_float


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("not-a-number", None),
        ([], None),
        ("12.5", 12.5),
        (7, 7.0),
        ("-0.25", -0.25),
    ],
)
def test_safe_float_preserves_legacy_parse_behavior(value, expected):
    assert safe_float(value) == expected


def test_safe_float_keeps_python_float_special_values():
    assert math.isnan(safe_float("nan"))
    assert safe_float("inf") == float("inf")
