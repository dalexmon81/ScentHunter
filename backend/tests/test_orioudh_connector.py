import os, unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.connectors.orioudh import OrioudhConnector

def variant(vid,price):
 return {"name":"Example 100 ml","url":"https://orioudh.com/products/example","source":{"source_name":"Example 100 ml","source_brand":"Example","url":"https://orioudh.com/products/example"},"identity":{"store_product_id":{"value":10},"store_variant_id":{"value":vid},"sku":{"value":str(vid)}},"attributes":{"size_ml":{"value":100}},"offer":{"price":price,"currency":"EUR","availability":"in_stock"}}
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_variants_keep_distinct_stable_ids_and_currency_unverified(self):
  scraper=SimpleNamespace(search_stream=lambda q:{"status":"success","verified":True,"results":[{"url":"https://orioudh.com/products/example"}]},extract_product_page=lambda s,u,q:[variant(11,30),variant(12,40)])
  c=OrioudhConnector(scraper)
  with patch.dict(os.environ,{"SCENTHUNTER_DISCOVERY_QUERIES_ORIOUDH":"Example"}):
   ds=await c.discover_products()
  offers=await c.fetch_offers(ds[0].product_url)
  self.assertEqual([x["external_product_id"] for x in offers],["10:11","10:12"])
  p=c.parse_raw(offers[0]); self.assertFalse(p["currency_explicit"]); self.assertEqual(p["price"],"30")
 async def test_explicit_currency_field_is_preserved(self):
  c=OrioudhConnector(SimpleNamespace())
  raw=variant(11,30)
  raw["offer"]["currency"]="GBP"
  raw["offer"]["currency_explicit"]=True
  parsed=c.parse_raw(raw)
  self.assertEqual(parsed["currency"],"GBP")
  self.assertTrue(parsed["currency_explicit"])
 async def test_missing_seeds_fail_closed(self):
  c=OrioudhConnector(SimpleNamespace())
  with patch.dict(os.environ,{"SCENTHUNTER_DISCOVERY_QUERIES_ORIOUDH":""}):
   with self.assertRaises(ValueError): await c.discover_products()

class RefreshAfterRestartTests(unittest.IsolatedAsyncioTestCase):
 async def test_refresh_uses_persisted_product_url_without_discovery_snapshot(self):
  url="https://orioudh.com/products/example"
  scraper=SimpleNamespace(extract_product_page=lambda s,u,q:[variant(11,33)])
  c=OrioudhConnector(scraper)
  observation=await c.fetch_price_and_stock("10:11",product_url=url)
  self.assertEqual(observation["external_product_id"],"10:11")
  self.assertEqual(observation["price"],"33")
  self.assertEqual(c._snapshot,())
