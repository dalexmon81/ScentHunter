"""Official-source name verification for Maison Asrar records without variant specs."""
import json
import unittest
from pathlib import Path

BACKEND=Path(__file__).resolve().parents[1]
CATALOG=json.loads((BACKEND/"product_catalog.json").read_text(encoding="utf-8"))
REGISTRY=json.loads((BACKEND/"family_registry.json").read_text(encoding="utf-8"))
EXPECTED={
 "Faris Al Arab":("SH-MAISON-ASRAR-9dfce2f6","https://maisonasrar.com/products/faris-al-arab"),
 "III Thriller":("SH-MAISON-ASRAR-6d0c1431","https://maisonasrar.com/products/iii-thriller"),
 "Muharib":("SH-MAISON-ASRAR-fee4b52e","https://maisonasrar.com/products/muharib"),
 "Hunter":("SH-MAISON-ASRAR-066e4606","https://maisonasrar.com/products/maison-asrar-hunter-eau-de-parfum-100ml"),
}
class MaisonAsrarNameVerificationTests(unittest.TestCase):
 def test_official_product_pages_verify_existing_canonical_names_only(self):
  family=next(f for f in REGISTRY["families"] if f["family_id"]=="maison_asrar_catalog")
  family_rows={p["canonical_name"]:p for p in family["products"]}
  for name,(pid,url) in EXPECTED.items():
   with self.subTest(product=name):
    rows=[p for p in CATALOG["products"] if p.get("product_id")==pid and p.get("brand")=="Maison Asrar"]
    self.assertEqual(len(rows),1);p=rows[0]
    self.assertEqual(p["canonical_name"],name);self.assertEqual(p["identity_status"],"source_verified_name")
    self.assertEqual(p["source_url"],url);self.assertEqual(p["source_product_url"],url);self.assertEqual(p["source_evidence_url"],url)
    self.assertNotIn("concentration",p);self.assertNotIn("formats_ml",p)
    self.assertEqual([v for v in CATALOG["variants"] if v.get("product_id")==pid],[])
    self.assertNotIn("formats_ml",family_rows[name])
if __name__=="__main__":unittest.main()
