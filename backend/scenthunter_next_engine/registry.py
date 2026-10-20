"""Explicit retailer adapter registry with no import-time network effects."""
from __future__ import annotations
from threading import RLock
from .adapter import RetailerAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._adapters: dict[str, RetailerAdapter] = {}

    def register(self, adapter: RetailerAdapter, *, replace: bool = False) -> None:
        key = str(getattr(adapter, "store_key", "") or "").strip().casefold()
        if not key:
            raise ValueError("adapter.store_key is required")
        if not callable(getattr(adapter, "discover", None)) or not callable(getattr(adapter, "fetch", None)) or not callable(getattr(adapter, "parse", None)):
            raise TypeError("adapter must implement discover, fetch and parse")
        with self._lock:
            if key in self._adapters and not replace:
                raise ValueError(f"adapter already registered for store {key}")
            self._adapters[key] = adapter

    def get(self, store_key: str) -> RetailerAdapter:
        key = str(store_key or "").strip().casefold()
        with self._lock:
            try:
                return self._adapters[key]
            except KeyError:
                raise KeyError(f"no adapter registered for store {key!r}") from None

    def stores(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._adapters))

    def unregister(self, store_key: str) -> bool:
        key = str(store_key or "").strip().casefold()
        with self._lock:
            return self._adapters.pop(key, None) is not None


registry = AdapterRegistry()
