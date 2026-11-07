from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, select


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SEED = BACKEND / "scripts" / "seed_catalog.py"


def sample_catalog() -> dict:
    return {
        "brands": [{"brand_id": "B1", "brand_name": "Test Brand"}],
        "products": [
            {
                "product_id": "P1",
                "brand_name": "Test Brand",
                "canonical_name": "Known Variant",
                "concentration": "EDP",
            },
            {
                "product_id": "P2",
                "brand_name": "Test Brand",
                "canonical_name": "Identity Only",
            },
        ],
        "variants": [
            {
                "variant_id": "V1",
                "product_id": "P1",
                "size_ml": 50,
            }
        ],
        "offers": [],
    }


def run_seed(catalog_path: Path, database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
    env.pop("SCENTHUNTER_DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, str(SEED), "--catalog", str(catalog_path), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_seed_dry_run_keeps_products_without_inventing_variants(tmp_path):
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(sample_catalog()), encoding="utf-8")
    result = run_seed(catalog_path, f"sqlite:///{tmp_path / 'unused.sqlite3'}", "--seed-bplatz-store")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "validated"
    assert report["stores_to_seed"] == [{
        "name": "Bplatz", "slug": "bplatz", "domain": "bplatz.de",
        "country": "DE", "currency": "EUR", "status": "active",
    }]
    assert report["brands"] == 1
    assert report["fragrances"] == 2
    assert report["variants"] == 1
    assert report["products_without_variants"] == 1
    assert report["offers_imported"] == 0
    assert report["database_written"] is False
    assert not (tmp_path / "unused.sqlite3").exists()


def test_seed_apply_imports_identity_without_creating_variant_or_offer(tmp_path):
    catalog_path = tmp_path / "catalog.json"
    database_path = tmp_path / "catalog.sqlite3"
    catalog_path.write_text(json.dumps(sample_catalog()), encoding="utf-8")
    database_url = f"sqlite:///{database_path}"
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
    env.pop("SCENTHUNTER_DATABASE_URL", None)

    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migration.returncode == 0, migration.stderr

    result = run_seed(catalog_path, database_url, "--apply")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "seeded"
    assert report["database_written"] is True
    assert report["database_counts"]["brands"] == 1
    assert report["database_counts"]["fragrances"] == 2
    assert report["database_counts"]["product_variants"] == 1
    assert report["database_counts"]["legacy_product_id_map"] == 2
    assert report["database_counts"]["legacy_variant_id_map"] == 1
    assert report["database_counts"]["offers"] == 0

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT fragrance_id FROM legacy_product_id_map WHERE legacy_product_id='P1'"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT product_variant_id FROM legacy_variant_id_map WHERE legacy_variant_id='V1'"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_product_id_map"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM fragrances f "
            "LEFT JOIN product_variants v ON v.fragrance_id = f.id "
            "WHERE v.id IS NULL"
        ).fetchone()[0] == 1


def test_seed_blocks_orphan_variant_without_writing_database(tmp_path):
    catalog = sample_catalog()
    catalog["variants"].append({
        "variant_id": "ORPHAN",
        "product_id": "MISSING",
        "size_ml": 100,
    })
    catalog_path = tmp_path / "catalog.json"
    database_path = tmp_path / "catalog.sqlite3"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    result = run_seed(catalog_path, f"sqlite:///{database_path}")

    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["status"] == "blocked"
    assert report["database_written"] is False
    assert not database_path.exists()


