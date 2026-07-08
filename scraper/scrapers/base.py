from abc import ABC, abstractmethod
from typing import List

from db.repository import PriceRecord, bulk_upsert
from utils.logger import get_logger


class BaseScraper(ABC):
    """
    All scrapers inherit from this class.

    Subclasses must implement:
        source_name  → str  (used for the 'source' column in DB)
        fetch()      → list[PriceRecord]  (all the scraping logic)

    Optionally override:
        validate(records) → list[PriceRecord]  (filter/clean records)
    """

    source_name: str = "unknown"

    def __init__(self):
        self.log = get_logger(f"scrapers.{self.__class__.__name__}")

    # ── Public interface ──────────────────────────────────────────────────────

    def run(self) -> int:
        """
        Orchestrate fetch → validate → store.
        Returns the number of newly inserted rows.
        """
        self.log.info("▶ Starting %s", self.source_name)
        try:
            records = self.fetch()
            self.log.info("  Fetched   %d raw records", len(records))
            records = self.validate(records)
            self.log.info("  Validated %d records", len(records))
            inserted = bulk_upsert(records)
            self.log.info("  Inserted  %d new rows  (skipped %d duplicates)",
                          inserted, len(records) - inserted)
            return inserted
        except Exception as e:
            self.log.exception("✗ %s failed: %s", self.source_name, e)
            return 0

    # ── Abstract ──────────────────────────────────────────────────────────────

    @abstractmethod
    def fetch(self) -> List[PriceRecord]:
        """Fetch and parse data from the source. Return raw PriceRecord list."""

    # ── Overrideable ──────────────────────────────────────────────────────────

    def validate(self, records: List[PriceRecord]) -> List[PriceRecord]:
        """
        Drop records with missing/invalid fields.
        Subclasses can extend this for source-specific cleaning.
        """
        valid = []
        for r in records:
            if not r.commodity:
                self.log.debug("Skipping — no commodity: %s", r)
                continue
            if r.price is None or r.price <= 0:
                self.log.debug("Skipping — invalid price: %s", r)
                continue
            if not r.date:
                self.log.debug("Skipping — no date: %s", r)
                continue
            valid.append(r)
        return valid
