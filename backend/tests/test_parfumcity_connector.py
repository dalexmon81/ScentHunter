import os, unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.connectors.parfumcity import ParfumCityConnector

from scrapers.parfumcity import scraper as parfumcity_scraper

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
  value=parfumcity_scraper._cart_currency(session,"https://www.parfumcity.nl/products/example")
  self.assertEqual(value,"EUR")
  self.assertEqual(parfumcity_scraper._cart_currency(session,"https://www.parfumcity.nl/products/example"),"EUR")
  self.assertEqual(session.calls,["https://www.parfumcity.nl/cart.js"])
  localized= parfumcity_scraper._cart_currency(session,"https://www.parfumcity.nl/fr/products/example")
  self.assertEqual(localized,"EUR")
  self.assertEqual(session.calls[-1],"https://www.parfumcity.nl/fr/cart.js")

 async def test_product_json_uses_cart_js_currency_in_raw_offer(self):
  product={"id":20,"title":"Example Eau de Parfum","vendor":"Example","variants":[{"id":201,"title":"100 ml","price":"30.00","available":True,"sku":"EX-100"}]}
  class Response:
   def __init__(self,payload): self.payload=payload
   def json(self): return self.payload
   def close(self): pass
  def fake_get(session,url):
   return Response({"currency":"GBP"} if url.endswith("/cart.js") else product.copy())
  with patch.object(parfumcity_scraper,"_get",side_effect=fake_get):
   loaded=parfumcity_scraper.product_json(SimpleNamespace(),"https://www.parfumcity.nl/products/example")
  self.assertEqual(loaded["_scenthunter_currency"],"GBP")
  row=parfumcity_scraper.make_item(loaded,loaded["variants"][0],"https://www.parfumcity.nl/products/example","Example")
  self.assertEqual(row["offer"]["currency"],"GBP")
  self.assertTrue(row["offer"]["currency_explicit"])
  self.assertEqual(row["offer"]["currency_source"],"shopify_cart_presentment_currency")
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
 async def test_explicit_currency_field_is_preserved(self):
  c=ParfumCityConnector(SimpleNamespace())
  raw={"name":"Example","url":"https://www.parfumcity.nl/products/example","offer":{"price":30,"currency":"GBP","currency_explicit":True,"currency_source":"shopify_cart_presentment_currency","availability":"in_stock"}}
  parsed=c.parse_raw(raw)
  self.assertEqual(parsed["currency"],"GBP")
  self.assertTrue(parsed["currency_explicit"])
  self.assertEqual(parsed["currency_source"],"shopify_cart_presentment_currency")
 async def test_missing_seeds_fail_closed(self):
  c=ParfumCityConnector(SimpleNamespace())
  with patch.dict(os.environ,{"SCENTHUNTER_DISCOVERY_QUERIES_PARFUMCITY":""}):
   with self.assertRaises(ValueError): await c.discover_products()

 async def test_foreign_product_hosts_are_rejected_during_discovery_and_fetch(self):
  scraper=SimpleNamespace(discover=lambda s,q:(["https://attacker.example/products/fake","https://www.parfumcity.nl/products/real"],[],True))
  c=ParfumCityConnector(scraper)
  with patch.dict(os.environ,{"SCENTHUNTER_DISCOVERY_QUERIES_PARFUMCITY":"Example"}):
   products=await c.discover_products()
  self.assertEqual([p.product_url for p in products],["https://www.parfumcity.nl/products/real"])
  with self.assertRaisesRegex(ValueError,"ParfumCity Shopify"):
   await c.fetch_product("https://attacker.example/products/fake")

class RefreshAfterRestartTests(unittest.IsolatedAsyncioTestCase):
 async def test_refresh_uses_persisted_product_url_without_discovery_snapshot(self):
  url="https://www.parfumcity.nl/products/example"
  product={"id":20,"title":"Example Eau de Parfum","vendor":"Example","variants":[{"id":201,"title":"50 ml","price":"31.00","available":True}]}
  def make(p,v,u,q):
   return {"name":p["title"]+" "+v["title"],"url":u,"source":{"source_name":p["title"],"source_brand":p["vendor"],"url":u},"identity":{"store_product_id":{"value":p["id"]},"store_variant_id":{"value":v["id"]}},"attributes":{"size_ml":{"value":50}},"offer":{"price":float(v["price"]),"currency":"EUR","availability":"in_stock"}}
  scraper=SimpleNamespace(product_json=lambda s,u:product,make_item=make)
  c=ParfumCityConnector(scraper)
  observation=await c.fetch_price_and_stock("20:201",product_url=url)
  self.assertEqual(observation["external_product_id"],"20:201")
  self.assertEqual(observation["price"],"31.0")
  self.assertEqual(c._snapshot,())
