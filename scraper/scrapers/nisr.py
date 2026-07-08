"""
Priority 2 — NISR (National Institute of Statistics Rwanda)
Source  : statistics.gov.rw — CPI / food price publications
Format  : Excel (.xlsx / .xls) or CSV
Strategy: Crawl the publications page, find downloadable spreadsheets,
          parse them and extract target commodity prices.
"""

import io
import re
import tempfile
from datetime import date
from typing import List, Optional
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import NISR_CPI_URL, NISR_BASE_URL
from db.repository import PriceRecord
from scrapers.base import BaseScraper
from utils.helpers import (
    clean_price, download_file, normalise_commodity,
    parse_date, safe_get,
)


class NISRScraper(BaseScraper):
    source_name = "nisr"

    # Keywords that suggest a food-price spreadsheet
    _FILE_KEYWORDS = ["price", "cpi", "food", "commodity", "market"]
    _FILE_EXTS     = (".xlsx", ".xls", ".csv")

    def fetch(self) -> List[PriceRecord]:
        links = self._discover_file_links()
        if not links:
            self.log.warning("No spreadsheet links found on NISR page")
            return []

        all_records: List[PriceRecord] = []
        for url in links:
            self.log.info("Processing NISR file: %s", url)
            records = self._process_file(url)
            all_records.extend(records)

        return all_records

    # ── Link discovery ────────────────────────────────────────────────────────

    def _discover_file_links(self) -> List[str]:
        resp = safe_get(NISR_CPI_URL)
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        found = []
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if any(href.lower().endswith(ext) for ext in self._FILE_EXTS):
                text = a.get_text(strip=True).lower()
                if any(kw in text or kw in href.lower()
                       for kw in self._FILE_KEYWORDS):
                    full_url = urljoin(NISR_BASE_URL, href)
                    found.append(full_url)
        self.log.info("Discovered %d NISR file links", len(found))
        # Only process the 3 most recent to avoid hammering the server
        return found[:3]

    # ── File processing ───────────────────────────────────────────────────────

    def _process_file(self, url: str) -> List[PriceRecord]:
        with tempfile.NamedTemporaryFile(suffix=self._suffix(url)) as tmp:
            if not download_file(url, tmp.name):
                return []
            try:
                if url.endswith(".csv"):
                    df = pd.read_csv(tmp.name)
                else:
                    df = pd.read_excel(tmp.name, sheet_name=None)
                    # Merge all sheets into one DataFrame
                    df = pd.concat(df.values(), ignore_index=True)
            except Exception as e:
                self.log.error("Failed to read %s: %s", url, e)
                return []

        return self._parse_dataframe(df, source_url=url)

    def _parse_dataframe(self, df: pd.DataFrame, source_url: str) -> List[PriceRecord]:
        """
        NISR sheets vary in layout — we do a fuzzy column search rather than
        assuming fixed column names.
        """
        df.columns = [str(c).strip().lower() for c in df.columns]
        records: List[PriceRecord] = []

        commodity_col = self._find_col(df, ["commodity", "item", "product", "description"])
        price_col     = self._find_col(df, ["price", "unit price", "amount", "value"])
        date_col      = self._find_col(df, ["date", "month", "period", "year"])
        market_col    = self._find_col(df, ["market", "district", "region", "location"])

        if commodity_col is None or price_col is None:
            self.log.warning("Cannot identify key columns in %s — cols: %s",
                             source_url, list(df.columns))
            return []

        for _, row in df.iterrows():
            commodity = normalise_commodity(str(row.get(commodity_col, "")))
            if not commodity:
                continue

            price = clean_price(row.get(price_col))
            if not price or price <= 0:
                continue

            raw_date = str(row[date_col]) if date_col else str(date.today())
            entry_date = parse_date(raw_date) or date.today()

            market = (
                str(row[market_col]).strip().title()
                if market_col else "National (NISR)"
            )

            records.append(PriceRecord(
                commodity=commodity,
                market=market,
                price=price,
                currency="RWF",
                unit="kg",
                date=entry_date,
                source=self.source_name,
            ))

        return records

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _find_col(df: pd.DataFrame, candidates: list) -> Optional[str]:
        for name in candidates:
            if name in df.columns:
                return name
        # partial match
        for name in candidates:
            for col in df.columns:
                if name in col:
                    return col
        return None

    @staticmethod
    def _suffix(url: str) -> str:
        for ext in (".xlsx", ".xls", ".csv"):
            if url.lower().endswith(ext):
                return ext
        return ".xlsx"
