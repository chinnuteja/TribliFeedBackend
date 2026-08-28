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
scrapers/    rss.py · jobposting.py · festivalapi.py
    |
fetcher.py   robots.txt, per-host rate limiting, retries, block detection
    |
filters.py   sanitise -> editorial policy -> scam/trust scoring
    |
db.py        SQLite. Content-fingerprint dedupe, stale expiry
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

`kind` is `rss`, `jobposting` (sitemap + schema.org JobPosting) or `festivalapi`.

Optional: `refresh_min` (minutes before the source is worth re-running; default
`TRIBLI_INTERVAL_MIN`) and `max_age_days` (ignore sitemap entries whose
`<lastmod>` is older than this).

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
| `FESTIVAL_API_KEY` | — | Festival API key. Without it, Festivals is empty. |
| `TRIBLI_INTERVAL_MIN` | 180 | Minutes between scheduled runs |
| `TRIBLI_DETAIL_LIMIT` | 60 | Job pages fetched per opportunity source per run |
| `TRIBLI_ARTICLE_LIMIT` | 5 | Articles kept per feed per run |
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

## Known state

Run `GET /api/sources` for live status. As of the last run, 25 of 27 configured
sources were healthy. CineD blocks at the CDN even with a browser UA;
StudioBinder's feed is valid but currently publishes zero entries. Both are
reported honestly rather than hidden.
