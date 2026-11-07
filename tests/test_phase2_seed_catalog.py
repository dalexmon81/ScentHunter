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
    assert report["fragrances"] == 1775
    assert report["variants"] == 202
    assert report["products_without_variants"] == 1595
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
    assert len(products) == 1775
    assert len(variants) == 202
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
        source_evidence = row["source_evidence_url"]
        assert source_evidence.startswith("https://armaf.com/")
        assert "/collections/" in source_evidence or "/products/" in source_evidence
        assert row["identity_status"] == "source_listed_name"



def test_additional_armaf_official_detail_records_and_variants_are_preserved():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {row["product_id"]: row for row in raw["products"]}
    variants = {row["variant_id"]: row for row in raw["variants"]}
    expected = {
        "SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-SUCCESS": ("Club de Nuit Private Key To My Success", "Eau de Parfum", "https://armaf.com/products/copy-of-club-de-nuit-private-key-to-my-success-100ml"),
        "SH-ARMAF-OFFICIAL-MISS-ARMAF-DAZZLING": ("Miss Armaf Dazzling", "Eau de Parfum", "https://armaf.com/products/miss-armaf-dazzling"),
        "SH-ARMAF-OFFICIAL-CHECKMATE-WHITE-KNIGHT": ("Checkmate White Knight", "Eau de Parfum", "https://armaf.com/products/checkmate-white-knight-1"),
        "SH-ARMAF-OFFICIAL-TAG-HIM-PRESTIGE": ("Tag Him Prestige", None, "https://armaf.com/products/tag-him-prestige"),
        "SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-LOVE": ("Club de Nuit Private Key To My Love", "Eau de Toilette", "https://armaf.com/products/club-de-nuit-private-key-to-my-love-100ml"),
        "SH-ARMAF-OFFICIAL-DUBAI-NIGHTS-UMBRA": ("Dubai Nights Umbra", None, "https://armaf.com/products/dubai-nights-umbra-spr"),
        "SH-ARMAF-OFFICIAL-OROS-THE-INVENTOR-BROWN": ("Oros The Inventor Brown", "Eau de Parfum", "https://armaf.com/products/the-inventor"),
        "SH-ARMAF-OFFICIAL-EGO-TIGRE": ("Ego Tigre", "Eau de Parfum", "https://armaf.com/products/ego-tiger"),
    }
    for product_id, (name, concentration, evidence_url) in expected.items():
        row = products[product_id]
        assert row["canonical_name"] == name
        assert row.get("concentration") == concentration
        assert row["source_evidence_url"] == evidence_url
    for variant_id, size_ml in {
        "SHV-SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-SUCCESS-100-000": 100,
        "SHV-SH-ARMAF-OFFICIAL-MISS-ARMAF-DAZZLING-100-000": 100,
        "SHV-SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-LOVE-100-000": 100,
        "SHV-SH-ARMAF-OFFICIAL-OROS-THE-INVENTOR-BROWN-85-000": 85,
        "SHV-SH-ARMAF-OFFICIAL-EGO-TIGRE-100-000": 100,
    }.items():
        assert variants[variant_id]["size_ml"] == size_ml



def test_armaf_official_pages_13_to_16_added_missing_fragrance_identities_and_sizes():
    """Only products confirmed by official detail pages are added; sizes remain explicit."""
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {row["product_id"]: row for row in raw["products"]}
    variants = {row["variant_id"]: row for row in raw["variants"]}
    expected = {
        "SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-SUCCESS": ("Club de Nuit Private Key To My Success", "Eau de Parfum", "https://armaf.com/products/copy-of-club-de-nuit-private-key-to-my-success-100ml"),
        "SH-ARMAF-OFFICIAL-MISS-ARMAF-DAZZLING": ("Miss Armaf Dazzling", "Eau de Parfum", "https://armaf.com/products/miss-armaf-dazzling"),
        "SH-ARMAF-OFFICIAL-CHECKMATE-WHITE-KNIGHT": ("Checkmate White Knight", "Eau de Parfum", "https://armaf.com/products/checkmate-white-knight-1"),
        "SH-ARMAF-OFFICIAL-TAG-HIM-PRESTIGE": ("Tag Him Prestige", None, "https://armaf.com/products/tag-him-prestige"),
        "SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-LOVE": ("Club de Nuit Private Key To My Love", "Eau de Toilette", "https://armaf.com/products/club-de-nuit-private-key-to-my-love-100ml"),
        "SH-ARMAF-OFFICIAL-DUBAI-NIGHTS-UMBRA": ("Dubai Nights Umbra", None, "https://armaf.com/products/dubai-nights-umbra-spr"),
        "SH-ARMAF-OFFICIAL-OROS-THE-INVENTOR-BROWN": ("Oros The Inventor Brown", "Eau de Parfum", "https://armaf.com/products/the-inventor"),
        "SH-ARMAF-OFFICIAL-EGO-TIGRE": ("Ego Tigre", "Eau de Parfum", "https://armaf.com/products/ego-tiger"),
    }
    for product_id, (name, concentration, evidence_url) in expected.items():
        row = products[product_id]
        assert row["canonical_name"] == name
        assert row.get("concentration") == concentration
        assert row["source_evidence_url"] == evidence_url
        assert row["identity_status"] == "source_verified_name"
    for variant_id, size_ml in {
        "SHV-SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-SUCCESS-100-000": 100,
        "SHV-SH-ARMAF-OFFICIAL-MISS-ARMAF-DAZZLING-100-000": 100,
        "SHV-SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-LOVE-100-000": 100,
        "SHV-SH-ARMAF-OFFICIAL-OROS-THE-INVENTOR-BROWN-85-000": 85,
        "SHV-SH-ARMAF-OFFICIAL-EGO-TIGRE-100-000": 100,
    }.items():
        assert variants[variant_id]["size_ml"] == size_ml



