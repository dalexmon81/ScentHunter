# Services layer

Business use cases and orchestration. Services coordinate repositories, matching, search, and workers without owning persistence details.

`catalog_search.py` owns the read-only catalog search use case and its legacy frontend response adapter. HTTP routing, query parameter constraints, and HTTP error translation stay in `app/api/catalog_search.py`.
