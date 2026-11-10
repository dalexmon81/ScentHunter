"""Regression tests for the Paris Corner and Armaf official variant gap batch."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED_VARIANTS = [
    {
        "product_id": "SH-PARIS-CORNER-cd8b1f8e",
        "brand": "Paris Corner",
        "canonical_name": "Bayn Al Asrar",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-cd8b1f8e-80-EDP",
        "size_ml": 80,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/bayn-al-asrar",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/bayn-al-asrar",
        "source_product_url": "https://de.pariscornereurope.com/en/products/paris-corner-bayn-al-asrar-edp-w-80-ml",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-5239463e",
        "brand": "Paris Corner",
        "canonical_name": "December Rose",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-5239463e-85-EDP",
        "size_ml": 85,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/dcember-rose",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/dcember-rose",
        "source_product_url": "https://de.pariscornereurope.com/en/products/paris-corner-december-rose-edp-u-85-ml",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-ef841988",
        "brand": "Paris Corner",
        "canonical_name": "December Vanilla",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-ef841988-85-EDP",
        "size_ml": 85,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/december-vanilla",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/december-vanilla",
        "source_product_url": "https://de.pariscornereurope.com/en/products/paris-corner-december-vanilla-edp-u-85-ml",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-KHAIR-PISTACHIO",
        "brand": "Paris Corner",
        "canonical_name": "Khair Pistachio",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-KHAIR-PISTACHIO-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/khair-pistachio",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/khair-pistachio",
        "source_product_url": "https://de.pariscornereurope.com/en/products/khair-pistachio",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-KHAIR-CONFECTION",
        "brand": "Paris Corner",
        "canonical_name": "Khair Confection",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-KHAIR-CONFECTION-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/khair-confection",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/khair-confection",
        "source_product_url": "https://de.pariscornereurope.com/en/products/khair-confection",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-KHAIR-FUSION",
        "brand": "Paris Corner",
        "canonical_name": "Khair Fusion",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-KHAIR-FUSION-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/khair-fusion",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/khair-fusion",
        "source_product_url": "https://de.pariscornereurope.com/en/products/khair-fusion",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-KHAIR-FELICITY",
        "brand": "Paris Corner",
        "canonical_name": "Khair Felicity",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-KHAIR-FELICITY-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/khair-felicity-100ml",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/khair-felicity-100ml",
        "source_product_url": "https://de.pariscornereurope.com/en/products/khair-felicity",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-MAWJ-APPLETINI",
        "brand": "Paris Corner",
        "canonical_name": "Mawj Appletini",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-MAWJ-APPLETINI-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/mawj-appletini",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/mawj-appletini",
        "source_product_url": "https://de.pariscornereurope.com/en/products/mawj-appletini",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-MAWJ-MOSCOW-MULE",
        "brand": "Paris Corner",
        "canonical_name": "Mawj Moscow Mule",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-MAWJ-MOSCOW-MULE-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/mawj-moscow-mule",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/mawj-moscow-mule",
        "source_product_url": "https://de.pariscornereurope.com/en/products/paris-corner-mawj-moscow-mule-edp-u-100-ml",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-MAWJ-COGNAC-BLAZE",
        "brand": "Paris Corner",
        "canonical_name": "Mawj Cognac Blaze",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-MAWJ-COGNAC-BLAZE-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/mawj-cognac-blaze",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/mawj-cognac-blaze",
        "source_product_url": "https://de.pariscornereurope.com/products/mawj-cognac-blaze",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-MINYA-COCO-LUSH",
        "brand": "Paris Corner",
        "canonical_name": "Minya Coco Lush",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-MINYA-COCO-LUSH-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/minya-coco-lush",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/minya-coco-lush",
        "source_product_url": "https://de.pariscornereurope.com/en/products/minya-coco-lush",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-COSMOPOLITAN-NEWYORK",
        "brand": "Paris Corner",
        "canonical_name": "Cosmopolitan Newyork",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-COSMOPOLITAN-NEWYORK-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/cosmopolitan-newyork",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/cosmopolitan-newyork",
        "source_product_url": "https://de.pariscornereurope.com/en/products/cosmopolitan-newyork",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-ETERNAL-COFFEE",
        "brand": "Paris Corner",
        "canonical_name": "Eternal Coffee",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-ETERNAL-COFFEE-85-EDP",
        "size_ml": 85,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/eternal-coffee",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/eternal-coffee",
        "source_product_url": "https://de.pariscornereurope.com/en/products/eternal-coffee",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-ETERNAL-MEADOWS",
        "brand": "Paris Corner",
        "canonical_name": "Eternal Meadows",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-ETERNAL-MEADOWS-85-EDP",
        "size_ml": 85,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/eternal-meadows",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/eternal-meadows",
        "source_product_url": "https://de.pariscornereurope.com/en/products/eternal-meadows",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-ETERNAL-MUSK",
        "brand": "Paris Corner",
        "canonical_name": "Eternal Musk",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-ETERNAL-MUSK-85-EDP",
        "size_ml": 85,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/eternal-musk",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/eternal-musk",
        "source_product_url": "https://de.pariscornereurope.com/en/products/eternal-musk",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-KHAIR",
        "brand": "Paris Corner",
        "canonical_name": "Khair",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-KHAIR-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/khair",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/khair",
        "source_product_url": "https://de.pariscornereurope.com/en/products/khair",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-MANAAL",
        "brand": "Paris Corner",
        "canonical_name": "Manaal",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-MANAAL-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/manaal-1",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/manaal-1",
        "source_product_url": "https://de.pariscornereurope.com/en/products/paris-corner-manaal-edp-u-100-ml",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-TASKEEN-CARAMEL-CASCADE",
        "brand": "Paris Corner",
        "canonical_name": "Taskeen Caramel Cascade",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-TASKEEN-CARAMEL-CASCADE-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/taskeen-caramel-cascade",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/taskeen-caramel-cascade",
        "source_product_url": "https://de.pariscornereurope.com/en/products/taskeen-caramel-cascade",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-VIRILIS",
        "brand": "Paris Corner",
        "canonical_name": "Virilis",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-VIRILIS-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/virilis",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/virilis",
        "source_product_url": "https://de.pariscornereurope.com/en/products/virilis",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-TASKEEN-MARINA",
        "brand": "Paris Corner",
        "canonical_name": "Taskeen Marina",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-TASKEEN-MARINA-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/taskeen-marina",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/taskeen-marina",
        "source_product_url": "https://de.pariscornereurope.com/en/products/paris-corner-taskeen-marina-edp-u-100-ml",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-c3372b4d",
        "brand": "Paris Corner",
        "canonical_name": "Ophidian Sweet Surrender",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-c3372b4d-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/ophidian-sweet-surrender",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/ophidian-sweet-surrender",
        "source_product_url": "https://de.pariscornereurope.com/en/products/ophidian-sweet-surrender",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-038c48d3",
        "brand": "Paris Corner",
        "canonical_name": "Nouf",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-038c48d3-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/nouf",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/nouf",
        "source_product_url": "https://de.pariscornereurope.com/en/products/nouf",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-91232b6e",
        "brand": "Paris Corner",
        "canonical_name": "Ophidian Mango Bliss",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-91232b6e-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/ophidian-mango-bliss",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/ophidian-mango-bliss",
        "source_product_url": "https://de.pariscornereurope.com/products/ophidian-mango-bliss",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-PARIS-CORNER-c3e787e0",
        "brand": "Paris Corner",
        "canonical_name": "Rifaaqat",
        "family_id": "paris_corner_catalog",
        "variant_id": "SHV-SH-PARIS-CORNER-c3e787e0-85-EDP",
        "size_ml": 85,
        "concentration": "Eau de Parfum",
        "source_url": "https://www.pariscornerperfumes.com/products/rifaaqat",
        "source_evidence_url": "https://www.pariscornerperfumes.com/products/rifaaqat",
        "source_product_url": "https://de.pariscornereurope.com/en/products/paris-corner-rifaaqat-edp-u-85-ml",
        "source_size_evidence_url": null
    },
    {
        "product_id": "SH-ARMAF-b6b77ff6",
        "brand": "Armaf",
        "canonical_name": "Club de Nuit Intense Man Pure Parfum",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-b6b77ff6-150-PARFUM",
        "size_ml": 150,
        "concentration": "Parfum",
        "source_url": "https://armaf.com/products/armaf-club-de-nuit-intense-man-pure-perfume",
        "source_evidence_url": "https://armaf.com/products/armaf-club-de-nuit-intense-man-pure-perfume",
        "source_product_url": "https://armaf.com/products/armaf-club-de-nuit-intense-man-pure-perfume",
        "source_size_evidence_url": "https://armaf.eu/products/armaf-club-de-nuit-intense-man-pure-perfume"
    },
    {
        "product_id": "SH-ARMAF-b6b77ff6",
        "brand": "Armaf",
        "canonical_name": "Club de Nuit Intense Man Pure Parfum",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-b6b77ff6-200-PARFUM",
        "size_ml": 200,
        "concentration": "Parfum",
        "source_url": "https://armaf.com/products/armaf-club-de-nuit-intense-man-pure-perfume",
        "source_evidence_url": "https://armaf.com/products/armaf-club-de-nuit-intense-man-pure-perfume",
        "source_product_url": "https://armaf.com/products/armaf-club-de-nuit-intense-man-pure-perfume",
        "source_size_evidence_url": "https://armaf.eu/products/armaf-club-de-nuit-intense-man-pure-perfume"
    },
    {
        "product_id": "SH-ARMAF-b3967c31",
        "brand": "Armaf",
        "canonical_name": "Club de Nuit Bling",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-b3967c31-75-EDP",
        "size_ml": 75,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/club-de-nuit-bling",
        "source_evidence_url": "https://armaf.com/products/club-de-nuit-bling",
        "source_product_url": "https://armaf.com/products/club-de-nuit-bling",
        "source_size_evidence_url": "https://armaf.eu/products/club-de-nuit-bling"
    },
    {
        "product_id": "SH-ARMAF-3730ce35",
        "brand": "Armaf",
        "canonical_name": "Club de Nuit Lionheart Man",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-3730ce35-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/cdn-lion-heart-man-spr",
        "source_evidence_url": "https://armaf.com/products/cdn-lion-heart-man-spr",
        "source_product_url": "https://armaf.com/products/cdn-lion-heart-man-spr",
        "source_size_evidence_url": "https://cz.armaf.eu/en/products/club-de-nuit-lion-heart-man"
    },
    {
        "product_id": "SH-ARMAF-8a8dfbb3",
        "brand": "Armaf",
        "canonical_name": "Club de Nuit Lionheart Woman",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-8a8dfbb3-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/cdn-lion-heart-spr",
        "source_evidence_url": "https://armaf.com/products/cdn-lion-heart-spr",
        "source_product_url": "https://armaf.com/products/cdn-lion-heart-spr",
        "source_size_evidence_url": "https://cz.armaf.eu/en/products/club-de-nuit-lion-heart-woman"
    },
    {
        "product_id": "SH-ARMAF-4e9fde0c",
        "brand": "Armaf",
        "canonical_name": "Club de Nuit Maleka",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-4e9fde0c-105-EDP",
        "size_ml": 105,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/club-de-nuit-maleka",
        "source_evidence_url": "https://armaf.com/products/club-de-nuit-maleka",
        "source_product_url": "https://armaf.com/products/club-de-nuit-maleka",
        "source_size_evidence_url": "https://fr.armaf.eu/products/club-de-nuit-maleka"
    },
    {
        "product_id": "SH-ARMAF-3810c777",
        "brand": "Armaf",
        "canonical_name": "Infinity Silver",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-3810c777-105-EDP",
        "size_ml": 105,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/infinity-spr-1",
        "source_evidence_url": "https://armaf.com/products/infinity-spr-1",
        "source_product_url": "https://armaf.com/products/infinity-spr-1",
        "source_size_evidence_url": "https://armaf.eu/products/infinity-silver-1"
    },
    {
        "product_id": "SH-ARMAF-d1a51dbe",
        "brand": "Armaf",
        "canonical_name": "Ombre D'Or",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-d1a51dbe-75-EDP",
        "size_ml": 75,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/ombre-dor",
        "source_evidence_url": "https://armaf.com/products/ombre-dor",
        "source_product_url": "https://armaf.com/products/ombre-dor",
        "source_size_evidence_url": "https://cz.armaf.eu/en/products/ombre-dor"
    },
    {
        "product_id": "SH-ARMAF-8b8e5648",
        "brand": "Armaf",
        "canonical_name": "Island Bliss",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-8b8e5648-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/island-bliss-delights-spr",
        "source_evidence_url": "https://armaf.com/products/island-bliss-delights-spr",
        "source_product_url": "https://armaf.com/products/island-bliss-delights-spr",
        "source_size_evidence_url": "https://cz.armaf.eu/en/products/delights-island-bliss"
    },
    {
        "product_id": "SH-ARMAF-ff1a16c2",
        "brand": "Armaf",
        "canonical_name": "Yum Yum",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-ff1a16c2-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/yum-yum-spr",
        "source_evidence_url": "https://armaf.com/products/yum-yum-spr",
        "source_product_url": "https://armaf.com/products/yum-yum-spr",
        "source_size_evidence_url": "https://cz.armaf.eu/en/products/delights-yum-yum"
    },
    {
        "product_id": "SH-ARMAF-78579c03",
        "brand": "Armaf",
        "canonical_name": "Odyssey Marshmallow",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-78579c03-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/odyssey-marshmallow",
        "source_evidence_url": "https://armaf.com/products/odyssey-marshmallow",
        "source_product_url": "https://armaf.com/products/odyssey-marshmallow",
        "source_size_evidence_url": "https://cz.armaf.eu/en/products/odyssey-marshmallow-gourmand-edition"
    },
    {
        "product_id": "SH-ARMAF-7becf4c9",
        "brand": "Armaf",
        "canonical_name": "Odyssey Toffee Coffee",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-7becf4c9-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/odyssey-toffee-coffee",
        "source_evidence_url": "https://armaf.com/products/odyssey-toffee-coffee",
        "source_product_url": "https://armaf.com/products/odyssey-toffee-coffee",
        "source_size_evidence_url": "https://cz.armaf.eu/en/products/odyssey-toffee-coffee-cafe-edition"
    },
    {
        "product_id": "SH-ARMAF-38558c30",
        "brand": "Armaf",
        "canonical_name": "Odyssey Black Forest",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-38558c30-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/odyssey-toffee-coffee-copy-1",
        "source_evidence_url": "https://armaf.com/products/odyssey-toffee-coffee-copy-1",
        "source_product_url": "https://armaf.com/products/odyssey-toffee-coffee-copy-1",
        "source_size_evidence_url": "https://cz.armaf.eu/en/products/odyssey-black-forest-dessert-edition"
    },
    {
        "product_id": "SH-ARMAF-e1349118",
        "brand": "Armaf",
        "canonical_name": "Odyssey Go Mango",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-e1349118-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/odyssey-go-mango",
        "source_evidence_url": "https://armaf.com/products/odyssey-go-mango",
        "source_product_url": "https://armaf.com/products/odyssey-go-mango",
        "source_size_evidence_url": "https://cz.armaf.eu/en/products/odyssey-go-mango-tropical-collection-1"
    },
    {
        "product_id": "SH-ARMAF-fa82f8c8",
        "brand": "Armaf",
        "canonical_name": "Odyssey Artisto",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-fa82f8c8-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/odyssey-artisto",
        "source_evidence_url": "https://armaf.com/products/odyssey-artisto",
        "source_product_url": "https://armaf.com/products/odyssey-artisto",
        "source_size_evidence_url": "https://cz.armaf.eu/en/products/odyssey-artisto-the-red-edition"
    },
    {
        "product_id": "SH-ARMAF-ODYSSEY-FRENCH-KISS",
        "brand": "Armaf",
        "canonical_name": "Odyssey French Kiss",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-ODYSSEY-FRENCH-KISS-60-EDP",
        "size_ml": 60,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/odyssey-french-kiss",
        "source_evidence_url": "https://armaf.com/products/odyssey-french-kiss",
        "source_product_url": "https://armaf.com/products/odyssey-french-kiss",
        "source_size_evidence_url": "https://cz.armaf.eu/products/odyssey-french-kiss"
    },
    {
        "product_id": "SH-ARMAF-ODYSSEY-EAU-DE-MONTAGNE",
        "brand": "Armaf",
        "canonical_name": "Odyssey Eau de Montagne",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-ODYSSEY-EAU-DE-MONTAGNE-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/odyssey-eau-de-montagne",
        "source_evidence_url": "https://armaf.com/products/odyssey-eau-de-montagne",
        "source_product_url": "https://armaf.com/products/odyssey-eau-de-montagne",
        "source_size_evidence_url": "https://cz.armaf.eu/products/odyssey-eau-de-montagne-mountain-edition"
    },
    {
        "product_id": "SH-ARMAF-386ff57b",
        "brand": "Armaf",
        "canonical_name": "Odyssey Ba Ha Mas",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-386ff57b-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://armaf.com/products/odyssey-ba-ha-mas",
        "source_evidence_url": "https://armaf.com/products/odyssey-ba-ha-mas",
        "source_product_url": "https://armaf.com/products/odyssey-ba-ha-mas",
        "source_size_evidence_url": "https://cz.armaf.eu/products/odyssey-ba-ha-mas"
    },
    {
        "product_id": "SH-ARMAF-ODYSSEY-SPECTRA-RAINBOW-EDITION",
        "brand": "Armaf",
        "canonical_name": "Odyssey Spectra Rainbow Edition",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-ODYSSEY-SPECTRA-RAINBOW-EDITION-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://cz.armaf.eu/products/odyssey-spectra-rainbow-edition",
        "source_evidence_url": "https://cz.armaf.eu/products/odyssey-spectra-rainbow-edition",
        "source_product_url": "https://cz.armaf.eu/products/odyssey-spectra-rainbow-edition",
        "source_size_evidence_url": "https://cz.armaf.eu/products/odyssey-spectra-rainbow-edition"
    },
    {
        "product_id": "SH-ARMAF-ODYSSEY-DUBAI-CHOCOLAT",
        "brand": "Armaf",
        "canonical_name": "Odyssey Dubai Chocolat",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-ODYSSEY-DUBAI-CHOCOLAT-60-EDP",
        "size_ml": 60,
        "concentration": "Eau de Parfum",
        "source_url": "https://cz.armaf.eu/products/odyssey-dubai-chocolat",
        "source_evidence_url": "https://cz.armaf.eu/products/odyssey-dubai-chocolat",
        "source_product_url": "https://cz.armaf.eu/products/odyssey-dubai-chocolat",
        "source_size_evidence_url": "https://cz.armaf.eu/products/odyssey-dubai-chocolat"
    },
    {
        "product_id": "SH-ARMAF-ODYSSEY-DUBAI-CHOCOLAT",
        "brand": "Armaf",
        "canonical_name": "Odyssey Dubai Chocolat",
        "family_id": "armaf_catalog",
        "variant_id": "SHV-SH-ARMAF-ODYSSEY-DUBAI-CHOCOLAT-100-EDP",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "source_url": "https://cz.armaf.eu/products/odyssey-dubai-chocolat",
        "source_evidence_url": "https://cz.armaf.eu/products/odyssey-dubai-chocolat",
        "source_product_url": "https://cz.armaf.eu/products/odyssey-dubai-chocolat",
        "source_size_evidence_url": "https://cz.armaf.eu/products/odyssey-dubai-chocolat"
    }
]

NEW_PRODUCTS = [
    {"product_id": "SH-ARMAF-ODYSSEY-SPECTRA-RAINBOW-EDITION", "canonical_name": "Odyssey Spectra Rainbow Edition"},
    {"product_id": "SH-ARMAF-ODYSSEY-DUBAI-CHOCOLAT", "canonical_name": "Odyssey Dubai Chocolat"},
]


class ArmafParisCornerVariantGapTests(unittest.TestCase):
    def test_every_expected_official_variant_is_present_with_source_provenance(self):
        families = {f["family_id"]: f for f in REGISTRY["families"]}
        for expected in EXPECTED_VARIANTS:
            with self.subTest(variant=expected["variant_id"]):
                product = next(p for p in CATALOG["products"] if p["product_id"] == expected["product_id"])
                variant = next(v for v in CATALOG["variants"] if v["variant_id"] == expected["variant_id"])
                self.assertEqual(variant.get("product_id"), expected["product_id"])
                self.assertEqual(variant.get("size_ml"), expected["size_ml"])
                self.assertEqual(variant.get("concentration"), expected["concentration"])
                for field in ("source_url", "source_evidence_url", "source_product_url", "source_size_evidence_url"):
                    if expected.get(field):
                        self.assertEqual(variant.get(field), expected[field])
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertIn(expected["size_ml"], product.get("formats_ml", []))
                family = families[expected["family_id"]]
                rows = [r for r in family["products"] if r.get("canonical_name") == expected["canonical_name"]]
                self.assertEqual(len(rows), 1)
                self.assertIn(expected["size_ml"], rows[0].get("formats_ml", []))

    def test_new_armaf_products_have_one_canonical_identity_and_registry_row(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog")
        for expected in NEW_PRODUCTS:
            with self.subTest(product=expected["canonical_name"]):
                products = [p for p in CATALOG["products"] if p.get("product_id") == expected["product_id"]]
                self.assertEqual(len(products), 1)
                self.assertEqual(products[0].get("canonical_name"), expected["canonical_name"])
                rows = [r for r in family["products"] if r.get("canonical_name") == expected["canonical_name"]]
                self.assertEqual(len(rows), 1)

    def test_catalog_variant_identity_integrity_remains_unique(self):
        products = CATALOG["products"]
        variants = CATALOG["variants"]
        self.assertEqual(len({p["product_id"] for p in products}), len(products))
        self.assertEqual(len({v["variant_id"] for v in variants}), len(variants))
        tuples = [(v["product_id"], v["size_ml"], v.get("concentration", "")) for v in variants]
        self.assertEqual(len(set(tuples)), len(tuples))


if __name__ == "__main__":
    unittest.main()
