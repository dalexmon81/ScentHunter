# backend/product_normalizer.py
"""
Normalizzazione e raggruppamento dei nomi dei profumi.
Estrae brand, variant, type e raggruppa varianti equivalenti.
"""
import re
import unicodedata
from typing import List, Dict, Any, Tuple, Optional

NUMBER_WORDS = {
    'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
    'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
}

def extract_brand_variant_type(name: str) -> Tuple[Optional[str], str, Optional[str]]:
    if not name:
        return (None, "", None)
    match = re.match(r'^([^\-]+)\s*-\s*(.+)$', name)
    if match:
        brand = match.group(1).strip()
        rest = match.group(2).strip()
        variant, typ = extract_variant_type(rest)
        return (brand, variant, typ)
    else:
        variant, typ = extract_variant_type(name)
        return (None, variant, typ)

def extract_variant_type(name: str) -> Tuple[str, Optional[str]]:
    type_patterns = [
        r'\b(eau de parfum|eau de toilette|eau de cologne|eau fraîche)\b',
        r'\b(extrait de parfum|extrait)\b',
        r'\b(edp|edt|edc|edf)\b',
        r'\b(parfum|perfume)\b',
        r'\b(intense|extreme|absolu|elixir)\b',
    ]
    typ = None
    variant = name
    for pattern in type_patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            typ = match.group(1).strip()
            variant = re.sub(pattern, '', name, flags=re.IGNORECASE).strip()
            break
    variant = re.sub(r'[\-–—]+\s*$', '', variant).strip()
    return (variant, typ)

def normalize_name(name: str) -> str:
    if not name:
        return ""
    n = name.lower()
    n = re.sub(r'[\u00ae\u00a9\u2122\u2014\u2013\u2010\u2011]', '', n)
    n = unicodedata.normalize('NFKD', n)
    n = re.sub(r'[\u0300-\u036f]', '', n)
    n = re.sub(r"\bl['\u2019]?eau\b", 'eau', n)
    stopwords = [
        'eau de parfum', 'eau de toilette', 'eau de cologne', 'eau fraîche',
        'edp', 'edt', 'edc', 'edf',
        'parfum', 'perfume', 'perfum',
        'extrait de parfum', 'extrait',
        'for women', 'for men', 'for her', 'for him', 'pour homme', 'pour femme',
        'intense', 'extreme', 'absolu', 'absolue', 'elixir',
    ]
    for sw in stopwords:
        n = n.replace(sw, '')
    for word, num in NUMBER_WORDS.items():
        n = re.sub(r'\b' + word + r'\b', num, n)
    n = re.sub(r'(\d)\s+([a-z])', r'\1\2', n)
    n = re.sub(r'([a-z])\s+(\d)', r'\1\2', n)
    n = re.sub(r'\s+', ' ', n).strip()
    n = re.sub(r"[^\w\s]", '', n)
    return n

def group_results_by_normalized_name(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped = {}
    for result in results:
        name = result.get('name', '')
        normalized = normalize_name(name)
        if not normalized:
            continue
        brand, variant, typ = extract_brand_variant_type(name)
        key = normalized
        if key not in grouped:
            grouped[key] = {
                'brand': brand,
                'variant': variant,
                'type': typ,
                'name': name,
                'normalized_name': normalized,
                'offers': [result]
            }
        else:
            grouped[key]['offers'].append(result)
            if len(name) < len(grouped[key]['name']):
                grouped[key]['name'] = name
                grouped[key]['brand'] = brand
                grouped[key]['variant'] = variant
                grouped[key]['type'] = typ
    grouped_list = list(grouped.values())
    grouped_list.sort(key=lambda x: len(x['offers']), reverse=True)
    return grouped_list

def deduplicate_offers(offers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped = []
    for offer in offers:
        key = (offer.get('store', ''), offer.get('url', ''))
        if key not in seen:
            seen.add(key)
            deduped.append(offer)
    return deduped

def normalize_and_group(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped = group_results_by_normalized_name(results)
    for product in grouped:
        product['offers'] = deduplicate_offers(product['offers'])
    return grouped
