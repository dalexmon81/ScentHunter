import os, unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.connectors.parfumcity import ParfumCityConnector

class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_variants_keep_distinct_ids_and_currency_unverified(self):
  product={"id":20,"title":"Example Eau de Parfum","vendor":"Example","variants":[{"id":201,"title":"50 ml","price":"30.00","available":True},{"id":202,"title":"100 ml","price":"45.00","available":True}]}
  def make(p,v,u,q):
   return {"name":p["title"]+" "+v["title"],"url":u,"source":{"source_name":p["title"],"source_brand":p["vendor"],"url":u},"identity":{"store_product_id":{"value":p["id"]},"store_variant_id":{"value":v["id"]}},"attributes":{"size_ml":{"value":int(v["title"].split()[0])}},"offer":{"price":float(v["price"]),"currency":"EUR","availability":"in_stock"}}
  scraper=SimpleNamespace(discover=lambda s,q: (["https://www.parfumcity.nl/products/example"],[],True),product_json=lambda s,u:product,make_item=make)
  c=ParfumCityConnector(scraper)
  with patch.dict(os.environ,{"SCENTHUNTER_DISCOVERY_QUERIES_PARFUMCITY":"Example"}):
   ds=await c.discover_products()
  offers=await c.fetch_offers(ds[0].product_url)
  self.assertEqual([x["external_product_id"] for x in offers],["20:201","20:202"])
  self.assertFalse(c.parse_raw(offers[0])["currency_explicit"])
 async def test_missing_seeds_fail_closed(self):
  c=ParfumCityConnector(SimpleNamespace())
  with patch.dict(os.environ,{"SCENTHUNTER_DISCOVERY_QUERIES_PARFUMCITY":""}):
   with self.assertRaises(ValueError): await c.discover_products()