def test_real_source_catalog_dry_run_reports_unmatched_variant_count():
    result = run_seed(
        BACKEND / "product_catalog.json",
        "sqlite:///:memory:",
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "validated"
    assert report["source_brand_records"] == 0
    assert report["brands"] == 21
    assert report["fragrances"] == 1628
    assert report["variants"] == 149
    assert report["products_without_variants"] == 1477
    assert report["offers_imported"] == 0
    assert report["database_written"] is False


def test_real_catalog_seed_populates_every_legacy_map_and_is_idempotent(tmp_path):
    import sys

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    sys.path.insert(0, str(BACKEND))
    from app.models import LegacyProductIdMap, LegacyVariantIdMap
    from app.services.ingestion_persistence import resolve_legacy_ids

    catalog_path = BACKEND / "product_catalog.json"
    raw_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    products = raw_catalog["products"]
    variants = raw_catalog["variants"]
    database_path = tmp_path / "full-catalog.sqlite3"
    database_url = f"sqlite:///{database_path}"
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
    env.pop("SCENTHUNTER_DATABASE_URL", None)

    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True, check=False,
    )
    assert migration.returncode == 0, migration.stderr

    first = run_seed(catalog_path, database_url, "--apply")
    assert first.returncode == 0, first.stderr
    first_report = json.loads(first.stdout)
    assert first_report["status"] == "seeded"
    assert first_report["database_counts"]["legacy_product_id_map"] == len(products)
    assert first_report["database_counts"]["product_variants"] == len(variants)
    assert first_report["database_counts"]["legacy_variant_id_map"] == len(variants)

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            product_ids = set(session.scalars(select(LegacyProductIdMap.legacy_product_id)))
            variant_ids = set(session.scalars(select(LegacyVariantIdMap.legacy_variant_id)))
            assert product_ids == {str(row["product_id"]) for row in products}
            assert variant_ids == {str(row["variant_id"]) for row in variants}

            # Every product ID has a persisted fragrance UUID, including products
            # that intentionally have no declared variant.
            for legacy_product_id in product_ids:
                mapping = session.get(LegacyProductIdMap, legacy_product_id)
                assert mapping is not None and mapping.fragrance_id is not None

            # Every variant resolves together with its owning historical product ID.
            for variant in variants:
                resolved = resolve_legacy_ids(
                    session,
                    legacy_product_id=str(variant["product_id"]),
                    legacy_variant_id=str(variant["variant_id"]),
                )
                assert resolved is not None, (
                    f"unresolved legacy IDs: {variant['product_id']} / {variant['variant_id']}"
                )

            first_product_id = str(products[0]["product_id"])
            missing_variant_id = "LEGACY-VARIANT-ID-DOES-NOT-EXIST"
            resolved_missing = resolve_legacy_ids(
                session,
                legacy_product_id=first_product_id,
                legacy_variant_id=missing_variant_id,
            )
            assert resolved_missing is None

        # Re-running the seed must be a no-op for both mapping tables.
        second = run_seed(catalog_path, database_url, "--apply")
        assert second.returncode == 0, second.stderr
        second_report = json.loads(second.stdout)
        assert second_report["database_counts"]["legacy_product_id_map"] == len(products)
        assert second_report["database_counts"]["legacy_variant_id_map"] == len(variants)

        # Re-running the migration must preserve all rows and the target revision.
        migration_again = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0002_ingestion_raw"],
            cwd=BACKEND, env=env, capture_output=True, text=True, check=False,
        )
        assert migration_again.returncode == 0, migration_again.stderr
        with Session(engine) as session:
            assert session.scalar(select(LegacyProductIdMap.legacy_product_id).limit(1))
            assert session.scalar(select(LegacyVariantIdMap.legacy_variant_id).limit(1))
            assert len(list(session.scalars(select(LegacyProductIdMap)))) == len(products)
            assert len(list(session.scalars(select(LegacyVariantIdMap)))) == len(variants)
    finally:
        engine.dispose()



