""""ScentHunter central product identity matcher."""
from __future__ import annotations
import re, unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

def normalize(value: Any) -> str:
    value=str(value or "").strip().lower()
    value=unicodedata.normalize("NFKD", value)
    value="".join(ch for ch in value if not unicodedata.combining(ch))
    value=re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value=re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def first_value(item: Dict[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value=item.get(key)
        if value is not None and str(value).strip(): return str(value).strip()
    return ""

def identifier(item: Dict[str, Any], keys: Sequence[str]) -> str:
    value=first_value(item, keys)
    return normalize(value).replace(" ", "") if value else ""

def size_ml(item: Dict[str, Any]) -> Optional[float]:
    explicit=item.get("size_ml")
    if explicit not in (None, ""):
        try: return float(str(explicit).replace(",", "."))
        except (TypeError, ValueError): pass
    text=" ".join(str(item.get(k) or "") for k in ("name","title","product_name","size","format"))
    m=re.search(r"\b(\d{1,4}(?:[.,]\d+)?)\s*(ml|cl)\b", text, re.I)
    if not m: return None
    value=float(m.group(1).replace(",", "."))
    return value*10 if m.group(2).lower()=="cl" else value

@dataclass(frozen=True)
class CatalogProduct:
    catalog_id: str
    brand: str
    name: str
    aliases: Tuple[str,...]=()
    formats_ml: Tuple[float,...]=()
    gtins: Tuple[str,...]=()
    mpns: Tuple[str,...]=()
    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(
            str(data.get("id") or data.get("catalog_id") or "").strip(),
            str(data.get("brand") or "").strip(),
            str(data.get("name") or "").strip(),
            tuple(str(x).strip() for x in (data.get("aliases") or []) if str(x).strip()),
            tuple(float(x) for x in (data.get("formats_ml") or []) if str(x).strip()),
            tuple(identifier({"v":x},("v",)) for x in (data.get("gtins") or data.get("ean") or []) if str(x).strip()),
            tuple(identifier({"v":x},("v",)) for x in (data.get("mpns") or data.get("mpn") or []) if str(x).strip()),
        )
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
    BRAND_KEYS=("brand","manufacturer","maker")
    NAME_KEYS=("name","title","product_name")
    def __init__(self,catalog:Iterable[Dict[str,Any]|CatalogProduct]):
        self.catalog=[x if isinstance(x,CatalogProduct) else CatalogProduct.from_dict(x) for x in catalog]
        self._by_gtin={}; self._by_mpn={}; self._by_catalog_id={}
        for p in self.catalog:
            if p.catalog_id: self._by_catalog_id[normalize(p.catalog_id)]=p
            for x in p.gtins: self._by_gtin.setdefault(x,[]).append(p)
            for x in p.mpns: self._by_mpn.setdefault(x,[]).append(p)
    def match(self,offer:Dict[str,Any])->Optional[Dict[str,Any]]:
        p,method,score=self._best_match(offer)
        if p is None:return None
        r=dict(offer); r.update(catalog_id=p.catalog_id,canonical_brand=p.brand,canonical_name=p.name,match_method=method,match_score=round(score,4),product_identity=p.catalog_id)
        s=size_ml(offer)
        if s is not None:r["size_ml"]=s
        r["variant_id"]=f"{p.catalog_id}:{s:g}" if s is not None else p.catalog_id
        return r
    def _best_match(self,offer):
        g=identifier(offer,self.GTIN_KEYS)
        if g in self._by_gtin and len(self._by_gtin[g])==1:return self._by_gtin[g][0],"gtin",1.0
        m=identifier(offer,self.MPN_KEYS)
        if m in self._by_mpn and len(self._by_mpn[m])==1:return self._by_mpn[m][0],"mpn",.99
        c=identifier(offer,self.CATALOG_KEYS)
        if c in self._by_catalog_id:return self._by_catalog_id[c],"catalog_id",.98
        brand=normalize(first_value(offer,self.BRAND_KEYS)); name=normalize(first_value(offer,self.NAME_KEYS))
        if not name:return None,"none",0.0
        best=(None,0.0,"none")
        for p in self.catalog:
            score=self._text_score(brand,name,p)
            if score>best[1]:best=(p,score,"exact_name" if score>=.94 else "token_score")
        if best[0] is None or best[1]<.86:return None,"none",best[1]
        return best[0], best[2], best[1]
    @staticmethod
    def _text_score(brand,name,p):
        brand_score=1.0 if brand and brand==p.normalized_brand else 0.0
        best=0.0
        for candidate in (p.normalized_name,)+p.normalized_aliases:
            if not candidate:continue
            if name==candidate:best=max(best,1.0);continue
            a=set(name.split()); b=set(candidate.split()); inter=len(a&b)
            recall=inter/len(b) if b else 0; precision=inter/max(1,len(a))
            f=(2*recall*precision/(recall+precision)) if recall+precision else 0
            if candidate in name or name in candidate:f=max(f,.92)
            best=max(best,f)
        return .45+.55*best if brand_score else .95*best

def offer_key(offer:Dict[str,Any])->Tuple[str,str,str,str]:
    store=normalize(offer.get("store") or offer.get("source")); identity=normalize(offer.get("product_identity") or offer.get("catalog_id")); s=size_ml(offer); size="" if s is None else f"{s:g}"; url=str(offer.get("url") or "").split("#",1)[0].split("?",1)[0].strip().lower(); return store,identity,size,url

def attach_matches(offers:Iterable[Dict[str,Any]],catalog:Iterable[Dict[str,Any]|CatalogProduct])->List[Dict[str,Any]]:
    matcher=ProductMatcher(catalog); out=[]
    for offer in offers:
        if isinstance(offer,dict):
            matched=matcher.match(offer)
            if matched is not None:out.append(matched)
    return out
