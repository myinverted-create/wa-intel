#!/usr/bin/env python3
"""
Fetch new commercial-construction-relevant tenders from Tenders WA and write to
data/tenders.json so the dashboard's Tenders panel can render them.

Tenders WA does not consistently publish a public RSS feed, so this script
uses HTML scraping of the public 'Current Tenders' search page filtered for
construction-related categories. If WA Govt changes the page structure, edit
the SOURCE_URL and parse_html() below.

The script is defensive: if the source can't be fetched or parsed, it writes
an empty list with an error note rather than crashing the whole workflow.
"""

import os
import sys
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
TENDERS_FILE = REPO_ROOT / "data" / "tenders.json"

AWST = timezone(timedelta(hours=8))

# Tenders WA public 'current tenders' listing.
# To narrow further, append a category filter param after testing in browser.
SOURCE_URL = os.environ.get(
    "TENDERS_SOURCE_URL",
    "https://www.tenders.wa.gov.au/watenders/tender/list.do?action=current-tender-list"
)

# Keywords that mark a tender as commercial-construction relevant.
COMMERCIAL_KEYWORDS = [
    "construction", "fitout", "fit out", "fit-out", "refurbishment",
    "office", "school", "hospital", "health", "education", "warehouse",
    "data centre", "data center", "retail", "commercial", "building works",
    "extension", "upgrade works"
]
EXCLUDE_KEYWORDS = [
    "road", "highway", "bridge", "rail", "wastewater", "sewer",
    "water main", "pipeline", "marine", "dredg", "mining", "ore",
    "residential", "house", "dwelling"
]


def fetch_html() -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; WA-Recruit-Intel-Dashboard/1.0)"
    }
    r = requests.get(SOURCE_URL, headers=headers, timeout=60)
    r.raise_for_status()
    return r.text


def looks_commercial(text: str) -> bool:
    low = text.lower()
    if any(k in low for k in EXCLUDE_KEYWORDS):
        return False
    return any(k in low for k in COMMERCIAL_KEYWORDS)


def parse_html(html: str) -> list:
    """
    Light-touch extractor. Tenders WA renders rows in a <table>; we pull
    visible row text and any tender detail links. If the page structure
    changes, this still degrades gracefully — at worst returns [].
    """
    tenders = []

    # Strip scripts/styles to keep regex sane
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style\b.*?</style>", "", html, flags=re.S | re.I)

    # Find all <tr> rows that contain at least one link to a tender detail
    row_pattern = re.compile(r"<tr\b[^>]*>(.*?)</tr>", flags=re.S | re.I)
    link_pattern = re.compile(
        r'href="([^"]*tender[^"]*\.do[^"]*)"[^>]*>(.*?)</a>',
        flags=re.S | re.I,
    )
    tag_strip = re.compile(r"<[^>]+>")
    ws = re.compile(r"\s+")

    for row_html in row_pattern.findall(html):
        m = link_pattern.search(row_html)
        if not m:
            continue
        href = m.group(1)
        title = ws.sub(" ", tag_strip.sub("", m.group(2))).strip()
        row_text = ws.sub(" ", tag_strip.sub(" ", row_html)).strip()
        if not title:
            continue
        if not looks_commercial(row_text):
            continue
        url = href
        if url.startswith("/"):
            url = "https://www.tenders.wa.gov.au" + url
        tenders.append({
            "title": title[:240],
            "summary": row_text[:400],
            "url": url,
        })

    # Dedupe on title
    seen = set()
    unique = []
    for t in tenders:
        if t["title"] in seen:
            continue
        seen.add(t["title"])
        unique.append(t)

    return unique[:25]


def main() -> None:
    now = datetime.now(AWST).isoformat()
    out = {
        "fetched_at": now,
        "source": SOURCE_URL,
        "tenders": [],
        "error": None,
    }
    try:
        html = fetch_html()
        out["tenders"] = parse_html(html)
        print(f"Fetched {len(out['tenders'])} commercial-relevant tenders.")
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        print(f"Tender fetch failed (non-fatal): {out['error']}", file=sys.stderr)

    TENDERS_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
