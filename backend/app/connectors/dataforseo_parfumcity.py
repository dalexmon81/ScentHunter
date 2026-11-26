"""ParfumCity fallback discovery through DataForSEO Google Shopping.

This provider is deliberately retailer-scoped. It never fetches ParfumCity's
blocked storefront; it uses DataForSEO's documented Merchant API and accepts
only seller offers whose product URL belongs to parfumcity.nl.
"""
from __future__ import annotations

import os
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

import requests

from app.connectors.base import ConnectorUnavailable

API_ROOT = "https://api.dataforseo.com"
STORE_HOSTS = {"parfumcity.nl", "www.parfumcity.nl"}
MAX_PRODUCTS_PER_QUERY = 10
TASK_POLL_SECONDS = 2.0
TASK_TIMEOUT_SECONDS = 100.0


def _clean(value: Any) -> str:
    return re.sub(r"\\s+", " ", str(value or "")).strip()


def _normal(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _size_ml(*values: Any) -> int | None:
    match = re.search(
        r"(?<!\\d)(\\d+(?:[.,]\\d+)?)\\s*(ml|cl|dl|l)\\b",
        " ".join(_clean(value) for value in values),
        re.I,
    )
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    amount *= {"ml": 1, "cl": 10, "dl": 100, "l": 1000}[unit]
    return int(amount) if amount.is_integer() else None


def _concentration(*values: Any) -> str | None:
    value = _normal(" ".join(_clean(item) for item in values))
    if "extrait de parfum" in value or re.search(r"\\bextrait\\b", value):
        return "Extrait de Parfum"
    if "eau de toilette" in value or re.search(r"\\bedt\\b", value):
        return "Eau de Toilette"
    if "eau de parfum" in value or re.search(r"\\bedp\\b", value):
        return "Eau de Parfum"
    return None


def _walk_specs(value: Any):
    if isinstance(value, Mapping):
        name = _normal(value.get("specification_name") or value.get("name") or value.get("key"))
        content = value.get("specification_value") or value.get("value")
        if name and content is not None:
            yield name, _clean(content)
        for child in value.values():
            yield from _walk_specs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_specs(child)


def _spec_value(item: Mapping[str, Any], names: set[str]) -> str | None:
    for name, value in _walk_specs(item):
        if name in names and value:
            return value
    return None


class DataForSEOParfumcitySource:
    """Small, bounded client for Google Shopping Products and Product Info."""

    def __init__(
        self,
        *,
        login: str | None = None,
        password: str | None = None,
        session: Any | None = None,
        clock=time.monotonic,
        sleeper=time.sleep,
        poll_timeout: float = TASK_TIMEOUT_SECONDS,
    ):
        self.login = login if login is not None else os.getenv("DATAFORSEO_LOGIN", "")
        self.password = password if password is not None else os.getenv("DATAFORSEO_PASSWORD", "")
        if not self.login or not self.password:
            raise ValueError("DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD are required")
        self.session = session or requests.Session()
        self.session.auth = (self.login, self.password)
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.clock = clock
        self.sleeper = sleeper
        self.poll_timeout = poll_timeout

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if callable(close):
            close()

    def _request(self, method: str, path: str, payload: Any | None = None) -> Mapping[str, Any]:
        try:
            response = self.session.request(
                method,
                API_ROOT + path,
                json=payload,
                timeout=(5.0, 30.0),
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ConnectorUnavailable(f"DataForSEO request failed: {type(exc).__name__}: {exc}") from exc
        if not isinstance(data, Mapping) or data.get("status_code") != 20000:
            code = data.get("status_code") if isinstance(data, Mapping) else "invalid_json"
            message = data.get("status_message") if isinstance(data, Mapping) else "invalid JSON response"
            raise ConnectorUnavailable(f"DataForSEO API error {code}: {message}")
        return data

    @staticmethod
    def _task_ids(response: Mapping[str, Any]) -> list[str]:
        tasks = response.get("tasks")
        if not isinstance(tasks, list):
            raise ConnectorUnavailable("DataForSEO task response has no tasks array")
        ids = [
            str(task.get("id"))
            for task in tasks
            if isinstance(task, Mapping) and task.get("id")
            and int(task.get("status_code") or 0) in {20000, 20100}
        ]
        if not ids:
            first = tasks[0] if tasks and isinstance(tasks[0], Mapping) else {}
            raise ConnectorUnavailable(
                f"DataForSEO task was not accepted: {first.get('status_code')} {first.get('status_message')}"
            )
        return ids

    def _post_and_collect(self, kind: str, payloads: list[dict[str, Any]]) -> list[Mapping[str, Any]]:
        if not payloads:
            return []
        if len(payloads) > 100:
            raise ValueError("DataForSEO task batches are limited to 100")
        posted = self._request(
            "POST",
            f"/v3/merchant/google/{kind}/task_post",
            payloads,
        )
        task_ids = self._task_ids(posted)
        wanted = set(task_ids)
        ready_ids: set[str] = set()
        deadline = self.clock() + self.poll_timeout
        while wanted - ready_ids and self.clock() < deadline:
            ready = self._request("GET", f"/v3/merchant/google/{kind}/tasks_ready")
            for task in ready.get("tasks") or []:
                if not isinstance(task, Mapping):
                    continue
                if task.get("id") in wanted:
                    ready_ids.add(str(task["id"]))
                for result in task.get("result") or []:
                    if isinstance(result, Mapping) and result.get("id") in wanted:
                        ready_ids.add(str(result["id"]))
            if wanted - ready_ids:
                self.sleeper(TASK_POLL_SECONDS)
        if wanted - ready_ids:
            pending = ", ".join(sorted(wanted - ready_ids))
            raise ConnectorUnavailable(
                f"DataForSEO {kind} tasks are still processing after {self.poll_timeout:.0f}s: {pending}"
            )

        collected: list[Mapping[str, Any]] = []
        for task_id in task_ids:
            result = self._request(
                "GET",
                f"/v3/merchant/google/{kind}/task_get/advanced/{task_id}",
            )
            for task in result.get("tasks") or []:
                if isinstance(task, Mapping):
                    collected.append(task)
        return collected

    @staticmethod
    def _result_items(tasks: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        items: list[Mapping[str, Any]] = []
        for task in tasks:
            for result in task.get("result") or []:
                if not isinstance(result, Mapping):
                    continue
                nested = result.get("items")
                if isinstance(nested, list):
                    items.extend(item for item in nested if isinstance(item, Mapping))
                elif result.get("type"):
                    items.append(result)
        return items

    def _product_ids(self, query: str) -> list[tuple[str, str]]:
        tasks = self._post_and_collect(
            "products",
            [{
                "keyword": query,
                "location_name": "Netherlands",
                "language_name": "Dutch",
                "depth": MAX_PRODUCTS_PER_QUERY,
                "priority": 2,
            }],
        )
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        wanted = [token for token in _normal(query).split() if len(token) > 1]
        for item in self._result_items(tasks):
            product_id = _clean(item.get("product_id"))
            title = _clean(item.get("title"))
            if not product_id or product_id in seen or not title:
                continue
            title_tokens = set(_normal(title).split())
            if wanted and not all(token in title_tokens for token in wanted):
                continue
            seen.add(product_id)
            found.append((product_id, title))
            if len(found) >= MAX_PRODUCTS_PER_QUERY:
                break
        return found

    @staticmethod
    def _seller_records(product_id: str, tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in DataForSEOParfumcitySource._result_items(tasks):
            if item.get("type") != "product_info_element":
                continue
            title = _clean(item.get("title"))
            brand = _spec_value(item, {"brand", "manufacturer", "merk"})
            gtin = _spec_value(item, {"gtin", "ean", "ean13", "gtin13"})
            size = _size_ml(title, item.get("description"))
            concentration = _concentration(title, item.get("description"))
            for seller in item.get("sellers") or []:
                if not isinstance(seller, Mapping):
                    continue
                url = _clean(seller.get("url"))
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.hostname not in STORE_HOSTS:
                    continue
                if "/products/" not in parsed.path.lower():
                    continue
                price_data = seller.get("price") if isinstance(seller.get("price"), Mapping) else {}
                price = price_data.get("current")
                currency = _clean(price_data.get("currency")).upper()
                try:
                    amount = float(price)
                except (TypeError, ValueError):
                    continue
                if amount <= 0 or not currency or not re.fullmatch(r"[A-Z]{3}", currency):
                    continue
                raw_availability = _clean(seller.get("product_availability")).lower()
                if raw_availability in {"in_stock", "limited_stock"}:
                    availability = "in_stock"
                elif raw_availability == "out_of_stock":
                    availability = "out_of_stock"
                else:
                    continue

                record = {
                    "store": "ParfumCity",
                    "external_product_id": f"dataforseo:{product_id}",
                    "source": {
                        "source_name": title,
                        "source_brand": brand,
                        "url": url,
                        "image": item.get("image_url"),
                    },
                    "identity": {
                        "gtin": {"value": gtin, "source": "dataforseo_product_spec"} if gtin else None,
                    },
                    "attributes": {
                        "size_ml": {"value": size, "source": "dataforseo_product_title"} if size else None,
                        "concentration": {"value": concentration, "source": "dataforseo_product_title"} if concentration else None,
                    },
                    "offer": {
                        "price": amount,
                        "currency": currency,
                        "currency_explicit": True,
                        "availability": availability,
                    },
                    "name": title,
                    "brand": brand,
                    "price_num": amount,
                    "price": f"{amount:.2f}",
                    "currency": currency,
                    "currency_explicit": True,
                    "availability": availability,
                    "available": availability == "in_stock",
                    "size_ml": size,
                    "concentration": concentration,
                    "url": url,
                    "product_url": url,
                    "captured_at": time.time(),
                    "provenance": {
                        "source": "dataforseo_google_product_info",
                        "product_id": product_id,
                    },
                    "raw_data": {
                        "dataforseo_product_info": dict(item),
                        "dataforseo_seller": dict(seller),
                    },
                }
                rows.append(record)
        return rows

    def _product_info(self, product_id: str) -> list[dict[str, Any]]:
        tasks = self._post_and_collect(
            "product_info",
            [{
                "product_id": product_id,
                "location_name": "Netherlands",
                "language_name": "Dutch",
                "priority": 2,
            }],
        )
        return self._seller_records(product_id, tasks)

    def discover(self, query: str) -> list[dict[str, Any]]:
        products = self._product_ids(query)
        rows: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for product_id, _title in products:
            for row in self._product_info(product_id):
                url = row["product_url"]
                if url not in seen_urls:
                    seen_urls.add(url)
                    rows.append(row)
        return rows

    def fetch_product(self, product_id: str) -> dict[str, Any] | None:
        rows = self._product_info(product_id)
        return rows[0] if rows else None
