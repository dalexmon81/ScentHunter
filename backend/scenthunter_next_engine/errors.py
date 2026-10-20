from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class ErrorKind(str, Enum):
    TRANSIENT_NETWORK = "transient_network"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_SERVER = "upstream_server"
    ACCESS_DENIED = "access_denied"
    NOT_FOUND = "not_found"
    INVALID_DOCUMENT = "invalid_document"
    INVALID_PRODUCT = "invalid_product"
    INVALID_PRICE = "invalid_price"
    INVALID_CURRENCY = "invalid_currency"
    INVALID_URL = "invalid_url"
    PARSER_REGRESSION = "parser_regression"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AdapterFailure(Exception):
    kind: ErrorKind
    message: str
    retry_after_seconds: float | None = None

    def __str__(self) -> str:
        return f"{self.kind.value}: {self.message}"


RETRYABLE = {
    ErrorKind.TRANSIENT_NETWORK,
    ErrorKind.RATE_LIMITED,
    ErrorKind.UPSTREAM_SERVER,
}


def is_retryable(kind: ErrorKind) -> bool:
    return kind in RETRYABLE
