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
app/scrapers/     rss.py | jobposting.py | festivalapi.py
app/fetcher.py    robots.txt, per-host throttle, retries, block detection
app/filters.py    sanitise -> editorial policy -> scam/trust scoring
app/db.py         SQLite, content-fingerprint dedupe, stale expiry
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