def test_bplatz_store_seed_is_idempotent_and_leaves_other_eight_stores_untouched(tmp_path):
    from sqlalchemy.orm import Session

    sys.path.insert(0, str(BACKEND))
    from app.models import Store

    catalog_path = BACKEND / "product_catalog.json"
    database_path = tmp_path / "stores-idempotency.sqlite3"
    database_url = f"sqlite:///{database_path}"
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
    env.pop("SCENTHUNTER_DATABASE_URL", None)

    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True, check=False,
    )
    assert migration.returncode == 0, migration.stderr

    other_stores = [
        ("deloox", "Deloox", "deloox.example", "NL", "EUR", "inactive"),
        ("parfumcity", "Parfumcity", "parfumcity.example", "DE", "EUR", "inactive"),
        ("parfumzentrum", "Parfumzentrum", "parfumzentrum.example", "DE", "EUR", "inactive"),
        ("perfumemarket", "Perfumemarket", "perfumemarket.example", "IT", "EUR", "inactive"),
        ("sabina", "Sabina", "sabina.example", "ES", "EUR", "inactive"),
        ("orioudh", "Orioudh", "orioudh.example", "FR", "EUR", "inactive"),
        ("easycosmetic", "Easycosmetic", "easycosmetic.example", "DE", "EUR", "inactive"),
        ("notino", "Notino", "notino.example", "CZ", "EUR", "inactive"),
    ]
    engine = create_engine(database_url)
    try:
        with Session(engine) as session, session.begin():
            for slug, name, domain, country, currency, status in other_stores:
                session.add(Store(
                    name=name, slug=slug, domain=domain, country=country,
                    currency=currency, status=status,
                ))
        with Session(engine) as session:
            before = {
                row.slug: (row.name, row.domain, row.country, row.currency, row.status)
                for row in session.scalars(select(Store)).all()
            }
        assert set(before) == {row[0] for row in other_stores}

        first = run_seed(catalog_path, database_url, "--apply", "--seed-bplatz-store")
        assert first.returncode == 0, first.stderr
        second = run_seed(catalog_path, database_url, "--apply", "--seed-bplatz-store")
        assert second.returncode == 0, second.stderr

        with Session(engine) as session:
            rows = session.scalars(select(Store)).all()
            by_slug = {row.slug: row for row in rows}
            assert len(rows) == 9
            assert set(by_slug) == set(before) | {"bplatz"}
            for slug, expected in before.items():
                row = by_slug[slug]
                assert (row.name, row.domain, row.country, row.currency, row.status) == expected
            bplatz = by_slug["bplatz"]
            assert (bplatz.name, bplatz.domain, bplatz.country, bplatz.currency, bplatz.status) == (
                "Bplatz", "bplatz.de", "DE", "EUR", "active",
            )
    finally:
        engine.dispose()



def test_seed_consolidates_duplicate_canonical_names_and_preserves_all_legacy_ids(tmp_path):
    """Punctuation/accent duplicates map to one fragrance without losing package variants."""
    catalog = {
        "brands": [],
        "products": [
            {"product_id": "AFNAN-9AM-A", "brand_name": "Afnan", "canonical_name": "9 AM Pour Femme"},
            {"product_id": "AFNAN-9AM-B", "brand_name": "Afnan", "canonical_name": "9 AM - Pour Femme"},
            {"product_id": "AFNAN-9PM-A", "brand_name": "Afnan", "canonical_name": "9 PM Pour Femme"},
            {"product_id": "AFNAN-9PM-B", "brand_name": "Afnan", "canonical_name": "9 PM - Pour Femme"},
            {"product_id": "ARMANI-PROFONDO-A", "brand_name": "Giorgio Armani", "canonical_name": "Acqua di Gio Profondo"},
            {"product_id": "ARMANI-PROFONDO-B", "brand_name": "Giorgio Armani", "canonical_name": "Acqua di Giò Profondo"},
        ],
        "variants": [
            {"variant_id": "PROFONDO-75", "product_id": "ARMANI-PROFONDO-A", "size_ml": 75, "concentration": "Eau de Parfum"},
            {"variant_id": "PROFONDO-125", "product_id": "ARMANI-PROFONDO-A", "size_ml": 125, "concentration": "Eau de Parfum"},
            {"variant_id": "PROFONDO-100-REFILL", "product_id": "ARMANI-PROFONDO-B", "size_ml": 100, "concentration": "Eau de Parfum", "is_refill": True},
        ],
        "offers": [],
    }
    catalog_path = tmp_path / "duplicate-identities.json"
    database_path = tmp_path / "duplicate-identities.sqlite3"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    database_url = f"sqlite:///{database_path}"
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
    env.pop("SCENTHUNTER_DATABASE_URL", None)

    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True, check=False,
    )
    assert migration.returncode == 0, migration.stderr

    result = run_seed(catalog_path, database_url, "--apply")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "seeded"
    assert report["database_counts"]["fragrances"] == 3
    assert report["database_counts"]["legacy_product_id_map"] == 6
    assert report["database_counts"]["product_variants"] == 3
    assert report["database_counts"]["legacy_variant_id_map"] == 3
    assert report["database_counts"]["offers"] == 0

    with sqlite3.connect(database_path) as connection:
        mapped = dict(connection.execute(
            "SELECT legacy_product_id, fragrance_id FROM legacy_product_id_map"
        ).fetchall())
        assert mapped["AFNAN-9AM-A"] == mapped["AFNAN-9AM-B"]
        assert mapped["AFNAN-9PM-A"] == mapped["AFNAN-9PM-B"]
        assert mapped["ARMANI-PROFONDO-A"] == mapped["ARMANI-PROFONDO-B"]

        variant_rows = connection.execute(
            "SELECT v.size_ml, v.is_refill, v.fragrance_id "
            "FROM product_variants v ORDER BY v.size_ml"
        ).fetchall()
        assert [(row[0], row[1]) for row in variant_rows] == [(75, None), (100, 1), (125, None)]
        assert {row[2] for row in variant_rows} == {mapped["ARMANI-PROFONDO-A"]}