def test_armaf_pages_17_to_20_official_ombre_and_eter_products_are_traced():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {row["product_id"]: row for row in raw["products"]}
    variants = {row["variant_id"]: row for row in raw["variants"]}
    ombre = products["SH-ARMAF-OFFICIAL-OMBRE-OUD-INTENSE-BLACK"]
    assert ombre["canonical_name"] == "Ombre Oud Intense Black"
    assert ombre["concentration"] == "Eau de Parfum"
    assert ombre["source_evidence_url"] == "https://armaf.com/products/ombre-oud-intense-black"
    assert variants["SHV-SH-ARMAF-OFFICIAL-OMBRE-OUD-INTENSE-BLACK-100-000"]["size_ml"] == 100
    eter = products["SH-ARMAF-OFFICIAL-ETER-DESERT-ROSE"]
    assert eter["canonical_name"] == "Eter Desert Rose"
    assert eter["concentration"] == "Eau de Parfum"
    assert eter["source_evidence_url"] == "https://armaf.com/products/eter-desert-rose"
    assert not any(v["product_id"] == eter["product_id"] for v in raw["variants"])



def test_armaf_pages_13_to_20_missing_official_products_and_100ml_variants():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {row["product_id"]: row for row in raw["products"]}
    variants = {row["variant_id"]: row for row in raw["variants"]}
    expected = {
        "SH-ARMAF-OFFICIAL-ETER-PERFUME-OASIS": ("Eter Perfume Oasis", "Eau de Parfum", "https://armaf.com/products/eter-perfume-oasis"),
        "SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-DREAMS": ("Club de Nuit Private Key To My Dreams", "Eau de Toilette", "https://armaf.com/products/club-de-nuit-private-key-to-my-dreams-100ml"),
        "SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-SOUL": ("Club de Nuit Private Key To My Soul", "Eau de Parfum", "https://armaf.com/products/club-de-nuit-private-key-to-my-soul-100ml"),
        "SH-ARMAF-OFFICIAL-NICHE-SAPPHIRE": ("Niche Sapphire", None, "https://armaf.com/products/niche-saphire"),
        "SH-ARMAF-OFFICIAL-PROFUMI-DART-13-TANTA-ROBA": ("Profumi D'Art 13 Tanta Roba", "Eau de Parfum", "https://armaf.com/products/profumi-dart-13-e-tanta-roba"),
    }
    for product_id, (name, concentration, evidence_url) in expected.items():
        row = products[product_id]
        assert row["canonical_name"] == name
        assert row.get("concentration") == concentration
        assert row["source_evidence_url"] == evidence_url
        assert row["identity_status"] == "source_verified_name"
    for variant_id in (
        "SHV-SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-DREAMS-100-000",
        "SHV-SH-ARMAF-OFFICIAL-CLUB-DE-NUIT-PRIVATE-KEY-TO-MY-SOUL-100-000",
        "SHV-SH-ARMAF-OFFICIAL-PROFUMI-DART-13-TANTA-ROBA-100-000",
    ):
        assert variants[variant_id]["size_ml"] == 100



def test_armaf_pages_22_to_24_new_fragrances_and_large_sizes_are_traceable():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {row["product_id"]: row for row in raw["products"]}
    variants = {row["variant_id"]: row for row in raw["variants"]}
    expected = {
        "SH-ARMAF-OFFICIAL-OROS-UOMO": ("Oros Uomo", "Eau de Parfum", "https://armaf.com/products/oros-uomo"),
        "SH-ARMAF-OFFICIAL-ART-DU-PARFUM-POUR-HOMME": ("Art Du' Parfum Pour Homme", "Eau de Parfum", "https://armaf.com/products/art-du-parfum"),
        "SH-ARMAF-OFFICIAL-RADICAL-BLUE-MAN": ("Radical Blue Man", "Eau de Parfum", "https://armaf.com/products/radical-edp-for-men-slate-blue-btl"),
        "SH-ARMAF-OFFICIAL-OROS-OUD": ("Oros Oud", "Eau de Parfum", "https://armaf.com/products/oros-oud"),
    }
    for product_id, (name, concentration, evidence_url) in expected.items():
        row = products[product_id]
        assert row["canonical_name"] == name
        assert row["concentration"] == concentration
        assert row["source_evidence_url"] == evidence_url
        assert row["identity_status"] == "source_verified_name"
    for variant_id, size_ml in {
        "SHV-SH-ARMAF-OFFICIAL-OROS-UOMO-100-000": 100,
        "SHV-SH-ARMAF-OFFICIAL-RADICAL-BLUE-MAN-100-000": 100,
        "SHV-SH-ARMAF-OFFICIAL-OROS-OUD-85-000": 85,
        "SHV-SH-ARMAF-6a665a32-200-000": 200,
        "SHV-SH-ARMAF-OFFICIAL-LE-PARFAIT-AZURE-FEMME-200-000": 200,
    }.items():
        assert variants[variant_id]["size_ml"] == size_ml


