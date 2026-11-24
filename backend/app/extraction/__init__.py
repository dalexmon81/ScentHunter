"""Known-product extraction boundary for retailer connector records."""
from .product import (
    ExtractedProductRecord,
    extract_price_stock_observation,
    extract_product_record,
)

__all__ = [
    "ExtractedProductRecord", "extract_product_record",
    "extract_price_stock_observation",
]
