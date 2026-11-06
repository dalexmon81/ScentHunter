"""Small fail-safe parsers shared by legacy API and ingestion code."""


def safe_float(value):
    """Return a float for parseable values, otherwise None."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
