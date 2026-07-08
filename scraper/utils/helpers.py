import re
from datetime import date, datetime
from typing import Optional

import requests

from config import COMMODITY_ALIASES, REQUEST_HEADERS, REQUEST_TIMEOUT, TARGET_COMMODITIES
from utils.logger import get_logger

log = get_logger(__name__)


# ─── Commodity helpers ────────────────────────────────────────────────────────

def normalise_commodity(raw: str) -> Optional[str]:
    """
    Map a raw commodity name from any source to our canonical name.
    Returns None if it's not one of our target commodities.
    """
    cleaned = raw.strip().lower()
    canonical = COMMODITY_ALIASES.get(cleaned)
    if canonical:
        return canonical
    # Partial match fallback
    for alias, canonical in COMMODITY_ALIASES.items():
        if alias in cleaned or cleaned in alias:
            return canonical
    return None


def is_target_commodity(raw: str) -> bool:
    return normalise_commodity(raw) is not None


# ─── Date helpers ─────────────────────────────────────────────────────────────

def parse_date(raw: str) -> Optional[date]:
    """Try several common date formats and return a date object."""
    formats = [
        "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
        "%d-%m-%Y", "%B %Y", "%b %Y", "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    log.warning("Could not parse date: %s", raw)
    return None


def today() -> date:
    return date.today()


# ─── Price helpers ────────────────────────────────────────────────────────────

def clean_price(raw) -> Optional[float]:
    """Strip currency symbols, commas, whitespace and return float."""
    if raw is None:
        return None
    try:
        cleaned = re.sub(r"[^\d.]", "", str(raw))
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def safe_get(url: str, **kwargs) -> Optional[requests.Response]:
    """GET with timeout, headers, and graceful error handling."""
    try:
        resp = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        resp.raise_for_status()
        return resp
    except requests.exceptions.HTTPError as e:
        log.error("HTTP error fetching %s: %s", url, e)
    except requests.exceptions.ConnectionError as e:
        log.error("Connection error fetching %s: %s", url, e)
    except requests.exceptions.Timeout:
        log.error("Timeout fetching %s", url)
    except Exception as e:
        log.error("Unexpected error fetching %s: %s", url, e)
    return None


def download_file(url: str, dest_path: str) -> bool:
    """Stream-download a binary file (PDF, Excel) to disk."""
    resp = safe_get(url, stream=True)
    if not resp:
        return False
    try:
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        log.info("Downloaded %s → %s", url, dest_path)
        return True
    except OSError as e:
        log.error("Failed to save file from %s: %s", url, e)
        return False