def test_requested_brand_catalog_coverage_and_maison_asrar_royal_collection():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = raw["products"]
    brands = {row.get("brand") or row.get("brand_name") for row in products}
    expected_brands = {
        "Velixir", "Mykonos", "Maison Asrar", "Khadlaj", "Bujairami",
        "Paris Corner", "Assaf", "Al Wataniah", "Armaf", "French Avenue",
        "Arabiyat Prestige", "Gulf Orchid", "Swiss Arabian", "Games of Spades",
        "Lattafa", "Afnan", "Aromatix", "Maison Alhambra", "Zimaya",
        "Al Haramain",
    }
    assert expected_brands.issubset(brands)

    royal_names = {
        "Belgravia", "Legacy", "Vanguard", "Regent", "Majesty",
        "Monarch", "Heritage", "Imperial", "Treasure",
    }
    royal_products = {
        row["canonical_name"]: row for row in products
        if row.get("brand") == "Maison Asrar"
        and row.get("collection_name") == "Royal Collection"
    }
    assert set(royal_products) == royal_names
    official_collection = "https://maisonasrar.com/collections/royal-collection"
    for row in royal_products.values():
        assert row["source_url"] == official_collection
        assert row["source_evidence_url"].startswith("https://")
        assert row["identity_status"] == "source_listed_name"


def test_requested_brand_catalog_has_unique_product_ids_and_no_orphan_variants():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = raw["products"]
    variants = raw["variants"]
    product_ids = [row["product_id"] for row in products]
    variant_ids = [row["variant_id"] for row in variants]
    assert len(product_ids) == len(set(product_ids))
    assert len(variant_ids) == len(set(variant_ids))
    product_id_set = set(product_ids)
    assert all(row["product_id"] in product_id_set for row in variants)


def test_khadlaj_official_perfume_spray_detail_pages_and_sizes_are_traceable():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {row["canonical_name"]: row for row in raw["products"] if row.get("brand") == "Khadlaj"}
    variants = {row["variant_id"]: row for row in raw["variants"]}
    expected = {
        "25 Experience": "https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-experience-100-ml-edp-spray",
        "25 Trust": "https://khadlaj-perfumes.com/collections/perfumes-spray/products/buy-khadlaj-25-trust-100-ml-edp-spray-best-gourmand-perfume-for-women",
        "25 Loyalty": "https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-loyalty-100-ml-edp-spray-best-women-perfume-to-shop-online-dubai-uae",
        "25 Heritage": "https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-heritage-100-ml-edp-spray",
        "25 Integrity": "https://khadlaj-perfumes.com/collections/perfumes-spray/products/khadlaj-25-integrity-100-ml-edp-spray",
    }
    for name, url in expected.items():
        row = products[name]
        assert row["source_url"] == url
        assert row["source_evidence_url"] == url
        assert row["identity_status"] == "source_verified_name"
        assert row["formats_ml"] == [100]
        assert row["concentration"] == "Eau de Parfum"
        variant_id = f"SHV-{row['product_id']}-100-000"
        assert variants[variant_id]["size_ml"] == 100
        assert variants[variant_id]["concentration"] == "Eau de Parfum"

    musk = products["Musk Pure Musk Blend"]
    assert "Musk Pure Musk Blend Creation of Iqbal" in musk["aliases"]
    assert musk["identity_status"] == "source_verified_name"
    assert musk["source_url"].endswith("musk-pure-musk-blend-creation-of-iqbal-65-ml-edp-spray-perfume-for-men-and-women-online-dubai-uae")
    assert variants["SHV-SH-KHADLAJ-04832397-60-000"]["size_ml"] == 60

    wild = products["Wild Indonesian Oud"]
    assert "Wild Indonesian Oud Pure" in wild["aliases"]
    assert wild["formats_ml"] == [60]
    assert wild["concentration"] == "Eau de Parfum"
    assert wild["identity_status"] == "source_verified_name"
    wild_variant_id = f"SHV-{wild['product_id']}-60-000"
    assert variants[wild_variant_id]["size_ml"] == 60
    assert variants[wild_variant_id]["concentration"] == "Eau de Parfum"