def test_real_catalog_requested_brands_are_present_and_variants_are_traceable():
    """Guard against dropping requested perfume houses during catalog expansion."""
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products, variants = raw["products"], raw["variants"]
    requested = {
        "Velixir", "Mykonos", "Maison Asrar", "Khadlaj", "Bujairami",
        "Paris Corner", "Assaf", "Al Wataniah", "Armaf", "French Avenue",
        "Arabiyat Prestige", "Gulf Orchid", "Swiss Arabian", "Games of Spades",
        "Lattafa", "Afnan", "Aromatix", "Maison Alhambra", "Zimaya",
        "Al Haramain",
    }
    brands = {row["brand_name"] for row in products}
    assert requested <= brands
    assert len(products) == 1628
    assert len(variants) == 151
    assert len({row["product_id"] for row in products}) == len(products)
    assert len({row["variant_id"] for row in variants}) == len(variants)
    ids = {row["product_id"] for row in products}
    assert all(row["product_id"] in ids for row in variants)
    assert all(str(row.get("source_url") or "").startswith("https://") for row in products)
    assert all(row.get("identity_status") in {"source_verified_name", "source_listed_name"} for row in products)
    assert all("price" not in row and "stock" not in row for row in products)
    assert "offers" not in raw or raw["offers"] == []


def test_maison_asrar_royal_collection_is_present_without_duplicate_names():
    """The nine official standalone Royal Collection names must remain discoverable."""
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    names = [
        row["canonical_name"].casefold()
        for row in raw["products"]
        if row["brand_name"] == "Maison Asrar"
    ]
    royal = {
        "belgravia", "legacy", "vanguard", "regent", "majesty",
        "heritage", "monarch", "treasure", "imperial",
    }
    assert all(names.count(name) == 1 for name in royal)




def test_paris_corner_official_100ml_sizes_are_explicit_variants():
    """Official product pages expose 100ml for these six existing fragrance identities."""
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    expected = {
        "SH-PARIS-CORNER-c5ed3eb2": "https://www.pariscornerperfumes.com/products/confidential-100ml",
        "SH-PARIS-CORNER-KHAYAL-PG09": "https://www.pariscornerperfumes.com/products/khayal-100ml",
        "SH-PARIS-CORNER-MINYA-PG19": "https://www.pariscornerperfumes.com/products/minya-100ml",
        "SH-PARIS-CORNER-OPHIDIAN-BLACK-CHERRY-PG29": "https://www.pariscornerperfumes.com/products/ophidian-black-cherry-100ml",
        "SH-PARIS-CORNER-QAWAFI-P310": "https://www.pariscornerperfumes.com/products/qawafi-100ml",
        "SH-PARIS-CORNER-TASKEEN-LACTEA-DIVINA-P326": "https://www.pariscornerperfumes.com/products/taskeen-lactea-divina-100ml",
    }
    products = {row["product_id"]: row for row in raw["products"]}
    variants = {row["product_id"]: row for row in raw["variants"] if row["product_id"] in expected}
    paris_corner_official_names = {
        "Virilis", "Zahi", "Zahri Amara", "Zaman Al Ula", "Zariya",
        "Zodiac", "Zodiac Lunaris", "Zodiac Solmaris", "Zodiac Stratos",
    }
    catalog_names = {
        row["canonical_name"] for row in raw["products"]
        if row["brand_name"] == "Paris Corner"
    }
    assert paris_corner_official_names <= catalog_names
    assert set(variants) == set(expected)
    for product_id, evidence_url in expected.items():
        assert products[product_id]["source_evidence_url"] == evidence_url
        assert variants[product_id]["size_ml"] == 100



