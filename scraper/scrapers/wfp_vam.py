"""
Priority 1 — WFP VAM (World Food Programme)
Source  : Humanitarian Data Exchange (HDX) public CSV
URL     : https://data.humdata.org  (Rwanda food prices dataset)
Fallback: WFP VAM REST API  (api.vam.wfp.org)
Format  : CSV
"""

import io
from datetime import date
from typing import List

import pandas as pd

from config import WFP_HDX_URL, WFP_API_URL
from db.repository import PriceRecord
from scrapers.base import BaseScraper
from utils.helpers import clean_price, normalise_commodity, parse_date, safe_get
from utils.logger import get_logger

log = get_logger(__name__)

# WFP HDX CSV column names (as of 2024 schema)
_COL_MAP = {
    "date":      ["date", "mp_year", "period"],
    "market":    ["market", "mkt_name"],
    "commodity": ["commodity", "cm_name"],
    "price":     ["price", "mp_price"],
    "currency":  ["currency", "cur_name"],
    "unit":      ["unit", "um_name"],
}


def _find_col(df: pd.DataFrame, candidates: list) -> str | None:
    """Return the first column name in candidates that exists in df."""
    cols_lower = {c.lower(): c for c in df.columns}
    for name in candidates:
        if name.lower() in cols_lower:
            return cols_lower[name.lower()]
    return None


class WFPVAMScraper(BaseScraper):
    source_name = "wfp_vam"

    def fetch(self) -> List[PriceRecord]:
        records = self._fetch_hdx_csv()
        if records:
            return records
        self.log.warning("HDX CSV failed — trying WFP API fallback")
        return self._fetch_api()

    # ── HDX CSV path ─────────────────────────────────────────────────────────

    def _fetch_hdx_csv(self) -> List[PriceRecord]:
        resp = safe_get(WFP_HDX_URL)
        if not resp:
            return []
        try:
            df = pd.read_csv(io.StringIO(resp.text), low_memory=False)
        except Exception as e:
            self.log.error("CSV parse error: %s", e)
            return []

        self.log.info("WFP HDX CSV: %d rows × %d cols", len(df), len(df.columns))
        return self._parse_dataframe(df)

    # ── WFP API fallback ─────────────────────────────────────────────────────

    def _fetch_api(self) -> List[PriceRecord]:
        resp = safe_get(WFP_API_URL)
        if not resp:
            return []
        try:
            payload = resp.json()
            rows = payload.get("items") or payload.get("data") or []
            if not rows:
                return []
            df = pd.DataFrame(rows)
            return self._parse_dataframe(df)
        except Exception as e:
            self.log.error("WFP API parse error: %s", e)
            return []

    # ── Shared parser ─────────────────────────────────────────────────────────

    def _parse_dataframe(self, df: pd.DataFrame) -> List[PriceRecord]:
        col = {k: _find_col(df, v) for k, v in _COL_MAP.items()}
        missing = [k for k, v in col.items() if v is None]
        if missing:
            self.log.error("Cannot map columns: %s — available: %s",
                           missing, list(df.columns))
            return []

        records: List[PriceRecord] = []
        for _, row in df.iterrows():
            raw_commodity = str(row[col["commodity"]])
            commodity = normalise_commodity(raw_commodity)
            if commodity is None:
                continue        # skip non-target commodities

            price = clean_price(row[col["price"]])
            if price is None or price <= 0:
                continue

            raw_date = str(row[col["date"]])
            parsed_date = parse_date(raw_date) or date.today()

            records.append(PriceRecord(
                commodity=commodity,
                market=str(row[col["market"]]).strip().title(),
                price=price,
                currency=str(row.get(col["currency"], "RWF")).strip().upper(),
                unit=str(row.get(col["unit"], "kg")).strip().lower(),
                date=parsed_date,
                source=self.source_name,
            ))

        return records
