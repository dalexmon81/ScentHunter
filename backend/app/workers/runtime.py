"""Explicit handler registry for isolated worker bootstrap."""
from __future__ import annotations
from collections.abc import Callable, Mapping
from threading import RLock
from typing import Any
_HANDLERS: dict[str, Callable[[Mapping[str, Any]], Any]] = {}
_LOCK = RLock()
_ALLOWED = {"discover", "fetch", "normalize", "match", "validate", "refresh", "quarantine", "reprocess"}
def register_handler(stage: str, handler: Callable[[Mapping[str, Any]], Any]) -> None:
    if stage not in _ALLOWED:
        raise ValueError(f"unsupported worker stage: {stage}")
    if not callable(handler):
        raise TypeError("handler must be callable")
    with _LOCK:
        _HANDLERS[stage] = handler
def get_handler(stage: str):
    with _LOCK:
        return _HANDLERS.get(stage)
def clear_handlers() -> None:
    with _LOCK:
        _HANDLERS.clear()
