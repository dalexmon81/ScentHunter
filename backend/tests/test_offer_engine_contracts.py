from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from backend.offer_engine.contracts import Availability, OfferObservation, RetailerListing, Verification
from backend.offer_engine.policy import OfferPolicy

class OfferEngineContractTests(unittest.TestCase):
 def test_listing_rejects_non_http_url_and_invalid_size(self):
  with self.assertRaises(ValueError): RetailerListing("deloox","1","javascript:alert(1)","Perfume")
  with self.assertRaises(ValueError): RetailerListing("deloox","1","https://example.com/p","Perfume",raw_size_ml=0)
 def test_verified_requires_identity_and_evidence(self):
  with self.assertRaises(ValueError): OfferObservation("deloox:1",datetime.now(timezone.utc),Decimal("42.89"),"EUR",Availability.IN_STOCK,"product_page",Verification.VERIFIED,product_id="p",variant_id="v",evidence_url="https://example.com/p")
 def test_stale_observation_is_not_publishable(self):
  now=datetime.now(timezone.utc)
  o=OfferObservation("deloox:1",now-timedelta(days=3),Decimal("42.89"),"EUR",Availability.IN_STOCK,"product_page",Verification.VERIFIED,"p","v","https://example.com/p","sha256:abc")
  d=OfferPolicy().evaluate(o,now=now)
  self.assertFalse(d.publish); self.assertEqual(d.reason,"observation_stale")
 def test_unknown_stock_is_not_publishable(self):
  now=datetime.now(timezone.utc)
  o=OfferObservation("deloox:1",now,Decimal("42.89"),"EUR",Availability.UNKNOWN,"product_page",Verification.UNVERIFIED)
  d=OfferPolicy().evaluate(o,now=now)
  self.assertFalse(d.publish); self.assertEqual(d.reason,"not_verified")
 def test_explicit_sold_out_can_be_verified(self):
  now=datetime.now(timezone.utc)
  o=OfferObservation("deloox:1",now,Decimal("42.89"),"EUR",Availability.OUT_OF_STOCK,"product_page",Verification.VERIFIED,"p","v","https://example.com/p","sha256:abc")
  decision=OfferPolicy().evaluate(o,now=now)
  self.assertFalse(decision.publish); self.assertEqual(decision.reason,"out_of_stock")

if __name__ == "__main__": unittest.main()
