# Config-Driven Web Scraper

A small scraping engine: **one Python file, one YAML config per site**. Adding a new
target site means writing ~10 lines of YAML (CSS selectors + pagination), not new code.

Built as a portfolio piece for freelance data-extraction jobs.

## What it does
- Fetches paginated listings and extracts each item into a CSV row
- **YAML site configs** — selectors, field extraction rules, pagination, delay
- Normalizes messy fields on the way out (prices → numbers, star ratings → 1–5, tags → pipe list)
- Respects `robots.txt` (checked once per host) and throttles requests (default 1s)
- Retries failed requests once, logs per-page progress
- CLI overrides: `--max-pages`, `--delay`, `--out`, `--ignore-robots`

## Quick start
```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

python scraper.py --config config/books.yaml
python scraper.py --config config/quotes.yaml --max-pages 5
```

Output lands in `output/<site>.csv`.

## Adding a new site
Copy `config/books.yaml`, change `start_urls`, `item_selector` and the `fields` map:

```yaml
name: my_site
start_urls:
  - https://example.com/listings
item_selector: "div.listing-card"
pagination_next: "a.next-page"
fields:
  title:   { selector: "h2" }
  price:   { selector: "span.price", extract: price }
  link:    { selector: "a", extract: "attr:href" }
  extras:  { selector: "ul.meta li", extract: multi }
```

Extraction modes: `text` (default), `attr:<name>`, `price`, `rating`, `multi`.

## Example output
`books_toscrape.csv` (40 rows, 2 pages):

| title | price | rating | stock |
|---|---|---|---|
| A Light in the Attic | 51.77 | 3 | In stock |
| Sharp Objects | 47.82 | 4 | In stock |

## Notes
- Demo configs point at [books.toscrape.com](https://books.toscrape.com) and
  [quotes.toscrape.com](https://quotes.toscrape.com) — sandbox sites explicitly made
  for scraping practice.
- For real client work: same engine, different YAML; JS-heavy sites get a Playwright
  variant instead of requests+BeautifulSoup.

## Stack
Python 3.12 · requests · BeautifulSoup (lxml) · PyYAML
