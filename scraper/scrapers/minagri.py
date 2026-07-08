"""
Priority 3 — MINAGRI / RAB (Rwanda Agriculture Board)
Source  : rab.gov.rw — market price bulletins
Format  : PDF (text extracted with pdfplumber, then sent to Ollama)
"""

import tempfile
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

try:
    import pdfplumber
    _PDF_AVAILABLE = True
except ImportError:
    _PDF_AVAILABLE = False

from config import RAB_PRICES_URL, RAB_BASE_URL
from db.repository import PriceRecord
from normalizers.ollama import extract_prices
from scrapers.base import BaseScraper
from utils.helpers import download_file, safe_get


class MINAGRIScraper(BaseScraper):
    source_name = "minagri_rab"

    _PDF_KEYWORDS = ["price", "market", "bulletin", "commodity", "report"]

    def fetch(self) -> List[PriceRecord]:
        if not _PDF_AVAILABLE:
            self.log.error("pdfplumber not installed — cannot scrape PDFs")
            return []

        pdf_links = self._find_pdf_links()
        if not pdf_links:
            self.log.warning("No PDF links found on RAB page")
            return []

        all_records: List[PriceRecord] = []
        # Process latest 2 bulletins to avoid very long CPU runs
        for url in pdf_links[:2]:
            self.log.info("Processing RAB PDF: %s", url)
            text = self._extract_pdf_text(url)
            if text:
                records = extract_prices(text, source=self.source_name)
                all_records.extend(records)

        return all_records

    # ── Link discovery ────────────────────────────────────────────────────────

    def _find_pdf_links(self) -> List[str]:
        resp = safe_get(RAB_PRICES_URL)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith(".pdf"):
                text = a.get_text(strip=True).lower()
                if any(kw in text or kw in href.lower()
                       for kw in self._PDF_KEYWORDS):
                    links.append(urljoin(RAB_BASE_URL, href))

        self.log.info("Found %d PDF links on RAB page", len(links))
        return links

    # ── PDF text extraction ───────────────────────────────────────────────────

    def _extract_pdf_text(self, url: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            if not download_file(url, tmp.name):
                return ""
            try:
                pages_text = []
                with pdfplumber.open(tmp.name) as pdf:
                    for page in pdf.pages[:10]:   # cap at 10 pages
                        text = page.extract_text()
                        if text:
                            pages_text.append(text)
                result = "\n".join(pages_text)
                self.log.info(
                    "Extracted %d chars from PDF: %s",
                    len(result), url
                )
                return result
            except Exception as e:
                self.log.error("PDF extraction failed for %s: %s", url, e)
                return ""
