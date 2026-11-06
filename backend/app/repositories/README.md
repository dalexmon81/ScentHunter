# Repositories layer

Database access and persistence queries. Keep SQL/ORM operations here and expose domain-oriented methods to services.

`catalog_search.py` owns SQLAlchemy query construction and retrieval of canonical fragrance, variant, and currently published offer rows for the catalog-search service. Response shaping remains in the service layer.
