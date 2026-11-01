# Store inventory

The production repository contains scraper/connector code for the following 11 store identifiers. Presence in the codebase does not imply current production coverage or a valid published offer.

| Store ID | Connector code |
|---|---|
| amazon_de | `backend/scrapers/amazon_de/scraper.py` |
| amazon_fr | `backend/scrapers/amazon_fr/scraper.py` |
| bplatz | `backend/scrapers/bplatz/scraper.py` |
| deloox | `backend/scrapers/deloox/scraper.py` |
| easycosmetic | `backend/scrapers/easycosmetic/scraper.py` |
| notino | `backend/scrapers/notino/scraper.py` |
| orioudh | `backend/scrapers/orioudh/scraper.py` |
| parfumcity | `backend/scrapers/parfumcity/scraper.py` |
| parfumzentrum | `backend/scrapers/parfumzentrum/scraper.py` |
| perfumemarket | `backend/scrapers/perfumemarket/scraper.py` |
| sabina | `backend/scrapers/sabina/scraper.py` |

At least two Amazon marketplaces are configured but intentionally gated from ordinary active offer discovery while authorization/affiliate credentials are unresolved. This inventory describes repository code, not live feed availability.

Per-store details still to confirm from connector implementations: search URL strategy, product URL strategy, exposed product fields, official API/feed availability, variant handling, stock semantics, and known parser limitations. Use dedicated reviewed records rather than assuming parity between stores.
