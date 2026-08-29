# backend/product_normalizer.py
"""
Normalizzazione e raggruppamento dei nomi dei profumi.
Raggruppa varianti equivalenti (es. "Eau Rosé®®" vs "Eau Rosè®®") in un'unica scheda.
"""
import re
import unicodedata
from typing import List, Dict, Any

NUMBER_WORDS = {
    'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
    'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
    'eleven': '11', 'twelve': '12', 'thirteen': '13', 'fourteen': '14',
    'fifteen': '15', 'sixteen': '16', 'seventeen': '17', 'eighteen': '18',
    'nineteen': '19', 'twenty': '20'
}

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
        if normalized not in grouped:
            grouped[normalized] = {'name': name, 'normalized_name': normalized, 'offers': [result]}
        else:
            grouped[normalized]['offers'].append(result)
            if len(name) < len(grouped[normalized]['name']):
                grouped[normalized]['name'] = name
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
