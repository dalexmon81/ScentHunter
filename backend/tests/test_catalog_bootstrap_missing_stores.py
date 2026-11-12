"""Partial persistent catalogs must bootstrap every missing retailer."""

import main


def test_partial_catalog_starts_immediate_discovery_for_missing_stores(monkeypatch):
    monkeypatch.setenv("CATALOG_BACKGROUND_WORKERS_ENABLED", "1")
    monkeypatch.setattr(main, "_CATALOG_BOOTSTRAP_STARTED", False)
    monkeypatch.setattr(main, "_catalog_is_ready", lambda: True)
    missing = ["parfumzentrum", "sabina", "easycosmetic"]
    monkeypatch.setattr(main, "_stores_missing_catalog", lambda: list(missing))

    started = []
    monkeypatch.setattr(main, "_start_catalog_hydration", lambda: started.append("hydration"))
    monkeypatch.setattr(main, "_start_catalog_discovery", lambda: started.append("discovery"))

    class FakeThread:
        def __init__(self, *, target, args=(), kwargs=None, daemon=None, name=None):
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = daemon
            self.name = name

        def start(self):
            started.append({
                "target": self.target,
                "args": self.args,
                "name": self.name,
                "daemon": self.daemon,
            })

    monkeypatch.setattr(main.threading, "Thread", FakeThread)

    main._start_catalog_bootstrap()

    assert started[:2] == ["hydration", "discovery"]
    assert started[2] == {
        "target": main._discover_missing_catalog_stores,
        "args": (tuple(missing),),
        "name": "scenthunter-missing-store-bootstrap",
        "daemon": True,
    }
