#!/usr/bin/env python3
"""
Config-driven web scraper: one engine, one YAML config per site.

Adding a new site means writing a short YAML file (selectors + pagination),
not new Python code.

Usage:
    python scraper.py --config config/books.yaml
    python scraper.py --config config/quotes.yaml --max-pages 5 --out output/quotes.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
import yaml
from bs4 import BeautifulSoup

USER_AGENT = "PortfolioScraper/1.0 (portfolio project; educational use)"
TIMEOUT = 15
RATING_WORDS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


@dataclass
class FieldSpec:
    """One column: which CSS selector (relative to the item) and how to extract it."""
    name: str
    selector: str
    extract: str = "text"  # text | attr:<name> | rating | price | multi


@dataclass
class SiteConfig:
    name: str
    start_urls: list[str]
    item_selector: str
    fields: list[FieldSpec]
    pagination_next: str | None = None
    delay_s: float = 1.0
    max_pages: int = 10


def load_config(path: Path) -> SiteConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    fields = [
        FieldSpec(name=name, selector=spec["selector"], extract=spec.get("extract", "text"))
        for name, spec in raw["fields"].items()
    ]
    return SiteConfig(
        name=raw["name"],
        start_urls=list(raw["start_urls"]),
        item_selector=raw["item_selector"],
        fields=fields,
        pagination_next=raw.get("pagination_next"),
        delay_s=float(raw.get("delay_s", 1.0)),
        max_pages=int(raw.get("max_pages", 10)),
    )


class RobotsChecker:
    """Check robots.txt once per host so we don't hammer it either."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._cache: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        if not self.enabled:
            return True
        parsed = urlparse(url)
        host = parsed.netloc
        if host not in self._cache:
            parser = RobotFileParser()
            parser.set_url(f"{parsed.scheme}://{host}/robots.txt")
            try:
                parser.read()
            except Exception:
                parser = None  # robots.txt unreachable -> proceed, delay still applies
            self._cache[host] = parser
        parser = self._cache[host]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)


def get_soup(session: requests.Session, url: str) -> BeautifulSoup | None:
    """Fetch a page, one retry on failure."""
    for attempt in (1, 2):
        try:
            resp = session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except requests.RequestException as exc:
            if attempt == 2:
                print(f"  ! giving up on {url}: {exc}", file=sys.stderr)
                return None
            time.sleep(2)
    return None


def extract_value(node, extract: str) -> str:
    if extract.startswith("attr:"):
        return node.get(extract[5:], "") or ""
    if extract == "rating":
        # class looks like: star-rating Three
        classes = [c for c in node.get("class", []) if c in RATING_WORDS]
        return str(RATING_WORDS[classes[0]]) if classes else ""
    if extract == "price":
        # "£51.77" -> "51.77" (keeps digits and decimal point only)
        return "".join(ch for ch in node.get_text(strip=True) if ch.isdigit() or ch == ".")
    return node.get_text(strip=True)


def extract_row(item, fields: list[FieldSpec]) -> dict[str, str]:
    """Build one CSV row from one listing item (selectors are relative to it)."""
    row: dict[str, str] = {}
    for spec in fields:
        nodes = item.select(spec.selector)
        if not nodes:
            row[spec.name] = ""  # missing field -> empty cell, don't crash the row
        elif spec.extract == "multi":
            row[spec.name] = " | ".join(n.get_text(strip=True) for n in nodes)
        else:
            row[spec.name] = extract_value(nodes[0], spec.extract)
    return row


def scrape_site(config: SiteConfig, robots: RobotsChecker) -> list[dict[str, str]]:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    rows: list[dict[str, str]] = []

    for start_url in config.start_urls:
        url: str | None = start_url
        page = 0
        while url and page < config.max_pages:
            if not robots.allowed(url):
                print(f"  robots.txt disallows {url}, skipping", file=sys.stderr)
                break
            soup = get_soup(session, url)
            if soup is None:
                break

            items = soup.select(config.item_selector)
            for item in items:
                rows.append(extract_row(item, config.fields))
            print(f"  page {page + 1}: {len(items)} items ({url})")

            # follow pagination
            url = None
            if config.pagination_next:
                nxt = soup.select_one(config.pagination_next)
                if nxt and nxt.get("href"):
                    url = urljoin(url or start_url, nxt["href"])
            page += 1
            if url:
                time.sleep(config.delay_s)

    return rows


def write_csv(rows: list[dict[str, str]], path: Path, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Config-driven scraper (YAML site configs).")
    ap.add_argument("--config", required=True, type=Path, help="site config, e.g. config/books.yaml")
    ap.add_argument("--out", type=Path, default=None, help="output CSV (default: output/<site>.csv)")
    ap.add_argument("--max-pages", type=int, default=None, help="override max pages from config")
    ap.add_argument("--delay", type=float, default=None, help="override delay between requests (seconds)")
    ap.add_argument("--ignore-robots", action="store_true", help="skip robots.txt check")
    args = ap.parse_args()

    config = load_config(args.config)
    if args.max_pages is not None:
        config.max_pages = args.max_pages
    if args.delay is not None:
        config.delay_s = args.delay

    out = args.out or Path("output") / f"{config.name}.csv"
    rows = scrape_site(config, RobotsChecker(enabled=not args.ignore_robots))
    if not rows:
        print("No rows extracted -- check the selectors in the config.", file=sys.stderr)
        return 1

    write_csv(rows, out, [f.name for f in config.fields])
    print(f"{config.name}: {len(rows)} rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
