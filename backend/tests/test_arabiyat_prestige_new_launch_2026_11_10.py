"""Regression coverage for source-backed Arabiyat Prestige launch variants."""
import json, unittest
from pathlib import Path
BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
EXPECTED = {
 "Aariz": ("SH-ARABIYAT-PRESTIGE-00d6e7bc", "https://arabiyatprestige.com/collections/new-launch/products/aariz-100ml", 100),
 "Aariz L’Absolu": ("SH-ARABIYAT-PRESTIGE-5ea21b51", "https://arabiyatprestige.com/collections/new-launch/products/arabiyat-prestige-aariz-l-absolu-edp-100-ml-unisex", 100),
 "Asháa Oud Noir": ("SH-ARABIYAT-PRESTIGE-641acbf3", "https://arabiyatprestige.com/collections/new-launch/products/ashaa-oud-noir-edp-110ml", 110),
 "Kohl Opulence": ("SH-ARABIYAT-PRESTIGE-113b2420", "https://arabiyatprestige.com/collections/new-launch/products/arabiyat-prestige-kohl-opulence-edp-100-ml-unisex", 100),
}
class ArabiyatPrestigeNewLaunchTests(unittest.TestCase):
 def test_each_verified_launch_has_one_canonical_identity(self):
  for name,(pid,url,size) in EXPECTED.items():
   with self.subTest(name=name):
    rows=[p for p in CATALOG["products"] if p.get("brand_name")=="Arabiyat Prestige" and p.get("canonical_name")==name]
    self.assertEqual(len(rows),1); p=rows[0]
    self.assertEqual(p["product_id"],pid); self.assertEqual(p["identity_status"],"source_verified_name")
    self.assertEqual(p["source_product_url"],url); self.assertEqual(p["source_evidence_url"],url)
    self.assertEqual(p["concentration"],"Eau de Parfum"); self.assertEqual(p["formats_ml"],[size])
 def test_explicit_variants_and_family_registry_match(self):
  family=next(f for f in REGISTRY["families"] if f["family_id"]=="arabiyat_prestige_catalog")
  records={p["canonical_name"]:p for p in family["products"]}
  for name,(pid,url,size) in EXPECTED.items():
   with self.subTest(name=name):
    vs=[v for v in CATALOG["variants"] if v.get("product_id")==pid]
    self.assertEqual(len(vs),1); self.assertEqual(vs[0]["size_ml"],size)
    self.assertEqual(vs[0]["concentration"],"Eau de Parfum"); self.assertEqual(vs[0]["source_evidence_url"],url)
    self.assertEqual(records[name]["formats_ml"],[size])
 def test_marwa_size_and_concentration_remain_deferred(self):
  p=next(p for p in CATALOG["products"] if p.get("product_id")=="SH-ARABIYAT-PRESTIGE-7bf3b46e")
  self.assertEqual(p["canonical_name"],"Marwa"); self.assertEqual(p["identity_status"],"source_listed_name")
  self.assertEqual(p["source_url"],"https://arabiyatprestige.com/collections/all")
  self.assertNotIn("source_product_url",p); self.assertNotIn("concentration",p); self.assertNotIn("formats_ml",p)
  self.assertEqual([v for v in CATALOG["variants"] if v.get("product_id")==p["product_id"]],[])
  family=next(f for f in REGISTRY["families"] if f["family_id"]=="arabiyat_prestige_catalog")
  row=next(p for p in family["products"] if p["canonical_name"]=="Marwa")
  self.assertNotIn("formats_ml",row)
if __name__=="__main__": unittest.main()
