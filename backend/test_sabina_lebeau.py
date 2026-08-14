#!/usr/bin/env python3
"""Test Sabina scraper with Le Beau query."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from backend.scrapers.sabina.scraper import search as sabina_search
except ModuleNotFoundError:
    from scrapers.sabina.scraper import search as sabina_search

QUERY = "Le Beau"

print(f"=== Testing Sabina scraper with query: {QUERY} ===\n")

results = sabina_search(QUERY)

print(f"Results count: {len(results)}\n")

for i, r in enumerate(results, 1):
    print(f"{i}. {r.get('name', 'N/A')}")
    print(f"   Brand: {r.get('brand', 'N/A')}")
    print(f"   Price: {r.get('price', 'N/A')}")
    print(f"   URL: {r.get('url', 'N/A')}")
    print()

print(f"=== Done ===")
