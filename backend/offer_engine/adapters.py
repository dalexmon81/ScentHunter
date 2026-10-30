"""Independent retailer connector contract."""
from dataclasses import dataclass
from typing import Iterable, Protocol
from .contracts import RetailerListing, OfferObservation

@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    retailer: str
    ok: bool
    source: str
    message: str | None = None

class RetailerConnector(Protocol):
    retailer: str
    def discover(self, query: str) -> Iterable[RetailerListing]:
        """Return retailer listings without assigning canonical IDs."""
        ...
    def observe(self, listing: RetailerListing) -> OfferObservation:
        """Fetch one listing and return an immutable observation."""
        ...
    def healthcheck(self) -> ConnectorHealth:
        ...
