# Schemas layer

**Responsibility:** validated data contracts at API, connector, worker and internal application boundaries.

Keep Pydantic request/response schemas separate from SQLAlchemy persistence models. Connector source payloads must retain raw evidence; normalized records must state which fields were explicit versus inferred. Schemas validate shape and types but do not perform retailer I/O, canonical matching or database persistence.
