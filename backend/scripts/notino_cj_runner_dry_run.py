"""Read-only live CJ parser check using Fly credentials and runner-local staging."""
import base64
import hashlib
import json
import os
import resource
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

from scrapers.notino import affiliate_feed as feed


# Keep this gate aligned with backfill_notino_verified_gtin.VERIFIED_GTINS.
# The runner intentionally imports only the standalone feed parser: it must not
# need database credentials, SQLAlchemy, or any catalog-writing application code.
REVIEWED_GTINS = {
    "3348901608053": {
        "external_product_id": "CHDSVGM_AEDP40",
        "size_ml": 30,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-16187295/",
    },
    "3348901368254": {
        "external_product_id": "CHDSVGM_AEDP20",
        "size_ml": 60,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-15676582/",
    },
    "3348901368247": {
        "external_product_id": "CHDSVGM_AEDP10",
        "size_ml": 100,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-15676518/",
    },
    "3348901428545": {
        "external_product_id": "CHDSVGM_AEDP25",
        "size_ml": 200,
        "path": "/dior/sauvage-eau-de-parfum-pour-homme/p-15971107/",
    },
}


def validate_reviewed_gtins(offers):
    """Require exact live-feed evidence for every reviewed Dior Sauvage EDP size."""
    by_gtin = {}
    by_external_id = {}
    for offer in offers:
        gtin = str(getattr(offer, "gtin", "") or "").strip()
        external_id = str(getattr(offer, "external_id", "") or "").strip()
        if gtin:
            by_gtin.setdefault(gtin, []).append(offer)
        if external_id:
            by_external_id.setdefault(external_id, []).append(offer)

    evidence = []
    failures = []
    for gtin, expected in REVIEWED_GTINS.items():
        matches = by_gtin.get(gtin, [])
        id_matches = by_external_id.get(expected["external_product_id"], [])
        if len(matches) != 1 or len(id_matches) != 1 or matches[0] is not id_matches[0]:
            failures.append({
                "gtin": gtin,
                "external_product_id": expected["external_product_id"],
                "reason": "missing_or_ambiguous_gtin_external_id_pair",
                "gtin_matches": len(matches),
                "external_id_matches": len(id_matches),
            })
            continue

        offer = matches[0]
        parsed_url = urllib.parse.urlparse(str(getattr(offer, "url", "") or ""))
        checks = {
            "brand": str(getattr(offer, "brand", "") or "").strip().casefold() == "dior",
            "title": (
                "sauvage" in str(getattr(offer, "title", "") or "").casefold()
                and "eau de parfum" in str(getattr(offer, "title", "") or "").casefold()
            ),
            "concentration": str(getattr(offer, "concentration", "") or "").casefold() == "eau de parfum",
            "size_ml": (
                getattr(offer, "size_ml", None) is not None
                and abs(float(offer.size_ml) - expected["size_ml"]) < 0.01
            ),
            "price": getattr(offer, "price", 0) is not None and float(offer.price) > 0,
            "currency": str(getattr(offer, "currency", "") or "").upper() == "EUR",
            "availability": str(getattr(offer, "availability", "") or "") in {"in_stock", "out_of_stock"},
            "url": (
                parsed_url.scheme == "https"
                and parsed_url.hostname == "www.notino.fr"
                and parsed_url.path == expected["path"]
                and not parsed_url.query
                and not parsed_url.fragment
            ),
        }
        failed_checks = [name for name, passed in checks.items() if not passed]
        row = {
            "gtin": gtin,
            "external_product_id": expected["external_product_id"],
            "expected_size_ml": expected["size_ml"],
            "actual_size_ml": getattr(offer, "size_ml", None),
            "price": str(getattr(offer, "price", "")),
            "currency": getattr(offer, "currency", None),
            "availability": getattr(offer, "availability", None),
            "product_url": getattr(offer, "url", None),
            "checks": checks,
        }
        if failed_checks:
            failures.append({**row, "reason": "identity_or_offer_validation_failed",
                             "failed_checks": failed_checks})
        else:
            evidence.append(row)

    return {
        "expected_gtins": len(REVIEWED_GTINS),
        "verified_gtins": len(evidence),
        "evidence": evidence,
        "failures": failures,
        "passed": len(evidence) == len(REVIEWED_GTINS) and not failures,
    }


START = b"NOTINO_FEED_DATA_BEGIN\\n"
END = b"NOTINO_FEED_DATA_END="


