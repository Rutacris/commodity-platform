"""
main.py — Scraper Orchestrator
────────────────────────────────────────────────────────────────────────────────
Runs all scrapers in priority order.  Called by cron (via Docker) or manually.

Usage:
    python main.py                    # run all scrapers
    python main.py --sources wfp nisr # run specific scrapers only
    python main.py --dry-run          # fetch only, no DB writes
"""

import argparse
import sys
import time
from typing import List

from db.repository import ensure_schema, init_pool
from scrapers.fews_net import FEWSNETScraper
from scrapers.manual import ManualScraper
from scrapers.minagri import MINAGRIScraper
from scrapers.nisr import NISRScraper
from scrapers.wfp_vam import WFPVAMScraper
from utils.logger import get_logger

log = get_logger("main")

# ── Registry — order = priority ───────────────────────────────────────────────
SCRAPER_REGISTRY = {
    "wfp":     WFPVAMScraper,
    "nisr":    NISRScraper,
    "minagri": MINAGRIScraper,
    "fews":    FEWSNETScraper,
    "manual":  ManualScraper,
}


def run(sources: List[str] = None, dry_run: bool = False) -> dict:
    """
    Run scrapers and return a summary dict.
    sources=None means run all (in priority order).
    """
    if not dry_run:
        init_pool()
        ensure_schema()

    selected = sources or list(SCRAPER_REGISTRY.keys())
    unknown  = [s for s in selected if s not in SCRAPER_REGISTRY]
    if unknown:
        log.error("Unknown scraper(s): %s — valid: %s", unknown, list(SCRAPER_REGISTRY))
        sys.exit(1)

    summary = {}
    total_inserted = 0

    log.info("═" * 60)
    log.info("Starting commodity scrape run")
    log.info("Sources: %s", selected)
    log.info("Dry run: %s", dry_run)
    log.info("═" * 60)

    for name in selected:
        scraper = SCRAPER_REGISTRY[name]()
        t0 = time.time()

        if dry_run:
            records = scraper.fetch()
            inserted = len(records)
            log.info("[DRY RUN] %s would produce %d records", name, inserted)
        else:
            inserted = scraper.run()

        elapsed = round(time.time() - t0, 1)
        summary[name] = {"inserted": inserted, "elapsed_s": elapsed}
        total_inserted += inserted

    log.info("═" * 60)
    log.info("Run complete — %d new rows inserted across %d sources",
             total_inserted, len(selected))
    for name, stats in summary.items():
        log.info("  %-10s  +%3d rows  (%ss)", name, stats["inserted"], stats["elapsed_s"])
    log.info("═" * 60)

    return summary


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rwanda Commodity Price Scraper")
    parser.add_argument(
        "--sources", nargs="+",
        choices=list(SCRAPER_REGISTRY.keys()),
        help="Run only these scrapers (default: all)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch data but do not write to the database",
    )
    args = parser.parse_args()
    run(sources=args.sources, dry_run=args.dry_run)
