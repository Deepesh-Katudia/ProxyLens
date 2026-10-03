"""Fetching and identifying official source documents."""

import logging
import re
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "ProxyLens-research/0.1 (+https://github.com/Deepesh-Katudia/ProxyLens)"
DOWNLOAD_TIMEOUT_S = 120

# Consolidated LODR, "Last amended on July 14, 2026". Listed at
# https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListingLegal=yes&sid=1&ssid=3&smid=0
LODR_PAGE_URL = (
    "https://www.sebi.gov.in/legal/regulations/jul-2026/securities-and-exchange-board-of-india-"
    "listing-obligations-and-disclosure-requirements-regulations-2015-last-amended-on-july-14-"
    "2026-_102974.html"
)
LODR_PDF_URL = "https://www.sebi.gov.in/sebi_data/attachdocs/jul-2026/1784630770711.pdf"

_AMENDED_UP_TO = re.compile(r"Amended up to\s+([A-Z][a-z]+ \d{1,2},\s*\d{4})", re.IGNORECASE)


def download_cached(url: str, dest: Path) -> Path:
    """Download `url` to `dest` once; later calls reuse the cached file."""
    if dest.exists() and dest.stat().st_size > 0:
        logger.info("Using cached %s", dest)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s", url)
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True
    ) as client:
        response = client.get(url)
        response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise ValueError(f"{url} did not return a PDF")
    dest.write_bytes(response.content)
    return dest


def amended_up_to(first_page_text: str) -> str | None:
    """ISO date from a consolidated text's '[Amended up to July 14, 2026]' banner."""
    match = _AMENDED_UP_TO.search(first_page_text)
    if match is None:
        return None
    parsed = datetime.strptime(re.sub(r"\s+", " ", match.group(1)), "%B %d, %Y")
    return parsed.date().isoformat()
