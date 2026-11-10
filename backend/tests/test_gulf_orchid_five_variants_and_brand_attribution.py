"""Regression coverage for Gulf Orchid variants and Maison Asrar attribution."""
import json, unittest
from pathlib import Path
BACKEND=Path(__file__).resolve().parents[1]
CATALOG=json.loads((BACKEND/"product_catalog.json").read_text(encoding="utf-8"))
REGISTRY=json.loads((BACKEND/"family_registry.json").read_text(encoding="utf-8"))
EXPECTED={
 "Al Qasr":{"id":"SH-GULF-ORCHID-4133b3ae","size":100,"url":"https://shop-gulforchid.com/products/al-qasr-silver","brand":"Gulf Orchid"},
 "Exotic Oud":{"id":"SH-GULF-ORCHID-EXOTIC-OUD","size":100,"url":"https://shop-gulforchid.com/products/exotic_oud_eau_de_parfum","brand":"Gulf Orchid"},
 "Vanilla Latte":{"id":"SH-GULF-ORCHID-VANILLA-LATTE","size":100,"url":"https://shop-gulforchid.com/products/vanilla_latte_eau_de_parfum","brand":"Gulf Orchid"},
 "Cookie Bite":{"id":"SH-GULF-ORCHID-COOKIE-BITE","size":100,"url":"https://shop-gulforchid.com/products/cookie-bite","brand":"Gulf Orchid"},
 "Vanilla Aura":{"id":"SH-MAISON-ASRAR-bab16c06","size":100,"url":"https://shop-gulforchid.com/products/vanilla-aura","brand":"Maison Asrar"},
}
class GulfOrchidAndMaisonAsrarAttributionTests(unittest.TestCase):
 def test_five_explicit_variants_have_source_and_family_coverage(self):
  for name,e in EXPECTED.items():
   with self.subTest(product=name):
    rows=[p for p in CATALOG["products"] if p.get("product_id")==e["id"] and p.get("canonical_name")==name]
    self.assertEqual(len(rows),1); p=rows[0]
    self.assertEqual(p["brand"],e["brand"]); self.assertEqual(p["identity_status"],"source_verified_name")
    self.assertEqual(p["source_url"],e["url"]); self.assertEqual(p["source_product_url"],e["url"]); self.assertEqual(p["source_evidence_url"],e["url"])
    self.assertEqual(p["concentration"],"Eau de Parfum"); self.assertEqual(p["formats_ml"],[e["size"]])
    vs=[v for v in CATALOG["variants"] if v.get("product_id")==e["id"]]
    self.assertEqual(len(vs),1); self.assertEqual(vs[0]["size_ml"],e["size"])
    self.assertEqual(vs[0]["concentration"],"Eau de Parfum"); self.assertNotIn("gtin",vs[0])
    family=next(f for f in REGISTRY["families"] if f.get("family_id")==p["family_id"])
    row=next(x for x in family["products"] if x.get("canonical_name")==name)
    self.assertIn(e["size"],row.get("formats_ml",[]))
 def test_tahara_name_is_verified_but_variant_attributes_are_deferred(self):
  p=next(p for p in CATALOG["products"] if p.get("product_id")=="SH-GULF-ORCHID-TAHARA-VANILLA-MUSK")
  url="https://shop-gulforchid.com/products/musk-eau-de-parfum-60-ml"
  self.assertEqual(p["identity_status"],"source_verified_name")
  self.assertEqual(p["source_url"],url); self.assertEqual(p["source_product_url"],url); self.assertEqual(p["source_evidence_url"],url)
  self.assertNotIn("concentration",p); self.assertNotIn("formats_ml",p)
  self.assertEqual([v for v in CATALOG["variants"] if v.get("product_id")==p["product_id"]],[])
  family=next(f for f in REGISTRY["families"] if f["family_id"]=="gulf_orchid_catalog")
  row=next(x for x in family["products"] if x["canonical_name"]=="Tahara Vanilla Musk")
  self.assertNotIn("formats_ml",row)
 def test_vanilla_voyage_is_attributed_to_maison_asrar_without_guessing_attributes(self):
  p=next(p for p in CATALOG["products"] if p.get("product_id")=="SH-MAISON-ASRAR-19d98178")
  self.assertEqual(p["canonical_name"],"Vanilla Voyage"); self.assertEqual(p["brand"],"Maison Asrar")
  self.assertEqual(p["identity_status"],"source_verified_name")
  self.assertEqual(p["source_url"],"https://shop-gulforchid.com/products/maison-asrar-vanilla-voyage-eau-de-parfum")
  self.assertNotIn("concentration",p); self.assertNotIn("formats_ml",p)
  self.assertEqual([v for v in CATALOG["variants"] if v.get("product_id")==p["product_id"]],[])
 def test_misattributed_gulf_orchid_duplicates_are_removed(self):
  ids={p.get("product_id") for p in CATALOG["products"]}
  self.assertNotIn("SH-GULF-ORCHID-2e9b4429",ids); self.assertNotIn("SH-GULF-ORCHID-0aca84c2",ids)
  gulf=next(f for f in REGISTRY["families"] if f.get("family_id")=="gulf_orchid_catalog")
  self.assertFalse(any(p.get("canonical_name") in {"Vanilla Aura","Vanilla Voyage"} for p in gulf["products"]))
if __name__=="__main__": unittest.main()
