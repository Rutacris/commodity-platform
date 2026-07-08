"""
Priority 5 — Manual / Local Market Seed Data
Source  : scraper/data/manual_prices.json
Format  : JSON array (human-maintained)
Use case: Field agents / WhatsApp-forwarded prices from local Rwandan markets
          (Kimironko, Nyabugogo, Gikondo, Musanze, Huye, Rubavu).

How to add prices:
    Edit  scraper/data/manual_prices.json
    The scraper picks them up on the next run.
    Already-inserted records are silently skipped (upsert logic).
"""

import json
from datetime import date
from pathlib import Path
from typing import List

from db.repository import PriceRecord
from scrapers.base import BaseScraper
from utils.helpers import clean_price, normalise_commodity, parse_date

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "manual_prices.json"

# Pre-seeded example records covering all 5 commodities × 6 key markets
SEED_DATA = [
    # Kigali — Kimironko market
    {"commodity": "Maize",        "market": "Kimironko",  "price": 450,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Beans",        "market": "Kimironko",  "price": 680,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Rice",         "market": "Kimironko",  "price": 1100, "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Cooking oil",  "market": "Kimironko",  "price": 2200, "currency": "RWF", "unit": "ltr", "date": "2024-03-01"},
    {"commodity": "Sugar",        "market": "Kimironko",  "price": 950,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    # Kigali — Nyabugogo market
    {"commodity": "Maize",        "market": "Nyabugogo",  "price": 440,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Beans",        "market": "Nyabugogo",  "price": 670,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Rice",         "market": "Nyabugogo",  "price": 1080, "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Cooking oil",  "market": "Nyabugogo",  "price": 2150, "currency": "RWF", "unit": "ltr", "date": "2024-03-01"},
    {"commodity": "Sugar",        "market": "Nyabugogo",  "price": 930,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    # Kigali — Gikondo market
    {"commodity": "Maize",        "market": "Gikondo",    "price": 460,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Beans",        "market": "Gikondo",    "price": 700,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Rice",         "market": "Gikondo",    "price": 1120, "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Cooking oil",  "market": "Gikondo",    "price": 2250, "currency": "RWF", "unit": "ltr", "date": "2024-03-01"},
    {"commodity": "Sugar",        "market": "Gikondo",    "price": 960,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    # Northern — Musanze market
    {"commodity": "Maize",        "market": "Musanze",    "price": 420,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Beans",        "market": "Musanze",    "price": 640,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Rice",         "market": "Musanze",    "price": 1150, "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Cooking oil",  "market": "Musanze",    "price": 2300, "currency": "RWF", "unit": "ltr", "date": "2024-03-01"},
    {"commodity": "Sugar",        "market": "Musanze",    "price": 980,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    # Southern — Huye market
    {"commodity": "Maize",        "market": "Huye",       "price": 430,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Beans",        "market": "Huye",       "price": 660,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Rice",         "market": "Huye",       "price": 1090, "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Cooking oil",  "market": "Huye",       "price": 2180, "currency": "RWF", "unit": "ltr", "date": "2024-03-01"},
    {"commodity": "Sugar",        "market": "Huye",       "price": 940,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    # Western — Rubavu market
    {"commodity": "Maize",        "market": "Rubavu",     "price": 410,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Beans",        "market": "Rubavu",     "price": 650,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Rice",         "market": "Rubavu",     "price": 1060, "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
    {"commodity": "Cooking oil",  "market": "Rubavu",     "price": 2100, "currency": "RWF", "unit": "ltr", "date": "2024-03-01"},
    {"commodity": "Sugar",        "market": "Rubavu",     "price": 920,  "currency": "RWF", "unit": "kg",  "date": "2024-03-01"},
]


class ManualScraper(BaseScraper):
    source_name = "manual"

    def fetch(self) -> List[PriceRecord]:
        raw_data = self._load()
        records: List[PriceRecord] = []

        for item in raw_data:
            commodity = normalise_commodity(str(item.get("commodity", "")))
            if not commodity:
                continue

            price = clean_price(item.get("price"))
            if not price:
                continue

            raw_date = str(item.get("date", date.today()))
            entry_date = parse_date(raw_date) or date.today()

            records.append(PriceRecord(
                commodity=commodity,
                market=str(item.get("market", "Unknown")).strip().title(),
                price=price,
                currency=str(item.get("currency", "RWF")).upper(),
                unit=str(item.get("unit", "kg")).lower(),
                date=entry_date,
                source=self.source_name,
            ))

        return records

    # ── File loading ──────────────────────────────────────────────────────────

    def _load(self) -> list:
        if DATA_FILE.exists():
            try:
                with open(DATA_FILE) as f:
                    data = json.load(f)
                    self.log.info(
                        "Loaded %d manual records from %s", len(data), DATA_FILE
                    )
                    return data
            except Exception as e:
                self.log.error("Failed to read %s: %s — using seed data", DATA_FILE, e)

        # File doesn't exist yet — write seed data and use it
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(SEED_DATA, f, indent=2, default=str)
        self.log.info("Created seed manual_prices.json with %d records", len(SEED_DATA))
        return SEED_DATA
