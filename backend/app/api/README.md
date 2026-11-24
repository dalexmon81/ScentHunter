# API layer

**Responsibility:** FastAPI routers, dependency wiring, authentication boundary and request/response handling only.

Routes call application/domain services or read repositories. They must not implement catalog identity, matching, offer publication, price refresh or connector-health rules. They must never call retailer connectors or scrapers during user-facing search.

Search endpoints remain read-only against the canonical PostgreSQL catalog and its indexed offers.
