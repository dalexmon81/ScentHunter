SABINA DIAGNOSTIC INSTALL — DO NOT CHANGE PRODUCTION SCRAPER

1) Copy:
   debug_sabina_born_in_roma.py
   into:
   backend/debug_sabina_born_in_roma.py

2) In backend/main.py, immediately AFTER:
       app = FastAPI(
           title="ScentHunter API",
           version="1.0.0",
       )

   add:

       from debug_sabina_born_in_roma import router as debug_sabina_born_in_roma_router
       app.include_router(debug_sabina_born_in_roma_router)

   If main.py already imports this router/include, DO NOT duplicate it.

3) Do NOT modify:
   - backend/scrapers/sabina/scraper.py
   - backend/product_matcher.py
   - backend/family_registry.json
   - backend/sitecustomize.py

4) Deploy/restart the backend.

5) Test ONLY this endpoint:

   /diagnose-sabina-born-in-roma?q=Born%20in%20Roma

The diagnostic performs ONE Sabina search through the REAL search_stream().
It does NOT call search() separately.

The response contains:
- counts
- loss_by_variant
- matrix
- raw_trace
- downstream_observation

The decisive field is:
loss_by_variant

Possible conclusions:
NOT_DISCOVERED_EVIDENCE
DISCOVERED_URL_BUT_EXTRACTION_FAILED
EXTRACTED_BUT_NOT_EMITTED
STREAM_EMITTED_BUT_CLEAN_RESULT_REJECTED
CLEANED_BUT_PRODUCT_MATCHER_REJECTED
MATCHED_BUT_DEDUPE_DROPPED
SURVIVED_OBSERVED_STAGES

IMPORTANT:
A URL alone is not treated as proof of discovery when the slug does not expose
the variant. In that case the diagnostic says NOT_DISCOVERED_EVIDENCE rather
than inventing certainty.