def test_paris_corner_official_product_lines_are_tagged_without_changing_parent_brand():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {
        row["canonical_name"]: row
        for row in raw["products"]
        if row.get("brand") == "Paris Corner"
    }
    expected = {
        "Emir": {
            "Acadia Intenso Emir", "Arcana", "Atomise Intensive Men",
            "Camp Fire Emir Factory Edition", "Cedrat Essence Emir",
            "Celestial Emir", "Cherry Cola", "Cherry Gossip",
            "Cosmopolitan Dubai", "Cosmopolitan London",
        },
        "Pendora Scents": {
            "Attractus", "Blackberry Wish", "Camaro Homme Intense",
            "Charuto Mysterious Tobacco", "Charuto Regal Reserve",
            "Cornflower Delight",
        },
        "Ministry of Gourmand": {
            "Banana Bliss", "Cake Temptation", "Choco Cult", "Coconut Lagoon",
        },
        "North Stag": {"North Stag Neuf IX"},
    }
    source_urls = {
        "Emir": "https://www.pariscornerperfumes.com/collections/emir-1",
        "Pendora Scents": "https://www.pariscornerperfumes.com/collections/pendora-scents-1",
        "Ministry of Gourmand": "https://www.pariscornerperfumes.com/collections/ministry-of-gourmand",
        "North Stag": "https://www.pariscornerperfumes.com/collections/north-stag-1",
    }
    for line, names in expected.items():
        for name in names:
            row = products[name]
            assert row["brand"] == "Paris Corner"
            assert row["collection_name"] == line
            assert row["source_url"] == source_urls[line]
            assert row["source_evidence_url"] == source_urls[line]


def test_maison_asrar_royal_collection_matches_current_official_nine_product_listing():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = [
        row for row in raw["products"]
        if row.get("brand") == "Maison Asrar"
        and row.get("collection_name") == "Royal Collection"
    ]
    names = {row["canonical_name"] for row in products}
    assert names == {
        "Belgravia", "Legacy", "Vanguard", "Regent", "Majesty",
        "Monarch", "Heritage", "Imperial", "Treasure",
    }
    official_collection = "https://maisonasrar.com/collections/royal-collection"
    assert all(row.get("source_url") == official_collection for row in products)
    assert all(row.get("source_evidence_url") == official_collection for row in products)


def test_armaf_official_collection_membership_and_missing_collaborations_are_reconciled():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {
        row["canonical_name"]: row
        for row in raw["products"]
        if row.get("brand") == "Armaf"
    }
    official = {
        "Club de Nuit": "https://armaf.com/collections/club-de-nuit",
        "Odyssey": "https://armaf.com/collections/odyssey",
        "Tres Nuit": "https://armaf.com/collections/armaf-tres-nuit-collection",
        "Checkmate": "https://armaf.com/collections/checkmate",
        "Eter": "https://armaf.com/collections/eter",
        "Bucephalus": "https://armaf.com/collections/bucephalus",
        "Tag": "https://armaf.com/collections/tag",
        "Armaf Delights": "https://armaf.com/collections/armaf-delights",
        "The Lion's Club": "https://armaf.com/collections/the-lions-club",
        "Profumi D'Art": "https://armaf.com/collections/profumi-dart",
        "ARMAF X Christian Provenzano": "https://armaf.com/collections/armaf-collection-for-christian-provenzano",
        "ARMAF X SHK": "https://armaf.com/collections/shk",
        "Oros": "https://armaf.com/collections/oros",
        "ARMAF Niche": "https://armaf.com/collections/armaf-niche",
        "The Inventor": "https://armaf.com/collections/armaf-the-inventor",
    }
    expected = {
        "Club de Nuit Untold": "Club de Nuit",
        "Odyssey Mandarin Sky": "Odyssey",
        "Tres Nuit Man": "Tres Nuit",
        "Checkmate King": "Checkmate",
        "Eter Desert Star": "Eter",
        "Bucephalus No. X": "Bucephalus",
        "Tag Him Man": "Tag",
        "The Lion's Club Courageux": "The Lion's Club",
        "Profumi D'Art 13 Tanta Roba": "Profumi D'Art",
        "Christian Provenzano I": "ARMAF X Christian Provenzano",
        "Christian Provenzano II": "ARMAF X Christian Provenzano",
        "Christian Provenzano III": "ARMAF X Christian Provenzano",
        "Christian Provenzano IV": "ARMAF X Christian Provenzano",
        "SHK I by Saoud Alkaabi": "ARMAF X SHK",
        "SHK II by Saoud Alkaabi": "ARMAF X SHK",
        "SHK III by Saoud Alkaabi": "ARMAF X SHK",
        "SHK IV by Saoud Alkaabi": "ARMAF X SHK",
        "Oros The Inventor Black": "The Inventor",
        "Oros The Inventor Brown": "The Inventor",
        "Oros": "Oros",
        "Niche Purple Amethyst": "ARMAF Niche",
    }
    for name, line in expected.items():
        row = products[name]
        assert row["collection_name"] == line
        assert row["collection_source_url"] == official[line]
    assert products["Club de Nuit Intense Man"]["source_url"] == "https://armaf.com/products/club-de-nuit-intense-for-man"
    assert products["Club de Nuit Intense Man"]["source_evidence_url"] == "https://armaf.com/products/club-de-nuit-intense-for-man"
    assert len(products) == 303
    # Regional source spellings were consolidated into their current official product identities.
    assert "Odyssey Lichi Lush" in products["Odyssey Li'Chi Lush EDP"]["aliases"]
    assert "Lion's Club Courageux" in products["The Lion's Club Courageux"]["aliases"]
    assert "Profumi D'Art 13 E Tanta Roba" in products["Profumi D'Art 13 Tanta Roba"]["aliases"]
    assert "Perfume Oasis For Eter" in products["Eter Perfume Oasis"]["aliases"]
    assert "Desert Rose For Eter" in products["Eter Desert Rose"]["aliases"]
    assert sum(1 for row in products.values() if row["canonical_name"] == "Odyssey Lichi Lush") == 0
    assert sum(1 for row in products.values() if row["canonical_name"] == "Lion's Club Courageux") == 0


