import json
from pathlib import Path

CATALOG_FILE = (
    Path(__file__).resolve().parent.parent
    / "database"
    / "perfumes.json"
)


def load_catalog():
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data.get("perfumes", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def find_perfume(brand, name):
    brand = (brand or "").strip().lower()
    name = (name or "").strip().lower()

    for perfume in load_catalog():
        perfume_brand = str(
            perfume.get("brand", "")
        ).strip().lower()

        perfume_name = str(
            perfume.get("name", "")
        ).strip().lower()

        if perfume_brand == brand and perfume_name == name:
            return perfume

    return None


def get_image(brand, name):
    perfume = find_perfume(brand, name)

    if perfume:
        return perfume.get("image")

    return None