"""
Ollama Normalizer
─────────────────
Sends raw unstructured text (from PDFs, HTML blobs, etc.) to the
local Mistral model and asks it to extract commodity prices as JSON.

Used by MINAGRI and FEWS NET scrapers where data is in narrative form.
"""

import json
import re
from typing import List, Optional

import requests

from config import OLLAMA_HOST, OLLAMA_MODEL
from db.repository import PriceRecord
from utils.helpers import clean_price, normalise_commodity, parse_date, today
from utils.logger import get_logger

log = get_logger(__name__)

_SYSTEM_PROMPT = """
You are a data extraction assistant. Your job is to read agricultural 
market reports and extract commodity price data for Rwanda.

Extract ONLY these commodities if present:
- Maize
- Beans
- Rice
- Cooking oil
- Sugar

Return ONLY a valid JSON array. No explanation, no markdown, no extra text.
Each object must have these exact keys:
  commodity, market, price, currency, unit, date

If a field is unknown, use null.
Prices should be numeric only (no currency symbols).
Currency default is RWF. Unit default is kg.
Date format: YYYY-MM-DD.

Example output:
[
  {"commodity":"Maize","market":"Kigali","price":450,"currency":"RWF","unit":"kg","date":"2024-03-01"},
  {"commodity":"Beans","market":"Musanze","price":680,"currency":"RWF","unit":"kg","date":"2024-03-01"}
]
"""


def extract_prices(text: str, source: str = "ollama") -> List[PriceRecord]:
    """
    Send raw text to local Ollama model.
    Returns a list of PriceRecord objects.
    """
    if not text or len(text.strip()) < 20:
        log.warning("Text too short to extract from")
        return []

    # Trim to ~3000 chars to avoid overloading the 7B model
    trimmed = text[:3000].strip()

    payload = {
        "model":  OLLAMA_MODEL,
        "system": _SYSTEM_PROMPT,
        "prompt": f"Extract commodity prices from this text:\n\n{trimmed}",
        "stream": False,
    }

    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=120,       # 7B on CPU can be slow
        )
        resp.raise_for_status()
        raw_response = resp.json().get("response", "")
    except Exception as e:
        log.error("Ollama request failed: %s", e)
        return []

    return _parse_response(raw_response, source)


def _parse_response(raw: str, source: str) -> List[PriceRecord]:
    """Parse the JSON array the model returns."""
    # Strip any markdown fences the model might add despite instructions
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()

    # Find JSON array bounds
    start = cleaned.find("[")
    end   = cleaned.rfind("]") + 1
    if start == -1 or end == 0:
        log.warning("No JSON array found in Ollama response: %s", raw[:200])
        return []

    try:
        items = json.loads(cleaned[start:end])
    except json.JSONDecodeError as e:
        log.error("JSON decode error: %s — raw: %s", e, cleaned[start:end][:300])
        return []

    records: List[PriceRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        commodity = normalise_commodity(str(item.get("commodity", "")))
        if not commodity:
            continue

        price = clean_price(item.get("price"))
        if not price:
            continue

        raw_date = item.get("date") or str(today())
        entry_date = parse_date(str(raw_date)) or today()

        records.append(PriceRecord(
            commodity=commodity,
            market=str(item.get("market") or "Unknown").strip().title(),
            price=price,
            currency=str(item.get("currency") or "RWF").upper(),
            unit=str(item.get("unit") or "kg").lower(),
            date=entry_date,
            source=source,
        ))

    log.info("Ollama extracted %d price records", len(records))
    return records