def test_armaf_official_us_first_four_all_fragrances_pages_resolve_to_existing_identities():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {
        row["canonical_name"]: row
        for row in raw["products"]
        if row.get("brand") == "Armaf"
    }
    expected_detail_pages = {
        "Club de Nuit Woman Extrait": "https://armaf.com/products/cdn-club-de-nuit-extrait-de-parfum-spr",
        "Odyssey Pink Pop": "https://armaf.com/products/odyssey-pink-pop-edp",
        "Spartacus": "https://armaf.com/products/spartacus-edp",
    }
    for name, url in expected_detail_pages.items():
        row = products[name]
        assert row["source_evidence_url"] == url
        assert row["source_evidence_url"] == url
        assert row["identity_status"] == "source_verified_name"
    assert len(products) == 303


def test_khadlaj_six_additional_official_product_identities_have_verified_variants():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {
        row["canonical_name"]: row
        for row in raw["products"]
        if row.get("brand") == "Khadlaj"
    }
    variants = {row["variant_id"]: row for row in raw["variants"]}
    expected = {
        "Bleu Glace": (
            "https://khadlaj-perfumes.com/ar/collections/for-him/products/bleu-glace-100-ml-extrait-de-parfum-for-men-fresh-fragrance-online-dubai-uae",
            100, "Extrait de Parfum",
        ),
        "Gaith": (
            "https://khadlaj-perfumes.com/collections/all/products/gaith-100-ml-edp-spray-men-perfumes-dubai-uae",
            100, "Eau de Parfum",
        ),
        "Qarar": (
            "https://khadlaj-perfumes.com/products/khadlaj-qarar-unisex-bold-oriental-extrait-de-parfum",
            60, "Extrait de Parfum",
        ),
        "Sueño": (
            "https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/sueno-100ml-extrait-de-parfum-for-women",
            100, "Extrait de Parfum",
        ),
        "Wow Oud": (
            "https://khadlaj-perfumes.com/collections/oud-range/products/wow-oud-100-ml-edp-spray",
            100, "Eau de Parfum",
        ),
        "Zayaan Silver": (
            "https://khadlaj-perfumes.com/products/zayaan-silver-fresh-aquatic-spicy-woody-eau-de-parfum-for-men",
            100, "Eau de Parfum",
        ),
    }
    for name, (url, size, concentration) in expected.items():
        row = products[name]
        assert row["identity_status"] == "source_verified_name"
        assert row["source_url"] == url
        assert row["source_evidence_url"] == url
        assert row["formats_ml"] == [size]
        assert row["concentration"] == concentration
        variant_id = f"SHV-{row['product_id']}-{size}-000"
        assert variants[variant_id]["size_ml"] == size
        assert variants[variant_id]["concentration"] == concentration

    # The official Bleu Glace page establishes its 100 ml format but no GTIN.
    assert "gtin" not in products["Bleu Glace"]

def test_paris_corner_magic_oud_north_stag_and_ministry_lines_have_official_membership():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {
        row["canonical_name"]: row
        for row in raw["products"]
        if row.get("brand") == "Paris Corner"
    }
    expected = {
        "Magic Oud Series": {
            "Magic Oud Dark Roses", "Magic Oud In Pure Zaffron",
            "Magic Oud Kalimath", "Magic Oud Kashmir Musk",
        },
        "North Stag": {
            "Quatre IV Expressions, North Stag", "Trois III Expressions, North Stag",
            "Deux II Expressions, North Stag", "Un I Expressions, North Stag",
            "North Stag Hypnotic Oud Quinze XV", "North Stag Phenomenal Quatorze XIV",
            "North Stag Huit VIII", "North Stag Sept VII",
        },
        "Ministry of Oud": {
            "Ministry of Oud - Amber Oud", "Ministry of Oud - Oud Indonesian",
            "Ministry of Oud - Oud Royal", "Ministry of Oud - Oud Satin",
            "Ministry of Oud - Strictly Oud", "Ministry of Oud - Thailand Oud in Cairo",
            "Ministry of Oud Greatest", "Ministry of Oud - Gladiators Oath",
            "Ministry of Oud - Maestro's Symphony", "Ministry of Oud - Nile Whispers",
            "Ministry of Oud - Oud Beyond the Wall", "Ministry of Oud - Romance Reverie",
        },
        "Ministry of Gourmand": {
            "Creamy Biscuit", "Mango Jugoso", "Strawberry Pound Cake", "Tiramisu Speculoos",
        },
    }
    source_urls = {
        "Magic Oud Series": "https://www.pariscornerperfumes.com/collections/magic-oud-series",
        "North Stag": "https://www.pariscornerperfumes.com/collections/north-stag-1",
        "Ministry of Oud": "https://www.pariscornerperfumes.com/collections/ministry-of-oud",
        "Ministry of Gourmand": "https://www.pariscornerperfumes.com/collections/ministry-of-gourmand",
    }
    for line, names in expected.items():
        for name in names:
            row = products[name]
            assert row["brand"] == "Paris Corner"
            assert row["collection_name"] == line
            assert row["identity_status"] == "source_listed_name"
            assert row["source_url"] == source_urls[line]
            assert row["source_evidence_url"] == source_urls[line]
            assert row.get("formats_ml") is None
            assert row.get("concentration") is None
    assert len(expected["Magic Oud Series"]) + len(expected["North Stag"]) + len(expected["Ministry of Oud"]) + len(expected["Ministry of Gourmand"]) == 28



