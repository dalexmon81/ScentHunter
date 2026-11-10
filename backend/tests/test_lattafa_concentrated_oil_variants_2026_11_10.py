"""Official Lattafa concentrated-oil variant evidence."""
import json
import unittest
from pathlib import Path
BACKEND=Path(__file__).resolve().parents[1]
CATALOG=json.loads((BACKEND/"product_catalog.json").read_text(encoding="utf-8"))
REGISTRY=json.loads((BACKEND/"family_registry.json").read_text(encoding="utf-8"))
EXPECTED={
 "Abraaj":("SH-LATTAFA-ABRAAJ","SHV-SH-LATTAFA-ABRAAJ-20-000","https://lattafa.com/product/abraaj-concentrated-oil/"),
 "Haakim":("SH-LATTAFA-HAAKIM","SHV-SH-LATTAFA-HAAKIM-20-000","https://lattafa.com/product/haakim-concentrated-oil/"),
 "Amoura":("SH-LATTAFA-AMOURA","SHV-SH-LATTAFA-AMOURA-20-000","https://lattafa.com/product/amoura-concentrated-oil/"),
}
class LattafaConcentratedOilTests(unittest.TestCase):
 def test_three_official_twenty_ml_variants(self):
  family=next(f for f in REGISTRY["families"] if f["family_id"]=="lattafa_catalog")
  rows={p["canonical_name"]:p for p in family["products"]}
  for name,(pid,vid,url) in EXPECTED.items():
   with self.subTest(product=name):
    p=next(p for p in CATALOG["products"] if p.get("product_id")==pid)
    self.assertEqual(p["identity_status"],"source_verified_name")
    self.assertEqual(p["source_url"],url);self.assertEqual(p["source_product_url"],url);self.assertEqual(p["source_evidence_url"],url)
    self.assertEqual(p["concentration"],"Concentrated Oil");self.assertEqual(p["formats_ml"],[20])
    v=next(v for v in CATALOG["variants"] if v.get("variant_id")==vid)
    self.assertEqual(v["product_id"],pid);self.assertEqual(v["size_ml"],20);self.assertEqual(v["concentration"],"Concentrated Oil")
    self.assertEqual(v["source_url"],url);self.assertEqual(v["source_evidence_url"],url)
    self.assertNotIn("gtin",v);self.assertEqual(rows[name]["formats_ml"],[20])
 def test_maitha_name_and_product_type_verified_without_inventing_size(self):
  p=next(p for p in CATALOG["products"] if p.get("product_id")=="SH-LATTAFA-MAITHA")
  url="https://lattafa.com/product/maitha-concentrated-oil/"
  self.assertEqual(p["identity_status"],"source_verified_name")
  self.assertEqual(p["source_url"],url);self.assertEqual(p["source_product_url"],url);self.assertEqual(p["source_evidence_url"],url)
  self.assertEqual(p["concentration"],"Concentrated Oil")
  self.assertNotIn("formats_ml",p)
  self.assertEqual([v for v in CATALOG["variants"] if v.get("product_id")==p["product_id"]],[])
if __name__=="__main__":unittest.main()