def download_from_fly(destination):
    parser_source = Path(feed.__file__).read_bytes()
    remote = """
import base64, hashlib, sys, tempfile, time, types
feed = types.ModuleType("notino_feed_remote")
sys.modules[feed.__name__] = feed
exec(compile(base64.b64decode(PARSER_SOURCE), "<notino_feed_remote>", "exec"), feed.__dict__)
with tempfile.TemporaryFile() as source:
    size = feed._download_feed(source, time.monotonic() + 240)
    digest = hashlib.sha256()
    output = sys.stdout.buffer
    output.write(b"NOTINO_FEED_DATA_BEGIN\\\\n")
    while True:
        chunk = source.read(65535)
        if not chunk:
            break
        digest.update(chunk)
        output.write(base64.b64encode(chunk) + b"\\\\n")
    output.write(b"NOTINO_FEED_DATA_END=" + str(size).encode() + b":" + digest.hexdigest().encode() + b"\\\\n")
    output.flush()
""".replace("PARSER_SOURCE", repr(base64.b64encode(parser_source).decode("ascii")))
    encoded = base64.b64encode(remote.encode()).decode("ascii")
    command = "/bin/sh -lc 'printf \\"%s\\" \\"".replace("\\\\", "\\") + encoded + "\\" | base64 -d | /app/.venv/bin/python'"
    with tempfile.TemporaryFile() as transport, tempfile.TemporaryFile() as errors:
        app = os.environ.get("SCENTHUNTER_NOTINO_FEED_APP", "scenthunter-pilot-20261030").strip()
        if not app:
            raise RuntimeError("SCENTHUNTER_NOTINO_FEED_APP must name the isolated feed source app")
        result = subprocess.run(
            ["flyctl", "ssh", "console", "--app", app, "--select=false", "-C", command],
            stdout=transport, stderr=errors, timeout=1200, check=False,
        )
        if result.returncode:
            raise RuntimeError(f"fly_feed_download_failed:exit={result.returncode}")
        transport.seek(0)
        for line in transport:
            if line == START:
                break
        else:
            raise RuntimeError("fly_feed_transfer_start_missing")
        digest = hashlib.sha256()
        size = 0
        for line in transport:
            if line.startswith(END):
                expected_size, expected_digest = line[len(END):].strip().split(b":", 1)
                if size != int(expected_size) or digest.hexdigest().encode() != expected_digest:
                    raise RuntimeError("fly_feed_transfer_integrity_failed")
                destination.seek(0)
                return size
            chunk = base64.b64decode(line.strip(), validate=True)
            size += len(chunk)
            if size > feed.MAX_FEED_BYTES:
                raise RuntimeError("fly_feed_transfer_too_large")
            digest.update(chunk)
            destination.write(chunk)
        raise RuntimeError("fly_feed_transfer_incomplete")


def stage_feed(source, download_bytes, started):
    stats = {}
    counts = {"products_read": 0, "valid": 0, "rejected": 0}
    reviewed_offers = []
    original_items = feed._feed_items
    original_parse = feed._parse_item

    def measured_items(stream):
        for item in original_items(stream):
            counts["products_read"] += 1
            yield item
            if counts["products_read"] % 5000 == 0:
                print("NOTINO_RUNNER_PROGRESS=" + json.dumps({
                    **counts, "staged_unique_variants": db.total_changes,
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                    "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                }), flush=True)

    def measured_parse(*args, **kwargs):
        offer = original_parse(*args, **kwargs)
        counts["valid" if offer is not None else "rejected"] += 1
        if offer is not None and (
            offer.gtin in REVIEWED_GTINS
            or offer.external_id in {
                item["external_product_id"] for item in REVIEWED_GTINS.values()
            }
        ):
            reviewed_offers.append(offer)
        return offer

    feed._feed_items = measured_items
    feed._parse_item = measured_parse
    try:
        with tempfile.TemporaryDirectory(prefix="notino-runner-stage-") as directory:
            db = sqlite3.connect(os.path.join(directory, "offers.sqlite3"))
            try:
                db.execute("CREATE TABLE offers(url TEXT, variant_key TEXT, PRIMARY KEY(url, variant_key)) WITHOUT ROWID")
                with feed._xml_stream(source, time.monotonic() + 18 * 60) as stream:
                    for offer in feed._parsed_offers(stream, stats):
                        db.execute("INSERT OR IGNORE INTO offers VALUES(?,?)",
                                   (offer.url, feed._stable_variant_key(offer)))
                db.commit()
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("notino_runner_staging_integrity_failed")
                staged = db.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
            finally:
                db.close()
    finally:
        feed._feed_items = original_items
        feed._parse_item = original_parse

    if not staged or stats["products_read"] != counts["products_read"]:
        raise RuntimeError("notino_runner_invalid_staging_result")

    reviewed = validate_reviewed_gtins(reviewed_offers)
    result = {
        "result": "PASS" if reviewed["passed"] else "FAIL",
        "download_bytes": download_bytes,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "staged_unique_variants": staged,
        "duplicate_items": stats["valid_items"] - staged,
        "parser_stats": stats,
        "catalog_database_touched": False,
        "reviewed_dior_sauvage_edp": reviewed,
    }
    print("NOTINO_RUNNER_DRY_RUN=" + json.dumps(result, ensure_ascii=False), flush=True)
    if not reviewed["passed"]:
        raise RuntimeError("notino_runner_reviewed_four_gtin_gate_failed")
    return result


def main():
    started = time.monotonic()
    with tempfile.TemporaryFile() as source:
        size = download_from_fly(source)
        print("NOTINO_RUNNER_DOWNLOAD=" + json.dumps({
            "download_bytes": size, "elapsed_seconds": round(time.monotonic() - started, 2),
        }), flush=True)
        stage_feed(source, size, started)


if __name__ == "__main__":
    main()