def test_paris_corner_core_collection_records_use_official_brand_collection_evidence():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {row["canonical_name"]: row for row in raw["products"] if row.get("brand") == "Paris Corner"}
    page_one_names = {
        "Affogato Al Caffe", "Aira", "Arwa", "Atoof", "Azm", "Bayn Al Asrar",
        "Caramel Bash", "Choco Lait", "Ciao Citrus", "Confidential", "Cosmic Giardino",
        "Dar Al Oud", "Date Caramel", "December Ambar", "December Rose",
        "December Vanilla", "Dulzura", "Dulzura Vanilla Envie",
    }
    official_collection = "https://www.pariscornerperfumes.com/collections/paris-corner"
    for name in page_one_names:
        row = products[name]
        assert row["collection_name"] == "Paris Corner"
        assert row["source_url"] == official_collection
        assert row["source_evidence_url"].startswith("https://")

    for row in products.values():
        if "/collections/paris-corner" in row.get("source_url", ""):
            assert row["collection_name"] == "Paris Corner"

def test_paris_corner_emir_pendora_and_parent_official_listing_gaps_are_added():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {
        row["canonical_name"]: row
        for row in raw["products"]
        if row.get("brand") == "Paris Corner"
    }
    expected = {
        "Emir": {
            "Cosmopolitan Newyork", "Elania Emir", "Fascination Emir",
            "Fire Your Desire Emir", "Forbidden Sugar Emir", "Juicy Melange",
            "Just Bergamot Emir Factory Edition", "La Serpiente Emir",
            "Lueur D'Espoir Arena Intense", "Lueur D'Espoir Memories of Summer",
            "Lueur D'Espoir Serene Grove", "Lueur D'Espoir Silhouette",
            "Mango Punch", "Metalico Emir", "Opulentia Empyreal Emir",
            "Opulentia Flame Emir", "Opulentia Inverno Emir", "Opulentia Primus Emir",
            "Oud and Vanille Emir", "Pear Potion", "Pour Me Wild",
            "Rich Santal Emir Factory Edition", "Super Crush Emir",
            "Ultra Citrus Emir Factory Edition", "Valar Series A Chaos in the Ocean",
            "Valar Series A Walk on Dirt", "Valar Series Smoky Leather",
            "Vanilla and Roses Emir", "Vibrant Orange and Neroli Emir",
            "Vibrant Sensual Saffron Emir", "Vibrant Spicy Tobacco Emir",
            "Vibrant Vetiver Delight Emir", "Voux Blue Oud Emir", "Voux Alma Verde",
            "Voux Elegante Emir", "Voux Patisserie", "Voux Spices Emir",
            "Voux Turquoise Emir", "Voux Violette Emir", "Voux Zeste",
            "Voux Zingy", "Warm Leather Emir Factory Edition", "Wayward Charlie Emir",
            "When Soul Gets High Emir",
        },
        "Pendora Scents": {
            "Doris Pink", "Dusky Vanilla", "Ecstatic Blanc Fleur", "English Leather",
            "Enormity", "Fig Fete", "Hidden Halo", "Honeyed Fantasy",
            "Intense Wayfarer", "Intima Red", "La Nuit Pendora", "Lullaby",
            "Mango Flames", "Nectarine Haze", "Neon Star", "Noir D'Arabie",
            "Oud Holidays", "Poppy Pulse", "Praise", "Precision", "Rose de Nuit",
            "The Aoud", "The Green", "The Peace", "The Scent", "The Street",
        },
    }
    source_urls = {
        "Emir": "https://www.pariscornerperfumes.com/collections/emir-1",
        "Pendora Scents": "https://www.pariscornerperfumes.com/collections/pendora-scents-1",
        "Paris Corner": "https://www.pariscornerperfumes.com/collections/paris-corner",
    }
    for line, names in expected.items():
        for name in names:
            row = products[name]
            assert row["brand"] == "Paris Corner"
            assert row["collection_name"] == line
            assert row["identity_status"] == "source_listed_name"
            assert row["source_url"] == source_urls[line]
            assert row["source_evidence_url"] == source_urls[line]
            assert row.get("formats_ml") is None
            assert row.get("concentration") is None
    assert sum(map(len, expected.values())) == 70

