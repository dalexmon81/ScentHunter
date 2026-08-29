"""
Product Normalizer per ScentHunter
----------------------------------
Questo file serve SOLO per raggruppare risultati con lo stesso nome normalizzato.
NON deve fare estrazione del brand, variante, concentrazione, ecc.
Quella logica rimane in main.py.

Regole di normalizzazione:
- Lowercase
- Rimuove punteggiatura extra
- Rimuove "eau de", "parfum", "perfume" (solo per raggruppamento)
- MANTIENE "for him", "for her", "pour homme", "pour femme" (distinguono varianti!)
- MANTIENE "limited edition", "extrait", ecc. (distinguono varianti!)
"""

import re
from typing import List, Dict, Any


def normalize_name(name: str) -> str:
    """
    Normalizza il nome del prodotto per il raggruppamento.
    MANTIENE le informazioni che distinguono le varianti.
    """
    if not name:
        return ""
    
    # Lowercase
    result = name.lower().strip()
    
    # Rimuove punteggiatura extra (ma mantiene trattini e slash)
    result = re.sub(r'[^\w\s\/-]', ' ', result)
    
    # Rimuove solo parole generiche che NON distinguono prodotti
    # NON rimuoviamo: for him, for her, pour homme, pour femme, limited, edition, extrait
    generic_words = [
        'eau', 'de', 'parfum', 'perfume', 'spray', 'edp', 'edt', 'edc',
        'ml', 'milliliters', 'millilitre', 'ounces', 'oz', 'fl',
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been', 'be',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare', 'ought', 'used', 'going'
    ]
    
    words = result.split()
    filtered_words = [w for w in words if w not in generic_words]
    result = ' '.join(filtered_words)
    
    # Pulizia spazi extra
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result


def group_products(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Raggruppa prodotti con lo stesso nome normalizzato.
    NON modifica brand, variant, concentration, gender, format.
    Quella logica rimane in main.py.
    """
    if not products:
        return []
    
    # Raggruppa per nome normalizzato
    groups: Dict[str, List[Dict[str, Any]]] = {}
    
    for product in products:
        name = product.get('name', '')
        normalized = normalize_name(name)
        
        if normalized not in groups:
            groups[normalized] = []
        
        groups[normalized].append(product)
    
    # Per ogni gruppo, crea un risultato con tutti i prezzi
    results = []
    
    for normalized, group in groups.items():
        if not group:
            continue
        
        # Prendi il primo prodotto come base
        base_product = group[0].copy()
        
        # Raccogli tutti i prezzi da tutti i prodotti nel gruppo
        all_prices = []
        for product in group:
            price = product.get('price')
            shop = product.get('shop')
            link = product.get('link')
            shipping = product.get('shipping')
            
            if price is not None:
                all_prices.append({
                    'price': price,
                    'shop': shop,
                    'link': link,
                    'shipping': shipping
                })
        
        # Ordina per prezzo
        all_prices.sort(key=lambda x: x['price'] if x['price'] is not None else float('inf'))
        
        # Crea il risultato
        result = {
            'name': base_product.get('name', ''),
            'brand': base_product.get('brand', ''),
            'variant': base_product.get('variant', ''),
            'concentration': base_product.get('concentration', ''),
            'gender': base_product.get('gender', ''),
            'format': base_product.get('format', ''),
            'prices': all_prices,
            'min_price': min((p['price'] for p in all_prices if p['price'] is not None), default=None)
        }
        
        results.append(result)
    
    return results
