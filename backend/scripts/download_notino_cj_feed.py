"""Download the authorized NOTINO.fr CJ export over authenticated HTTPS.

Credentials are read only from CJ_HTTP_USERNAME and CJ_HTTP_PASSWORD. They are
never embedded in the URL, written to disk, or printed. The ZIP is validated
and the single XML member is atomically written to the selected output folder.
"""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import base64
import zipfile
from pathlib import Path, PurePosixPath


DEFAULT_CID = "8115142"
DEFAULT_SUBSCRIPTION_ID = "324587"
DEFAULT_ADVERTISER_ACCOUNT_NAME = "NOTINO_fr"
DEFAULT_FEED_NAME = "NotinoFR_google_all"
MAX_DOWNLOAD_BYTES = 500_000_000


def build_download_url(
    *, cid: str = DEFAULT_CID, subscription_id: str = DEFAULT_SUBSCRIPTION_ID,
    advertiser_account_name: str = DEFAULT_ADVERTISER_ACCOUNT_NAME,
    feed_name: str = DEFAULT_FEED_NAME, file_format: str = "xml",
) -> str:
    """Build the CJ HTTP/S export URL using the documented subscription path."""
    values = (cid, subscription_id, advertiser_account_name, feed_name, file_format)
    if any(not str(value).strip() for value in values):
        raise ValueError("CJ export path values must be non-empty.")
    advertiser = str(advertiser_account_name).replace(" ", "_").replace(",", "_")
    feed = str(feed_name).replace(" ", "_").replace(",", "_")
    return (
        f"https://datatransfer.cj.com/datatransfer/files/{cid}/"
        f"outgoing/productcatalog/{subscription_id}/"
        f"{advertiser}-{feed}-shopping.{file_format}.zip"
    )


def download_feed(
    output_dir: str | Path, *, username: str, password: str,
    cid: str = DEFAULT_CID, subscription_id: str = DEFAULT_SUBSCRIPTION_ID,
    advertiser_account_name: str = DEFAULT_ADVERTISER_ACCOUNT_NAME,
    feed_name: str = DEFAULT_FEED_NAME, timeout: int = 60,
    max_download_bytes: int = MAX_DOWNLOAD_BYTES,
) -> Path:
    """Download and validate the CJ ZIP, then atomically publish its XML file."""
    if not username or not password:
        raise ValueError("Set CJ_HTTP_USERNAME and CJ_HTTP_PASSWORD before downloading.")
    url = build_download_url(
        cid=cid, subscription_id=subscription_id,
        advertiser_account_name=advertiser_account_name, feed_name=feed_name,
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    auth = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/zip, application/octet-stream",
            "User-Agent": "ScentHunter-Notino-CJ-Feed/1.0",
        },
    )

    zip_path: Path | None = None
    xml_temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output, suffix=".zip.part", delete=False) as temp_zip:
            zip_path = Path(temp_zip.name)
            total = 0
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_download_bytes:
                            raise ValueError("CJ feed ZIP exceeds the configured download size limit.")
                        temp_zip.write(chunk)
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"CJ feed download failed with HTTP {exc.code}.") from None
            except urllib.error.URLError as exc:
                raise RuntimeError("CJ feed download failed; check network access and CJ HTTP credentials.") from None

        if not zipfile.is_zipfile(zip_path):
            raise ValueError("CJ export response is not a valid ZIP archive.")
        with zipfile.ZipFile(zip_path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError("CJ feed ZIP failed its CRC integrity check.")
            xml_members = [
                info for info in archive.infolist()
                if not info.is_dir() and info.filename.casefold().endswith(".xml")
            ]
            if len(xml_members) != 1:
                raise ValueError(f"Expected exactly one XML file in CJ ZIP; found {len(xml_members)}.")
            member = xml_members[0]
            member_path = PurePosixPath(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError("CJ ZIP contains an unsafe XML member path.")
            if member.file_size > max_download_bytes:
                raise ValueError("CJ XML exceeds the configured extraction size limit.")

            target = output / member_path.name
            with tempfile.NamedTemporaryFile(dir=output, suffix=".xml.part", delete=False) as temp_xml:
                xml_temp_path = Path(temp_xml.name)
                copied = 0
                with archive.open(member) as source:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > max_download_bytes:
                            raise ValueError("CJ XML exceeds the configured extraction size limit.")
                        temp_xml.write(chunk)
            os.replace(xml_temp_path, target)
            xml_temp_path = None
            return target
    finally:
        if zip_path is not None:
            zip_path.unlink(missing_ok=True)
        if xml_temp_path is not None:
            xml_temp_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/feeds/notino"))
    parser.add_argument("--cid", default=DEFAULT_CID)
    parser.add_argument("--subscription-id", default=DEFAULT_SUBSCRIPTION_ID)
    parser.add_argument("--advertiser-account-name", default=DEFAULT_ADVERTISER_ACCOUNT_NAME)
    parser.add_argument("--feed-name", default=DEFAULT_FEED_NAME)
    args = parser.parse_args()
    path = download_feed(
        args.output_dir,
        username=os.environ.get("CJ_HTTP_USERNAME", ""),
        password=os.environ.get("CJ_HTTP_PASSWORD", ""),
        cid=args.cid,
        subscription_id=args.subscription_id,
        advertiser_account_name=args.advertiser_account_name,
        feed_name=args.feed_name,
    )
    print(f"NOTINO_CJ_FEED_DOWNLOADED={path}")
    print(f"NOTINO_CJ_FEED_BYTES={path.stat().st_size}")


if __name__ == "__main__":
    main()