def test_pendora_scents_veteran_oud_is_in_official_men_collection():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {
        row["canonical_name"]: row
        for row in raw["products"]
        if row.get("brand") == "Paris Corner"
    }
    row = products["Veteran Oud"]
    official = "https://www.pariscornerperfumes.com/collections/pendora-scents-men"
    assert row["collection_name"] == "Pendora Scents"
    assert row["identity_status"] == "source_listed_name"
    assert row["source_url"] == official
    assert row["source_evidence_url"] == official
    assert row.get("formats_ml") is None
    assert row.get("concentration") is None

def test_paris_corner_parent_collection_all_four_pages_match_105_official_names():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = [
        row for row in raw["products"]
        if row.get("brand") == "Paris Corner"
        and row.get("collection_name") == "Paris Corner"
        and row.get("source_url", "").startswith(
            "https://www.pariscornerperfumes.com/collections/paris-corner"
        )
    ]
    expected_names = {
        "Affogato Al Caffe", "Aira", "Arwa", "Atoof", "Azm", "Bayn Al Asrar",
        "Caramel Bash", "Choco Lait", "Ciao Citrus", "Confidential", "Cosmic Giardino",
        "Dar Al Oud", "Date Caramel", "December Ambar", "December Rose",
        "December Vanilla", "Dulzura", "Dulzura Vanilla Envie", "Eshal Musk",
        "Eshal Vanilla", "Eternal Coffee", "Eternal Meadows", "Eternal Musk", "Farah",
        "Fatal Embrace", "Fayora", "Fayora Oshino", "Green Bet", "Heer", "Hurriya",
        "Ibisco Nirvana", "Indomitable", "Jardin Des Papillons", "Kaheela Platinum",
        "Khair", "Khair Confection", "Khair Felicity", "Khair Fusion",
        "Khair Peach Delulu", "Khair Pistachio", "Khayal", "Manaal",
        "Marshmallow Blush", "Mawj Appletini", "Mawj Cognac Blaze", "Mawj Moscow Mule",
        "Mehwish", "Midnight Sin By Daniel Rene", "Miel Obscura", "Miel Vanille",
        "Minya", "Minya Caramel Dulce", "Minya Coco Lush",
        "Misty Dawn Musk Collection", "Molten Caramel", "Mysterium",
        "Nada Blumingle", "Nada Whimsical", "Nada Wink", "Nouf",
        "Ophidian Black Cherry", "Ophidian Mango Bliss", "Ophidian Sweet Surrender",
        "Oravea", "Oud Faek", "Oud Wahaaj", "Papillon Des Vents", "Perseviron",
        "Perseviron Fig Hug", "Pinkling", "Plum Liquor", "Prodigy", "Prodigy Noir",
        "Qawafi", "Qissa", "Qissa Delicious", "Qissa Gala", "Qissa Pink", "Rawq",
        "Reham Rose Petals", "Reham Vanilla Mood", "Reham Wild Mineral", "Rifaaqat",
        "Rifaaqat Adorn", "Rua", "Rua Radiant Roses", "Soothing Zephyr", "Taskeen",
        "Taskeen Caramel Cascade", "Taskeen Lactea Divina", "Taskeen Marina",
        "Taskeen Wowie", "Tawaaq", "The Show Magnifique",
        "Tranquil Night Musk Collection", "Twilight Shadow Musk Collection",
        "Virilis", "Zahi", "Zahri Amara", "Zaman Al Ula", "Zariya", "Zodiac",
        "Zodiac Lunaris", "Zodiac Solmaris", "Zodiac Stratos",
    }
    actual_names = {row["canonical_name"] for row in products}
    assert len(products) == 105
    assert actual_names == expected_names
    expected_page_counts = {
        "https://www.pariscornerperfumes.com/collections/paris-corner": 32,
        "https://www.pariscornerperfumes.com/collections/paris-corner?page=2": 32,
        "https://www.pariscornerperfumes.com/collections/paris-corner?page=3": 32,
        "https://www.pariscornerperfumes.com/collections/paris-corner?page=4": 9,
    }
    actual_page_counts = {}
    for row in products:
        actual_page_counts[row["source_url"]] = actual_page_counts.get(row["source_url"], 0) + 1
    assert actual_page_counts == expected_page_counts