def test_armaf_official_page_products_and_concentration_variants_are_traceable():
    """New Armaf fragrance names and the two size/concentration distinctions stay explicit."""
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {row["product_id"]: row for row in raw["products"]}
    variants = {row["variant_id"]: row for row in raw["variants"]}
    expected = {
        "SH-ARMAF-OFFICIAL-ODYSSEY-BLOODY-HOT": ("Odyssey Bloody Hot", "Eau de Parfum", "https://armaf.com/products/odyssey-bloody-hot"),
        "SH-ARMAF-OFFICIAL-ODYSSEY-RING-MY-BELL": ("Odyssey Ring My Bell", "Eau de Parfum", "https://armaf.com/products/odyssey-ring-my-bell"),
        "SH-ARMAF-OFFICIAL-ETER-ARABIAN-SKY": ("Eter Arabian Sky", "Eau de Parfum", "https://armaf.com/products/eter-arabian-sky"),
        "SH-ARMAF-OFFICIAL-ODYSSEY-FRENCH-KISS": ("Odyssey French Kiss", "Eau de Parfum", "https://armaf.com/products/odyssey-french-kiss"),
        "SH-ARMAF-OFFICIAL-ODYSSEY-PINK-POP": ("Odyssey Pink Pop", "Eau de Parfum", "https://armaf.com/products/odyssey-pink-pop-edp"),
        "SH-ARMAF-OFFICIAL-SPARTACUS": ("Spartacus", "Eau de Parfum", "https://armaf.com/products/spartacus-edp"),
        "SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-ICONIC-EXTRAIT-DE-PARFUM": ("Club de Nuit Iconic Extrait de Parfum", "Extrait de Parfum", "https://armaf.com/products/club-de-nuit-iconic-estrait-de-parfum"),
    }
    for product_id, (name, concentration, evidence_url) in expected.items():
        row = products[product_id]
        assert row["canonical_name"] == name
        assert row["concentration"] == concentration
        assert row["source_evidence_url"] == evidence_url
    assert variants["SHV-SH-ARMAF-224191af-55-000"]["size_ml"] == 55
    assert variants["SHV-SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-ICONIC-EXTRAIT-DE-PARFUM-70-000"]["size_ml"] == 70
    soda_pop = products["SH-ARMAF-OFFICIAL-ODYSSEY-SODA-POP"]
    assert soda_pop["identity_status"] == "source_verified_name"
    assert soda_pop["source_evidence_url"] == "https://armaf.com/products/odyssey-soda-pop"
    later_page_products = {
        "SH-ARMAF-OFFICIAL-UNIQ-EFFECTS-OF-UNIQ": "https://armaf.com/products/uniq-effects-of-uniq-spr",
        "SH-ARMAF-OFFICIAL-SCENTASY-NOIR-DE-PECHE": "https://armaf.com/products/scentasy-noir-de-peche",
        "SH-ARMAF-OFFICIAL-KUNAFA-CHOCOLATE": "https://armaf.com/products/kunafa-chocolate",
        "SH-ARMAF-OFFICIAL-DUBAI-NIGHTS-MIDNIGHT": "https://armaf.com/products/dubai-nights-midnight-spr",
    }
    for product_id, evidence_url in later_page_products.items():
        assert products[product_id]["source_evidence_url"] == evidence_url
    assert products["SH-ARMAF-OFFICIAL-MIRAGE-WOMAN"]["concentration"] == "Eau de Parfum"
    assert products["SH-ARMAF-OFFICIAL-VOYAGE-BROWN-MAN"]["concentration"] == "Eau de Parfum"
    assert products["SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-LIFE"]["concentration"] == "Eau de Toilette"
    assert variants["SHV-SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-LIFE-100-000"]["size_ml"] == 100
    assert "The Lion's Club Monarque" in products["SH-ARMAF-LION-S-CLUB-MONARQUE-P337"]["aliases"]
    assert "Craze Man Parfum" in products["SH-ARMAF-CRAZE-FOR-MEN-P032"]["aliases"]
    assert "Club de Nuit Urban" in products["SH-ARMAF-36ca3d7f"]["aliases"]
    assert products["SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-WOMAN-PARFUM-EXTREME-EDITION"]["concentration"] == "Parfum"
    assert products["SH-ARMAF-OFFICIAL-NICHE-PURPLE-AMETHYST-FLEUR"]["concentration"] == "Eau de Parfum"
    assert variants["SHV-SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-WOMAN-PARFUM-EXTREME-EDITION-105-000"]["size_ml"] == 105
    assert "Club de Nuit Precieux 1 Extrait de Parfum" in products["SH-ARMAF-224191af"]["aliases"]
    assert "Club de Nuit Woman Extrait de Parfum" in products["SH-ARMAF-7a645342"]["aliases"]



