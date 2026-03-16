#!/usr/bin/env python3
"""
lightroom_auto_adjust.py

Monitors Adobe Lightroom (cloud) for newly imported camera photos and
automatically applies Auto Tone adjustments to each one.

Usage:
    python3 lightroom_auto_adjust.py

Requirements:
    pip install requests python-dotenv

Setup:
    1. Create an Adobe Developer project at https://developer.adobe.com/console
       and add the Lightroom API.
    2. Copy .env.example to .env and fill in your credentials.
    3. Run the script while your camera is connected to your iPhone and
       Lightroom is importing photos.

How it works:
    - Polls the Lightroom cloud API every POLL_INTERVAL seconds.
    - Detects assets (photos) added after the script started.
    - For each new asset, applies autoTone (Auto adjustment) via the API.
"""

import os
import sys
import time
import json
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env loading is optional; fall back to real env vars

# ---------------------------------------------------------------------------
# Configuration (override via environment variables or .env file)
# ---------------------------------------------------------------------------
CLIENT_ID = os.environ.get("ADOBE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("ADOBE_CLIENT_SECRET", "")
ACCESS_TOKEN = os.environ.get("ADOBE_ACCESS_TOKEN", "")   # pre-obtained token
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "5"))   # catch any photos missed on startup

LR_BASE = "https://lr.adobe.io"
IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def obtain_token_client_credentials() -> str:
    """Exchange client_id + client_secret for an access token (Service account flow)."""
    if not CLIENT_ID or not CLIENT_SECRET:
        log.error(
            "ADOBE_CLIENT_ID and ADOBE_CLIENT_SECRET must be set.\n"
            "See https://developer.adobe.com/console to create a project."
        )
        sys.exit(1)

    resp = requests.post(
        IMS_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": "openid,AdobeID,lr_partner_apis",
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token", "")
    if not token:
        sys.exit(f"No access_token in response: {resp.text}")
    log.info("Obtained new access token.")
    return token


def get_token() -> str:
    """Return an access token, refreshing if necessary."""
    if ACCESS_TOKEN:
        return ACCESS_TOKEN
    return obtain_token_client_credentials()


# ---------------------------------------------------------------------------
# Lightroom API helpers
# ---------------------------------------------------------------------------

class LightroomClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "X-API-Key": CLIENT_ID or "lightroom_auto_adjust",
        })

    def _get(self, path: str, **params) -> dict:
        url = f"{LR_BASE}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code == 401:
            log.error("Unauthorized — check your access token or client credentials.")
            sys.exit(1)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, payload: dict) -> dict:
        url = f"{LR_BASE}{path}"
        resp = self.session.put(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    # --- catalog ---

    def get_catalog(self) -> dict:
        """Return the user's default Lightroom catalog."""
        data = self._get("/v2/catalog")
        return data.get("id", ""), data

    # --- assets ---

    def list_assets_since(self, catalog_id: str, since: datetime) -> list[dict]:
        """Return all assets captured/imported after `since` (UTC datetime)."""
        since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
        assets = []
        href = f"/v2/catalogs/{catalog_id}/assets"
        params = {
            "captured_after": since_str,
            "subtype": "image",
            "limit": 100,
        }
        while href:
            data = self._get(href, **params)
            resources = data.get("resources", [])
            assets.extend(resources)
            # Follow pagination links
            links = data.get("links", {})
            next_link = links.get("next", {}).get("href")
            href = next_link
            params = {}  # next href already includes query params
        return assets

    # --- develop (auto tone) ---

    def apply_auto_tone(self, catalog_id: str, asset_id: str) -> bool:
        """Apply Lightroom Auto Tone to a single asset. Returns True on success."""
        path = f"/v2/catalogs/{catalog_id}/assets/{asset_id}/develop"
        payload = {
            "settings": {
                "autoTone": True,
            }
        }
        try:
            self._put(path, payload)
            return True
        except requests.HTTPError as exc:
            log.warning("Auto tone failed for %s: %s", asset_id, exc)
            return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(dry_run: bool = False):
    token = get_token()
    client = LightroomClient(token)

    log.info("Fetching Lightroom catalog…")
    catalog_id, catalog_data = client.get_catalog()
    catalog_name = (
        catalog_data.get("payload", {})
        .get("name", "unknown")
    )
    log.info("Catalog: %s  (id=%s)", catalog_name, catalog_id)

    # Track which asset IDs we have already processed
    processed: set[str] = set()

    # On startup, look back a few minutes to catch any in-flight imports
    last_checked = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
    log.info(
        "Monitoring for new photos… (poll every %ds, lookback %dmin on startup)",
        POLL_INTERVAL,
        LOOKBACK_MINUTES,
    )
    log.info("Press Ctrl+C to stop.\n")

    try:
        while True:
            check_time = datetime.now(timezone.utc)
            new_assets = client.list_assets_since(catalog_id, last_checked)

            for asset in new_assets:
                asset_id = asset.get("id", "")
                if not asset_id or asset_id in processed:
                    continue

                filename = (
                    asset.get("payload", {})
                    .get("importSource", {})
                    .get("fileName", asset_id)
                )
                log.info("New photo detected: %s", filename)

                if dry_run:
                    log.info("  [dry-run] Would apply Auto Tone to %s", asset_id)
                else:
                    ok = client.apply_auto_tone(catalog_id, asset_id)
                    if ok:
                        log.info("  Auto Tone applied to %s", filename)
                    else:
                        log.warning("  Failed to apply Auto Tone to %s", filename)

                processed.add(asset_id)

            last_checked = check_time
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("\nStopped. Processed %d photo(s) this session.", len(processed))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Auto-apply Lightroom Auto Tone to newly imported camera photos."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect new photos but do not actually apply adjustments.",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