def test_paris_corner_sixteen_official_product_detail_pages_have_verified_variants():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {
        row["canonical_name"]: row
        for row in raw["products"]
        if row.get("brand") == "Paris Corner"
    }
    variants = {row["variant_id"]: row for row in raw["variants"]}
    expected = {
        "Frenetic Men": ("https://www.pariscornerperfumes.com/products/frenetic-men", 100, "Unclassified"),
        "Frenetic Red Tempt": ("https://www.pariscornerperfumes.com/products/frenetic-red-tempt", 80, "Unclassified"),
        "Frenetic Tobacco Honey": ("https://www.pariscornerperfumes.com/products/frenetic-tobacco-honey", 100, "Emir"),
        "Identity Oud Crescent": ("https://www.pariscornerperfumes.com/products/identity-oud-crescent", 100, "Unclassified"),
        "Identity Rose & Leather": ("https://www.pariscornerperfumes.com/products/identity-rose-leather", 100, "Unclassified"),
        "Identity Unique Portrait": ("https://www.pariscornerperfumes.com/products/identity-unique-portrait", 100, "Unclassified"),
        "Intense Oud": ("https://www.pariscornerperfumes.com/products/intense-oud-arabian", 100, "Unclassified"),
        "Intense Oud Saffron": ("https://www.pariscornerperfumes.com/products/intense-oud-saffron", 100, "Unclassified"),
        "Le Charme": ("https://www.pariscornerperfumes.com/products/la-charme-emir", 100, "Emir"),
        "Protocol Edition": ("https://www.pariscornerperfumes.com/products/protocol-edition", 100, "Pendora Scents"),
        "Resurrection": ("https://www.pariscornerperfumes.com/products/resurrection", 100, "Emir"),
        "The Triumphant Sapphire": ("https://www.pariscornerperfumes.com/products/the-triumphant-sapphire", 100, "Unclassified"),
        "Toxic Heart": ("https://www.pariscornerperfumes.com/products/toxic-heart", 100, "Unclassified"),
        "You're Drugged Emir": ("https://www.pariscornerperfumes.com/products/youre-drugged-emir", 100, "Emir"),
        "Frenetic Delicieuse": ("https://www.pariscornerperfumes.com/products/frenetic-delicieuse", 80, "Unclassified"),
        "Frenetic Homme Intense": ("https://www.pariscornerperfumes.com/products/frenetichomme-intense", 80, "Unclassified"),
    }
    assert len(expected) == 16
    for name, (url, size, line) in expected.items():
        row = products[name]
        assert row["identity_status"] == "source_verified_name"
        assert row["source_product_url"] == url
        assert row["source_evidence_url"] == url
        assert row["collection_name"] == line
        assert row["formats_ml"] == [size]
        variant_id = f"SHV-{row['product_id']}-{size}-000"
        assert variants[variant_id]["product_id"] == row["product_id"]
        assert variants[variant_id]["size_ml"] == size

def test_six_additional_paris_corner_product_detail_pages_have_verified_variants():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {
        row["canonical_name"]: row
        for row in raw["products"]
        if row.get("brand") == "Paris Corner"
    }
    variants = {row["variant_id"]: row for row in raw["variants"]}
    expected = {
        "Harrier Absoulte": ("https://www.pariscornerperfumes.com/products/harrier-absoulte", 100, "Unclassified"),
        "Wild and Tobacco Emir": ("https://www.pariscornerperfumes.com/products/wild-and-tobacco-emir", 75, "Emir"),
        "Lueur d'Espoir Noche": ("https://www.pariscornerperfumes.com/products/lueur-noche", 100, "Unclassified"),
        "Lueur d'Espoir Arena": ("https://www.pariscornerperfumes.com/products/lueur-arena", 100, "Unclassified"),
        "Lueur d'Espoir Ambre": ("https://www.pariscornerperfumes.com/products/lueur-ambre", 100, "Unclassified"),
        "Wayfarer Eau de Parfum": ("https://www.pariscornerperfumes.com/products/wayfarer-dau-de-parfum", 100, "Unclassified"),
    }
    assert len(expected) == 6
    for name, (url, size, line) in expected.items():
        row = products[name]
        assert row["identity_status"] == "source_verified_name"
        assert row["source_product_url"] == url
        assert row["source_evidence_url"] == url
        assert row["collection_name"] == line
        assert row["formats_ml"] == [size]
        variant_id = f"SHV-{row['product_id']}-{size}-000"
        assert variants[variant_id]["product_id"] == row["product_id"]
        assert variants[variant_id]["size_ml"] == size

def test_three_more_paris_corner_official_detail_products_have_size_variants():
    raw = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    products = {
        row["canonical_name"]: row
        for row in raw["products"]
        if row.get("brand") == "Paris Corner"
    }
    variants = {row["variant_id"]: row for row in raw["variants"]}
    expected = {
        "Empire de la Rouge": ("https://www.pariscornerperfumes.com/products/empire-de-la-rouge", 100),
        "Vivant Sunlit": ("https://www.pariscornerperfumes.com/products/vivant-sunlit", 100),
        "Wayfarer Infusion": ("https://www.pariscornerperfumes.com/products/wayfarer-infusion", 100),
    }
    for name, (url, size) in expected.items():
        row = products[name]
        assert row["identity_status"] == "source_verified_name"
        assert row["source_product_url"] == url
        assert row["source_evidence_url"] == url
        assert row["collection_name"] == "Unclassified"
        assert row["formats_ml"] == [size]
        variant_id = f"SHV-{row['product_id']}-{size}-000"
        assert variants[variant_id]["product_id"] == row["product_id"]
        assert variants[variant_id]["size_ml"] == size

