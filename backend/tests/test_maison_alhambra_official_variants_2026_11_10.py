"""Official Maison Alhambra variant verification from Lattafa's EU store."""
import json
import unittest
from pathlib import Path
BACKEND=Path(__file__).resolve().parents[1]
CATALOG=json.loads((BACKEND/"product_catalog.json").read_text(encoding="utf-8"))
REGISTRY=json.loads((BACKEND/"family_registry.json").read_text(encoding="utf-8"))
EXPECTED={
 "Mysterious Amber":("SH-MAISON-ALHAMBRA-e51860be",80,"https://lattafaparfum.eu/de-de/products/mysterious-amber"),
 "Jean Lowe Vibe":("SH-MAISON-ALHAMBRA-615f53ba",100,"https://lattafaparfum.eu/de-de/products/jean-lowe-vibe"),
 "Jean Lowe Immortal":("SH-MAISON-ALHAMBRA-14a18233",100,"https://lattafaparfum.eu/de-de/products/jean-lowe-immortal"),
}
class MaisonAlhambraOfficialVariantTests(unittest.TestCase):
 def test_three_official_pages_have_exact_size_and_edp(self):
  family=next(f for f in REGISTRY["families"] if f["family_id"]=="maison_alhambra_catalog")
  family_rows={p["canonical_name"]:p for p in family["products"]}
  for name,(pid,size,url) in EXPECTED.items():
   with self.subTest(product=name):
    p=next(p for p in CATALOG["products"] if p.get("product_id")==pid)
    self.assertEqual(p["brand"],"Maison Alhambra");self.assertEqual(p["canonical_name"],name)
    self.assertEqual(p["identity_status"],"source_verified_name")
    self.assertEqual(p["source_url"],url);self.assertEqual(p["source_product_url"],url);self.assertEqual(p["source_evidence_url"],url)
    self.assertEqual(p["concentration"],"Eau de Parfum");self.assertEqual(p["formats_ml"],[size])
    v=next(v for v in CATALOG["variants"] if v.get("product_id")==pid)
    self.assertEqual(v["variant_id"],f"SHV-{pid}-{size}-000")
    self.assertEqual(v["size_ml"],size);self.assertEqual(v["concentration"],"Eau de Parfum")
    self.assertEqual(v["source_url"],url);self.assertEqual(v["source_evidence_url"],url)
    self.assertNotIn("gtin",v);self.assertEqual(family_rows[name]["formats_ml"],[size])
if __name__=="__main__":unittest.main()