def test_armaf_official_us_listing_pages_13_to_26_additional_fragrance_names():
    """Additional perfume identities from later official US collection pages remain source-listed."""
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {row["product_id"]: row for row in raw["products"]}
    expected = {
        "ART-DU-PARFUM-ABSTRACTO": ("Art Du'Parfum Abstracto", "Eau de Parfum", 14),
        "THE-LION-S-CLUB-COURAGEUX": ("The Lion's Club Courageux", "Eau de Parfum", 14),
        "EL-CIELO-MAN": ("El Cielo Man", "Eau de Parfum", 17),
        "HUNTER-KILLER-MAN": ("Hunter Killer Man", "Eau de Parfum", 17),
        "OROS-PURE-CLOISONNE": ("Oros Pure Cloisonne", "Eau de Parfum", 17),
        "TAG-HER-DONNA-COLORATA-PURPLE": ("Tag Her Donna Colorata Purple", "Eau de Parfum", 17),
        "VANITY-FEMME-ESSENCE-WOMAN": ("Vanity Femme Essence Woman", "Eau de Parfum", 18),
        "AMBER-ARABIA-OUD": ("Amber Arabia Oud", "Eau de Parfum", 18),
        "ETER-DESERT-BREEZE": ("Eter Desert Breeze", "Eau de Parfum", 19),
        "OROS-THE-INVENTOR-BLACK": ("Oros The Inventor Black", "Eau de Parfum", 19),
        "PROFUMI-D-ART-03-LEGNI-DOLCI-BRUCIATI": ("Profumi D'Art 03 Legni Dolci Bruciati", "Eau de Parfum", 20),
        "ODYSSEY-WILD-ONE": ("Odyssey Wild One", "Eau de Parfum", 19),
        "ODYSSEY-AOUD": ("Odyssey Aoud", "Eau de Parfum", 19),
        "CONNOISSEUR-WOMAN": ("Connoisseur Woman", "Eau de Parfum", 20),
        "MAGNIFICENT-SATIN": ("Magnificent Satin", "Eau de Parfum", 16),
        "ETERNIA-MAN": ("Eternia Man", "Eau de Parfum", 14),
        "ETERNIA-MAN-LIMITED-EDITION": ("Eternia Man Limited Edition", None, 14),
        "RED-VELVET": ("Red Velvet", "Eau de Parfum", 22),
        "MISS-ARMAF-MAGNIFIQ": ("Miss Armaf Magnifiq", "Eau de Parfum", 22),
        "SHK-IV-BY-SAOUD-ALKAABI": ("SHK IV by Saoud Alkaabi", "Eau de Parfum", 22),
        "RED-SKY": ("Red Sky", "Eau de Parfum", 22),
        "BUCEPHALUS-NO-X": ("Bucephalus No. X", "Eau de Parfum", 20),
        "NICHE-PLATINUM": ("Niche Platinum", "Eau de Parfum", 23),
        "LE-PARFAIT-AZURE-FEMME": ("Le Parfait Azure Femme", "Eau de Parfum", 23),
        "MAGNIFICENT-POUR-FEMME": ("Magnificent Pour Femme", "Eau de Parfum", 24),
        "LET-S-MOVE-TANGO": ("Let's Move Tango", "Eau de Parfum", 24),
        "MAGNIFICENT-JARDIN": ("Magnificent Jardin", "Eau de Parfum", 24),
        "CLUB-DE-NUIT-INTENSE-MAN-PARFUM-EXTREME-EDITION": ("Club de Nuit Intense Man Parfum Extreme Edition", "Parfum", 26),
        "BLUE-SKY": ("Blue Sky", "Eau de Parfum", 26),
        "BLUE-HOMME": ("Blue Homme", "Eau de Toilette", 26),
    }
    for suffix, (name, concentration, page) in expected.items():
        row = products[f"SH-ARMAF-OFFICIAL-{suffix}"]
        assert row["canonical_name"] == name
        assert row.get("concentration") == concentration
        evidence = f"https://armaf.com/collections/all-fragrances-not-gift-set?page={page}"
        assert row["source_evidence_url"] == evidence
        assert row["identity_status"] == "source_listed_name"
