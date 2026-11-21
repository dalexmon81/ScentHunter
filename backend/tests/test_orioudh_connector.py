import os, unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.connectors.orioudh import OrioudhConnector

from scrapers.orioudh import scraper as orioudh_scraper

def variant(vid,price):
 return {"name":"Example 100 ml","url":"https://orioudh.com/products/example","source":{"source_name":"Example 100 ml","source_brand":"Example","url":"https://orioudh.com/products/example"},"identity":{"store_product_id":{"value":10},"store_variant_id":{"value":vid},"sku":{"value":str(vid)}},"attributes":{"size_ml":{"value":100}},"offer":{"price":price,"currency":"EUR","availability":"in_stock"}}
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_shopify_cart_currency_is_explicit_and_cached(self):
  class Response:
   status_code=200
   def json(self): return {"currency":"EUR"}
   def close(self): pass
  class Session:
   def __init__(self): self.calls=[]
   def get(self,url,**kwargs): self.calls.append(url); return Response()
  session=Session()
  value=orioudh_scraper._cart_currency(session,"https://orioudh.com/products/example")
  self.assertEqual(value,"EUR")
  self.assertEqual(orioudh_scraper._cart_currency(session,"https://orioudh.com/products/example"),"EUR")
  self.assertEqual(session.calls,["https://orioudh.com/cart.js"])
  localized= orioudh_scraper._cart_currency(session,"https://orioudh.com/fr/products/example")
  self.assertEqual(localized,"EUR")
  self.assertEqual(session.calls[-1],"https://orioudh.com/fr/cart.js")

 async def test_product_json_uses_cart_js_currency_in_raw_offer(self):
  product={"id":10,"title":"Example Eau de Parfum","vendor":"Example","variants":[{"id":11,"title":"100 ml","price":"30.00","available":True,"sku":"EX-100"}]}
  with patch.object(orioudh_scraper,"_request_json",side_effect=lambda session,url: {"currency":"GBP"} if url.endswith("/cart.js") else product.copy()):
   session=SimpleNamespace()
   loaded=orioudh_scraper._product_json(session,"https://orioudh.com/products/example")
  self.assertEqual(loaded["_scenthunter_currency"],"GBP")
  row=orioudh_scraper._raw_offer(loaded,loaded["variants"][0],"https://orioudh.com/products/example")
  self.assertEqual(row["offer"]["currency"],"GBP")
  self.assertTrue(row["offer"]["currency_explicit"])
  self.assertEqual(row["offer"]["currency_source"],"shopify_cart_presentment_currency")
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
  raw["offer"]["currency_source"]="shopify_cart_presentment_currency"
  parsed=c.parse_raw(raw)
  self.assertEqual(parsed["currency"],"GBP")
  self.assertTrue(parsed["currency_explicit"])
  self.assertEqual(parsed["currency_source"],"shopify_cart_presentment_currency")
 async def test_missing_seeds_fail_closed(self):
  c=OrioudhConnector(SimpleNamespace())
  with patch.dict(os.environ,{"SCENTHUNTER_DISCOVERY_QUERIES_ORIOUDH":""}):
   with self.assertRaises(ValueError): await c.discover_products()

 async def test_foreign_product_hosts_are_rejected_during_discovery_and_fetch(self):
  scraper=SimpleNamespace(search_stream=lambda q:{"status":"success","verified":True,"results":[{"url":"https://attacker.example/products/fake"},{"url":"http://orioudh.com/products/insecure"},{"url":"https://evil-orioudh.com/products/lookalike"},{"url":"https://orioudh.com/products/real"}]})
  c=OrioudhConnector(scraper)
  with patch.dict(os.environ,{"SCENTHUNTER_DISCOVERY_QUERIES_ORIOUDH":"Example"}):
   products=await c.discover_products()
  self.assertEqual([p.product_url for p in products],["https://orioudh.com/products/real"])
  with self.assertRaisesRegex(ValueError,"Orioudh Shopify"):
   await c.fetch_product("https://attacker.example/products/fake")
  with self.assertRaises(ValueError):
   await c.fetch_product("http://orioudh.com/products/insecure")

class RefreshAfterRestartTests(unittest.IsolatedAsyncioTestCase):
 async def test_refresh_uses_persisted_product_url_without_discovery_snapshot(self):
  url="https://orioudh.com/products/example"
  scraper=SimpleNamespace(extract_product_page=lambda s,u,q:[variant(11,33)])
  c=OrioudhConnector(scraper)
  observation=await c.fetch_price_and_stock("10:11",product_url=url)
  self.assertEqual(observation["external_product_id"],"10:11")
  self.assertEqual(observation["price"],"33")
  self.assertEqual(c._snapshot,())
