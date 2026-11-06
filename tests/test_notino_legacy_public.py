"""The legacy Notino public-discovery entry points must remain disabled."""

from backend.scrapers.notino import legacy_public


def test_legacy_public_search_never_starts_external_discovery(monkeypatch):
    monkeypatch.setattr(
        legacy_public,
        "_discover",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy Notino public discovery must not run")
        ),
    )
    assert legacy_public.search("Dior Sauvage") == []


def test_legacy_public_discovery_is_disabled_without_network(monkeypatch):
    monkeypatch.setattr(
        legacy_public,
        "_bing_rss",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("external RSS request must not run")
        ),
    )
    monkeypatch.setattr(
        legacy_public,
        "_browser_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("public browser search must not run")
        ),
    )
    candidates, report = legacy_public._discover("Dior Sauvage")

    assert candidates == []
    assert report["status"] == "disabled"
    assert report["source"] == "cj_viv_authorized_xml"
    assert report["error"] == "notino_public_html_disabled"


def test_legacy_public_diagnostic_is_disabled_without_network():
    report = legacy_public.diagnose("Dior Sauvage")

    assert report["diagnostic"] is True
    assert report["candidate_count"] == 0
    assert report["discovery"]["status"] == "disabled"
    assert report["discovery"]["error"] == "notino_public_html_disabled"
