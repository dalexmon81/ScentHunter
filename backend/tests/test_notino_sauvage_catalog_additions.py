"""Regression tests for the Dior Sauvage concentration family in the canonical catalog."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Brand, Fragrance, ProductVariant
from app.search.catalog import search_catalog
from scripts.seed_catalog import validate_catalog
from scenthunter_next_engine.catalog_repository import merge_supplemental_catalog


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
CATALOG = BACKEND / "product_catalog.json"


def test_notino_sauvage_edp_supplement_completes_four_known_sizes():
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    merged = merge_supplemental_catalog(raw, CATALOG)
    products, variants_by_product, blocked = validate_catalog(merged)

    assert blocked == []
    product = next(row for row in products if row["product_id"] == "SH-AUTO-0178")
    variants = variants_by_product[product["product_id"]]
    assert sorted(
        int(row["size_ml"])
        for row in variants
        if (row.get("concentration") or product.get("concentration")) == "Eau de Parfum"
    ) == [30, 60, 100, 200]


def test_search_title_does_not_repeat_concentration_and_keeps_families_separate():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            brand = Brand(name="Dior", slug="dior", normalized_name="dior")
            session.add(brand)
            session.flush()
            edp = Fragrance(
                brand_id=brand.id, name="Sauvage Eau de Parfum",
                slug="sauvage-eau-de-parfum",
            )
            edt = Fragrance(
                brand_id=brand.id, name="Sauvage",
                slug="sauvage",
            )
            elixir = Fragrance(
                brand_id=brand.id, name="Sauvage Elixir",
                slug="sauvage-elixir",
            )
            session.add_all([edp, edt, elixir])
            session.flush()
            session.add_all([
                ProductVariant(
                    fragrance_id=edp.id, concentration="Eau de Parfum",
                    size_ml=30, is_tester=False, is_refill=False,
                    is_gift_set=False, is_mini=False,
                    canonical_key="dior|sauvage|edp|30|regular|standard|single|standard",
                ),
                ProductVariant(
                    fragrance_id=edp.id, concentration="Eau de Parfum",
                    size_ml=100, is_tester=False, is_refill=False,
                    is_gift_set=False, is_mini=False,
                    canonical_key="dior|sauvage|edp|100|regular|standard|single|standard",
                ),
                ProductVariant(
                    fragrance_id=edt.id, concentration="Eau de Toilette",
                    size_ml=30, is_tester=False, is_refill=False,
                    is_gift_set=False, is_mini=False,
                    canonical_key="dior|sauvage|edt|30|regular|standard|single|standard",
                ),
                ProductVariant(
                    fragrance_id=elixir.id, concentration="Elixir",
                    size_ml=60, is_tester=False, is_refill=False,
                    is_gift_set=False, is_mini=False,
                    canonical_key="dior|sauvage|elixir|60|regular|standard|single|standard",
                ),
            ])

            result = search_catalog(session, "Dior Sauvage")
            names = {row["name"] for row in result["results"]}
            assert "Sauvage Eau de Parfum" in names
            assert "Sauvage Eau de Toilette" in names
            assert "Sauvage Elixir" in names
            assert "Sauvage Eau de Parfum Eau de Parfum" not in names
            assert "Sauvage Elixir Elixir" not in names
    finally:
        engine.dispose()


def test_seed_imports_all_four_edp_sizes_into_postgres_compatible_catalog():
    from sqlalchemy import select
    from app.models import LegacyProductIdMap, Fragrance, ProductVariant

    with tempfile.TemporaryDirectory() as temp:
        database_url = "sqlite:///" + str(Path(temp) / "catalog.sqlite3")
        env = os.environ.copy()
        env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
        schema_engine = create_engine(database_url)
        try:
            Base.metadata.create_all(schema_engine)
        finally:
            schema_engine.dispose()
        completed = subprocess.run(
            [
                sys.executable, str(BACKEND / "scripts" / "seed_catalog.py"),
                "--catalog", str(CATALOG), "--apply",
            ],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )
        assert completed.returncode == 0, completed.stdout + "\\n" + completed.stderr

        engine = create_engine(database_url)
        try:
            with Session(engine) as session:
                mapping = session.get(LegacyProductIdMap, "SH-AUTO-0178")
                assert mapping is not None
                fragrance = session.get(Fragrance, mapping.fragrance_id)
                assert fragrance is not None
                variants = session.scalars(
                    select(ProductVariant).where(
                        ProductVariant.fragrance_id == fragrance.id,
                        ProductVariant.concentration == "Eau de Parfum",
                    ).order_by(ProductVariant.size_ml)
                ).all()
                assert [variant.size_ml for variant in variants] == [30, 60, 100, 200]

                expected_families = {
                    "SH-0039": ("Eau de Toilette", [30, 60, 100, 200]),
                    "SH-0040": ("Elixir", [60, 100, 150]),
                }
                for product_id, (concentration, expected_sizes) in expected_families.items():
                    family_map = session.get(LegacyProductIdMap, product_id)
                    assert family_map is not None
                    family_variants = session.scalars(
                        select(ProductVariant).where(
                            ProductVariant.fragrance_id == family_map.fragrance_id,
                            ProductVariant.concentration == concentration,
                        ).order_by(ProductVariant.size_ml)
                    ).all()
                    assert [variant.size_ml for variant in family_variants] == expected_sizes

                result = search_catalog(session, "Dior Sauvage")
                edp = next(row for row in result["results"] if row["name"] == "Sauvage Eau de Parfum")
                edt = next(row for row in result["results"] if row["name"] == "Sauvage Eau de Toilette")
                elixir = next(row for row in result["results"] if row["name"] == "Sauvage Elixir")
                assert [item["size_ml"] for item in edp["formats"]] == [30, 60, 100, 200]
                assert [item["size_ml"] for item in edt["formats"]] == [30, 60, 100, 200]
                assert [item["size_ml"] for item in elixir["formats"]] == [60, 100, 150]
        finally:
            engine.dispose()
