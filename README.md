# TRIBLI Feed Backend

A real ingestion pipeline for the TRIBLI feed. It scrapes live sources on a
schedule, filters and de-duplicates them, scores opportunities for scam
patterns, and serves the result over an HTTP API that the frontend consumes.

This is **not** a static snapshot. Nothing is baked into the HTML.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env                 # then put your real key in it
python run.py
```

`.env` is gitignored and read at startup by `app/config.py`. A real exported
environment variable still wins over the file, so CI needs no `.env`.

Open http://localhost:8000

```bash
python run.py --ingest       # one scrape pass, no server
python run.py --no-scrape    # serve existing data only
```

## How it works

```
sources.py   registry — the only file you edit to add a source
    |
scrapers/    rss.py · rss_opportunity.py · rss_festival.py ·
             jobposting.py · festivalapi.py · official_call.py
    |
fetcher.py   robots.txt, per-host rate limiting, retries, block detection
    |
filters.py   sanitise -> editorial policy -> scam/trust scoring
             plus permalink / job / call-for-entry quality gates
    |
db.py        SQLite. Provenance, content-fingerprint dedupe, stale expiry
    |
api.py       FastAPI. The frontend never touches a source directly.
```

### Why a backend at all
Browsers cannot fetch most of these feeds — CORS blocks cross-origin requests
and almost none of these publishers allow it. Filtering, de-duplication and
scam scoring also have to happen server-side, before a user ever sees an item.

## Adding a source

One entry in `app/sources.py`:

```python
dict(id="example", name="Example", kind="rss", category="tech",
     url="https://example.com/feed/", credibility=4)
```

`kind` is one of:

| kind | What it pulls | Card |
|---|---|---|
| `rss` | Generic RSS/Atom | full article |
| `rss_opportunity` | Job RSS; explainers dropped | full opportunity |
| `rss_festival` | Call-for-entry RSS; news dropped | full festival |
| `jobposting` | Sitemap + schema.org JobPosting | full opportunity |
| `festivalapi` | Licensed Festival API (credit-capped) | full festival |
| `official_call` | Curated permalink + deadline only | redirect |

Item `kind` stays `opportunity | festival | article`. Acquisition is `display_mode: full | redirect`, so category filters, Telugu/South views, and card layouts keep working.

Optional: `refresh_min` (minutes before the source is worth re-running; default
`TRIBLI_INTERVAL_MIN`) and `max_age_days` (ignore sitemap entries whose
`<lastmod>` is older than this). Festival API and official calls are weekly.

### Quality ladder

- **full ingest** — public structured data or RSS, robots allow, we store the listing.
- **redirect-only** — TRIBLI chrome + the exact official application/call URL. No copied body, no publisher image. Requires permalink + title + a deadline that has not passed.
- **watching** — no public per-post URL or current dated window yet (Screen Entry, reelOn, annual funds). Not a card.
- **rejected for quality** — reachable HTML is not authentic per-call data (CastYou-style directories). FilmFreeway is rejected on ToS and is never scraped; Festival API may still emit a FilmFreeway *outbound* submit link.
- **blocked** — 403, paywall, or robots deny. Shown in `/api/sources`, never worked around.

Homepages, category indexes (`/auditions`, `/alljobs`), login walls, and undated SEO pages cannot become feed items.

### Adding an official call

Probe the permalink first (status, content-type, robots). Then:

```python
dict(id="examplefund", name="Example Fund", kind="official_call",
     category="grants", credibility=5, refresh_min=10080, publisher="Example",
     call=dict(
         title="Example Fund 2026",
         permalink="https://example.org/fund-2026",
         deadline="2026-12-01",
         publisher="Example",
         description="TRIBLI-written blurb. Never paste publisher HTML.",
     ))
```

When `deadline` is past, ingest stores nothing and `expire_stale` deactivates any previous card. Do not invent a window. Closed programmes belong in `NOT_INGESTING` with `acquisition="watch"` until a current permalink exists.

## Safety

Three independent layers, deliberately kept separate:

1. **Sanitising** — strips script injection. Not theoretical: SRFTI's official
   feed (a government film school) has served `<script>alert(1)</script>` as a
   post title.
2. **Editorial policy** — drops box office, trailers, reviews, gossip and
   affiliate gear deals.
3. **Scam scoring** — listings demanding payment from applicants, or requesting
   Aadhaar/PAN/bank details up front, are **never stored**. Exploitation-risk
   patterns are quarantined for human review. Nothing is ever auto-marked as
   TRIBLI-verified; that requires a human or a confirmed Organization link.

## Scraping posture

`robots.txt` is fetched and enforced on every request. A source that blocks us
is recorded as blocked and surfaced in the UI — we do not try to defeat bot
protection. A browser User-Agent is sent only where the site's own robots.txt
grants access and an edge CDN is rejecting non-browser agents.

## Configuration

All via environment variables, read from the process environment or from a
gitignored `.env` at the repo root — see `app/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `FESTIVAL_API_KEY` | — | Festival API key. Without it, Festival API is blocked. |
| `TRIBLI_INTERVAL_MIN` | 180 | Minutes between scheduled runs |
| `TRIBLI_DETAIL_LIMIT` | 60 | Job pages fetched per JobPosting source per run |
| `TRIBLI_ARTICLE_LIMIT` | 5 | Articles kept per craft/trade feed per run |
| `TRIBLI_OPP_RSS_LIMIT` | 15 | Jobs kept per opportunity RSS source per run |
| `TRIBLI_FESTIVAL_CREDITS` | 6 | Hard cap on Festival API search credits per run |
| `TRIBLI_DELAY` | 1.0 | Seconds between hits to the same host |
| `TRIBLI_ROBOTS` | 1 | Enforce robots.txt |

The API key is read from the environment and never written to source.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/feed?category=&limit=&offset=` | Paginated, source-interleaved feed |
| `GET /api/categories` | Categories with live counts |
| `GET /api/sources` | Full source intelligence + why each gap exists |
| `GET /api/health` | Item and source health |
| `POST /api/ingest?source=` | Trigger a run on demand |

Feed items include provenance: `source_id`, `publisher`, `source_url`, `display_mode` (`full` or `redirect`), and `verified_at` (ISO date, redirect cards only). `link` is always the exact outbound post or application URL. Raw source payloads are never returned. Quarantined listings are omitted.

`/api/sources` totals include `watching` and `rejected_quality`. Live sources report `acquisition` of `full` or `redirect`.

## Known state

Run `GET /api/sources` for live status. New in this expansion: Animation and VFX Jobs (full opportunity RSS), Asian Film Festivals (CFE-only RSS), ALT EFF Film Fund (redirect-only official call). CastYou and Talent Katta are rejected for quality; Screen Entry, reelOn, and closed annual funds are watching until a public permalink exists. FilmFreeway is never scraped.
