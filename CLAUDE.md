# TRIBLI Feed Backend — working agreement

You are working on a real ingestion pipeline that scrapes live film-industry
sources, filters them, and serves them over an API. It is running code with
real data, not a scaffold.

## Non-negotiables

1. **Run the pipeline after every change.** `python run.py --ingest`
   A scraper that imports cleanly can still return zero items. StudioBinder
   looked healthy for a whole build while returning nothing. Import success
   is not proof of anything.

2. **Never invent a source.** Every source in `app/sources.py` was verified by
   an actual HTTP request. If you add one, probe it first and paste the real
   status code and content-type into the commit message. No plausible-looking
   URLs.

3. **Report blocks honestly.** If a site returns 403 or bot-protection, record
   it as blocked and surface it. Do not add evasion (proxy rotation, header
   spoofing beyond what robots.txt permits, rate-limit dodging). A blocked
   source is information the product displays, not a problem to defeat.

4. **robots.txt stays enforced.** `TRIBLI_ROBOTS=1` is the default and stays
   that way. Note the existing bug fix in `app/fetcher.py`: Python's
   `RobotFileParser.read()` treats a 403 on robots.txt as "disallow all", which
   silently blocked 10 healthy sources. Do not reintroduce that pattern.

5. **Never weaken the scam filters in `app/filters.py`.** Listings that demand
   money from applicants or request Aadhaar/PAN/bank details are never stored.
   Nothing is ever auto-marked TRIBLI-verified. If a filter produces false
   positives, fix the extraction feeding it — do not loosen the rule.

6. **Secrets come from the environment.** `FESTIVAL_API_KEY` is read via
   `os.getenv`. Never hardcode it, never commit it, never print it.

## Before you claim something works

Paste the actual output of:
```bash
python run.py --ingest        # source-by-source results
curl localhost:8000/api/health
```
"Should work" is not acceptable. Show the numbers.

## Architecture

```
app/sources.py    registry — the ONLY file to edit when adding a source
app/scrapers/     rss.py | rss_opportunity.py | rss_festival.py | jobposting.py
                  | festivalapi.py | official_call.py
app/fetcher.py    robots.txt, per-host throttle, retries, block detection
app/filters.py    sanitise -> editorial policy -> scam/trust scoring
                  plus permalink / job / call-for-entry quality gates
app/db.py         SQLite, provenance, content-fingerprint dedupe, stale expiry
app/pipeline.py   orchestrator; one source failing must not stop the run
app/api.py        FastAPI; the frontend never touches a source directly
```

## Known real bugs already fixed — do not regress these

- Dazzlerr sends `31-08-2026T00:00` (day-first WITH a time suffix). The time
  part must be stripped before the day-first test, or it truncates into a
  string that looks ISO but isn't, silently corrupting every deadline.
- AIO Cine publishes `hiringOrganization.name: null` even when the employer is
  named in the title/description. There is a fallback extractor; keep it.
- Quarantined items must never appear in `/api/feed`.

## Source kinds and acquisition

`kind` on a feed item stays semantic: `opportunity | festival | article`.
How TRIBLI acquired it is `display_mode: full | redirect`, not a fourth kind.

| Scraper `kind` in `sources.py` | Item `kind` | `display_mode` | When to use |
|---|---|---|---|
| `rss` | article | full | Craft/trade/education/grant blogs |
| `rss_opportunity` | opportunity | full | Job RSS (Animation and VFX Jobs). Non-job posts are dropped. |
| `rss_festival` | festival | full | Editorial CFE RSS (Asian Film Festivals). Opening-film news is dropped. |
| `jobposting` | opportunity | full | Sitemap + schema.org JobPosting |
| `festivalapi` | festival | full | Licensed Festival API. FilmFreeway is outbound only. |
| `official_call` | by category | redirect | Curated permalink + current deadline. Body is not scraped. |

Acquisition status on `/api/sources`:

- **full ingest** — structured public data, robots allow, we store the listing.
- **redirect-only** — we card TRIBLI chrome + the exact official URL. No copied body or image.
- **watching** — no public per-post permalink or current dated call yet. Not a card.
- **rejected for quality** — reachable, but directory/SEO/unauthenticated dumps fail the permalink gate (CastYou, Talent Katta). FilmFreeway is rejected on ToS, not quality of listings.
- **blocked** — HTTP 403, paywall, or robots deny. Honest source health, never evaded.

A redirect card requires a single-call permalink, a title, and a deadline that has not passed. Homepages, `/auditions`, `/alljobs`, login walls, and undated SEO pages emit nothing.

To add an official call, put `kind="official_call"` plus a `call=` dict with `title`, `permalink`, `deadline` (ISO date), and `publisher`. Probe the permalink first. When the window closes, the next ingest deactivates the card (`deadline < today`); do not leave a stale grant on the rail. Closed programmes stay in `NOT_INGESTING` with `acquisition="watch"` until a current permalink exists.

Cadence: Festival API and official calls default to weekly (`refresh_min=10080`). Opportunity RSS uses `TRIBLI_OPP_RSS_LIMIT` (default 15) so an hourly board cannot bury AIO Cine. Festival API stops at `TRIBLI_FESTIVAL_CREDITS` (default 6).

Never log in, bypass Cloudflare, scrape FilmFreeway, hotlink publisher photos, fabricate a deadline, or auto-mark `trust=verified`. `trust` remains `external | caution | quarantine`.
