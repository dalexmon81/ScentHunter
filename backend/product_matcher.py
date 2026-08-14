"""ScentHunter central product identity matcher."""
from __future__ import annotations
import re, unicodedata, hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

def normalize(value: Any) -> str:
    value=str(value or "").strip().lower()
    value=unicodedata.normalize("NFKD", value)
    value=re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def stable_auto_id(brand: str, name: str, size_ml: Optional[int] = None, concentration: Optional[str] = None) -> str:
    """
    Generate a stable, deterministic product ID from brand, name, size, and concentration.
    Used for catalog deduplication and matching.
    """
    brand_norm = normalize(brand)
    name_norm = normalize(name)
    size_str = f"{size_ml:04d}" if size_ml else "0000"
    conc_norm = normalize(concentration or "")
    key = f"{brand_norm}|{name_norm}|{size_str}|{conc_norm}"
    hash_hex = hashlib.sha256(key.encode('utf-8')).hexdigest()[:12].upper()
    return f"AUTO-{hash_hex}"

def extract_size_ml(text: str) -> Optional[int]:
    """Extract size in ml from product text."""
    if not text:
        return None
    text = normalize(text)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|millilitri|litri|l|oz|fl\.?\s*oz)", text, re.I)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit in ("l", "litri"):
        return int(value * 1000)
    elif unit in ("oz", "fl. oz", "fl oz"):
        return int(value * 29.5735)
    else:
        return int(value)

@dataclass(frozen=True)
class CatalogProduct:
    catalog_id: str
    brand: str
    name: str
    size_ml: Optional[int] = None
    concentration: Optional[str] = None
    gtins: Tuple[str, ...] = ()
    mpns: Tuple[str, ...] = ()
    aliases: Tuple[str, ...] = ()
    
    @property
    def normalized_brand(self): return normalize(self.brand)
    @property
    def normalized_name(self): return normalize(self.name)
    @property
    def normalized_aliases(self): return tuple(normalize(x) for x in self.aliases)

class ProductMatcher:
    GTIN_KEYS=("gtin","ean","ean13","ean_code","barcode","upc")
    MPN_KEYS=("mpn","manufacturer_part_number","manufacturerNumber")
    CATALOG_KEYS=("catalog_id","master_id","item_group_id","product_id")
    
    def __init__(self, catalog: Iterable[Dict[str, Any]]):
        self.catalog = tuple(self._load_catalog(catalog))
    
    def _load_catalog(self, catalog: Iterable[Dict[str, Any]]) -> Iterable[CatalogProduct]:
        for item in catalog:
            if not isinstance(item, dict):
                continue
            catalog_id = item.get("catalog_id") or item.get("id") or item.get("master_id") or ""
            brand = item.get("brand", "").strip()
            name = item.get("name", "").strip()
            if not brand or not name:
                continue
            size_ml = item.get("size_ml") or extract_size_ml(item.get("name", "") or item.get("full_name", ""))
            concentration = item.get("concentration", "")
            gtins = tuple(str(x) for x in (item.get("gtins") or item.get("ean") or []) if str(x).strip())
            mpns = tuple(str(x) for x in (item.get("mpns") or item.get("mpn") or []) if str(x).strip())
            aliases = tuple(item.get("aliases") or [])
            yield CatalogProduct(
                catalog_id=str(catalog_id),
                brand=brand,
                name=name,
                size_ml=size_ml,
                concentration=concentration,
                gtins=gtins,
                mpns=mpns,
                aliases=aliases
            )
    
    def match(self, offer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        offer_brand = normalize(offer.get("brand", ""))
        offer_name = normalize(offer.get("name", "") or offer.get("title", "") or offer.get("product_name", ""))
        offer_size = offer.get("size_ml") or extract_size_ml(offer.get("name", "") or offer.get("title", ""))
        if not offer_brand or not offer_name:
            return None
        best_match = None
        best_score = 0
        for product in self.catalog:
            score = 0
            if offer_brand != product.normalized_brand:
                brand_match = False
                for alias in product.normalized_aliases:
                    if offer_brand in alias or alias in offer_brand:
                        brand_match = True
                        break
                if not brand_match:
                    continue
            else:
                score += 100
            if offer_name == product.normalized_name:
                score += 200
            elif offer_name in product.normalized_name or product.normalized_name in offer_name:
                score += 150
            else:
                alias_match = False
                for alias in product.normalized_aliases:
                    if offer_name == alias or offer_name in alias or alias in offer_name:
                        alias_match = True
                        score += 100
                        break
                if not alias_match:
                    offer_tokens = set(offer_name.split())
                    product_tokens = set(product.normalized_name.split())
                    overlap = offer_tokens & product_tokens
                    if len(overlap) >= 2:
                        score += 50 + len(overlap) * 10
            if offer_size and product.size_ml and offer_size == product.size_ml:
                score += 50
            if score > best_score and score >= 100:
                best_score = score
                best_match = product
        if best_match:
            return {"catalog_id": best_match.catalog_id, "brand": best_match.brand, "name": best_match.name, "size_ml": best_match.size_ml, "concentration": best_match.concentration, "matched": True}
        return None
