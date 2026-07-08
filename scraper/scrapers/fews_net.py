"""
Priority 4 — FEWS NET (Famine Early Warning Systems Network)
Source  : fews.net/east-africa/rwanda
Format  : HTML narrative + inline price tables
Strategy: Parse HTML tables first; fall back to Ollama for narrative text.
"""

import re
from datetime import date
from typing import List
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup

from config import FEWS_RWANDA_URL, FEWS_BASE_URL
from db.repository import PriceRecord
from normalizers.ollama import extract_prices
from scrapers.base import BaseScraper
from utils.helpers import (
    clean_price, normalise_commodity, parse_date, safe_get,
)


class FEWSNETScraper(BaseScraper):
    source_name = "fews_net"

    def fetch(self) -> List[PriceRecord]:
        resp = safe_get(FEWS_RWANDA_URL)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        records: List[PriceRecord] = []

        # ── Try HTML tables first (fast, structured) ──────────────────────────
        table_records = self._parse_tables(soup)
        records.extend(table_records)
        self.log.info("Parsed %d records from HTML tables", len(table_records))

        # ── Dive into linked price-monitoring reports ──────────────────────────
        report_links = self._find_report_links(soup)
        self.log.info("Found %d FEWS report links", len(report_links))

        for url in report_links[:2]:        # 2 most recent only (CPU budget)
            self.log.info("Fetching FEWS report: %s", url)
            report_resp = safe_get(url)
            if not report_resp:
                continue

            report_soup = BeautifulSoup(report_resp.text, "html.parser")
            tbl = self._parse_tables(report_soup)
            if tbl:
                records.extend(tbl)
            else:
                # No tables — extract prose and send to Ollama
                text = report_soup.get_text(separator="\n", strip=True)
                ollama_records = extract_prices(text, source=self.source_name)
                records.extend(ollama_records)

        return records

    # ── HTML table parser ─────────────────────────────────────────────────────

    def _parse_tables(self, soup: BeautifulSoup) -> List[PriceRecord]:
        records: List[PriceRecord] = []
        try:
            tables = pd.read_html(str(soup))
        except Exception:
            return []

        for df in tables:
            df.columns = [str(c).strip().lower() for c in df.columns]
            commodity_col = next(
                (c for c in df.columns if "commodity" in c or "item" in c), None
            )
            price_col = next(
                (c for c in df.columns if "price" in c or "cost" in c), None
            )
            if commodity_col is None or price_col is None:
                continue

            for _, row in df.iterrows():
                commodity = normalise_commodity(str(row[commodity_col]))
                if not commodity:
                    continue
                price = clean_price(row[price_col])
                if not price:
                    continue

                date_col = next(
                    (c for c in df.columns if "date" in c or "month" in c), None
                )
                market_col = next(
                    (c for c in df.columns if "market" in c or "district" in c), None
                )

                records.append(PriceRecord(
                    commodity=commodity,
                    market=(
                        str(row[market_col]).strip().title()
                        if market_col else "Rwanda (FEWS)"
                    ),
                    price=price,
                    currency="RWF",
                    unit="kg",
                    date=(
                        parse_date(str(row[date_col])) or date.today()
                        if date_col else date.today()
                    ),
                    source=self.source_name,
                ))
        return records

    # ── Link discovery ────────────────────────────────────────────────────────

    def _find_report_links(self, soup: BeautifulSoup) -> List[str]:
        links = []
        _KEYWORDS = ["price", "market", "monitor", "bulletin", "rwanda"]
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True).lower()
            if any(kw in text or kw in href.lower() for kw in _KEYWORDS):
                full = urljoin(FEWS_BASE_URL, href) if href.startswith("/") else href
                if full not in links:
                    links.append(full)
        return links[:5]
