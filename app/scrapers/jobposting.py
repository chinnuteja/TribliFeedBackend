"""
Opportunity scraper.

Reads a public sitemap, then pulls schema.org JobPosting off each listing page.
Two encodings are in play across the three Indian sources:

  JSON-LD   (AIO Cine, Castkro)  -> <script type="application/ld+json">
  microdata (Dazzlerr)           -> itemprop="..." attributes

Both are the same standard Google uses for job listings, so the same fields come
out either way: title, hiringOrganization, jobLocation, employmentType,
datePosted, validThrough, baseSalary.
"""
import json, re, datetime
from concurrent.futures import ThreadPoolExecutor
from .. import db
from ..fetcher import get, Blocked, FetchError
from ..config import DETAIL_LIMIT, MAX_WORKERS
from ..filters import (clean_text, is_injection, fingerprint,
                       assess_trust, region_tier)

_URLSET = re.compile(r"<url>(.*?)</url>", re.S | re.I)
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
_LASTMOD = re.compile(r"<lastmod>\s*([^<]+?)\s*</lastmod>", re.I)
_LDJSON = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)


def _sitemap_url(source):
    """Some sitemaps are month-partitioned (AIO Cine: jobs-2026-08.xml)."""
    url = source["sitemap"]
    if source.get("sitemap_dynamic"):
        return url.format(ym=datetime.date.today().strftime("%Y-%m"))
    return url


def _sitemap_urls(xml_text, max_age_days=None):
    """Listing URLs, newest <lastmod> first, optionally only recent ones.

    File position is not recency: Castkro's sitemap interleaves 2020 entries
    among 2026 ones, and Dazzlerr's opens with 2020 and ends at 2026 — so the
    old reverse-the-list heuristic was reading whichever end happened to be
    less stale. Every one of the three sources stamps <lastmod> on every entry,
    so sort on it and take the newest.
    """
    entries = []
    for block in _URLSET.findall(xml_text):
        loc = _LOC.search(block)
        if loc:
            lm = _LASTMOD.search(block)
            entries.append((loc.group(1), lm.group(1) if lm else ""))
    if not entries:                      # sitemap without <url> wrappers
        entries = [(u, "") for u in _LOC.findall(xml_text)]
    if max_age_days:
        # <lastmod> is ISO-8601, so a lexical compare on the date part is the
        # whole comparison — no parsing, no timezone maths. An entry with no
        # <lastmod> is kept: unknown age is not evidence of being stale.
        cutoff = (datetime.date.today()
                  - datetime.timedelta(days=max_age_days)).isoformat()
        entries = [e for e in entries if not e[1] or e[1][:10] >= cutoff]
    # Stable sort: entries with no <lastmod> keep file order and sort last.
    entries.sort(key=lambda e: e[1], reverse=True)
    return [u for u, _ in entries]


def _iter_jobposting(node):
    """Walk arbitrary JSON-LD and yield every JobPosting object found."""
    if isinstance(node, list):
        for n in node:
            yield from _iter_jobposting(n)
    elif isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if "JobPosting" in types:
            yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _iter_jobposting(node[key])


def _from_jsonld(html_text):
    for m in _LDJSON.finditer(html_text):
        blob = m.group(1).strip()
        try:
            data = json.loads(blob)
        except Exception:
            continue
        for job in _iter_jobposting(data):
            return job
    return None


def _microdata_prop(html_text, prop):
    for pat in (rf'itemprop=["\']{prop}["\'][^>]*content=["\']([^"\']*)["\']',
                rf'itemprop=["\']{prop}["\'][^>]*>\s*([^<]{{1,300}})\s*<'):
        m = re.search(pat, html_text, re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def _from_microdata(html_text):
    if "schema.org/JobPosting" not in html_text:
        return None
    title = _microdata_prop(html_text, "title")
    if not title:
        return None
    return {
        "title": title,
        "description": _microdata_prop(html_text, "description"),
        "datePosted": _microdata_prop(html_text, "datePosted"),
        "validThrough": _microdata_prop(html_text, "validThrough"),
        "employmentType": _microdata_prop(html_text, "employmentType"),
        "_org": _microdata_prop(html_text, "name"),
        "_city": _microdata_prop(html_text, "addressLocality"),
        "_region": _microdata_prop(html_text, "addressRegion"),
    }


def _norm_date(s):
    """
    Normalise to ISO YYYY-MM-DD.

    Dazzlerr emits DD-MM-YYYY with a time suffix ("31-08-2026T00:00"), so the
    time part has to come off BEFORE testing the day-first pattern — otherwise
    it falls through and gets truncated to a date that reads as YYYY-MM-DD but
    isn't, which silently corrupts every deadline comparison downstream.
    """
    s = (s or "").strip()
    if not s:
        return ""
    s = re.split(r"[T\s]", s)[0]                      # drop any time component
    if re.match(r"^\d{2}-\d{2}-\d{4}$", s):           # DD-MM-YYYY
        d, m, y = s.split("-")
        return f"{y}-{m}-{d}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):           # already ISO
        return s
    return s[:10]


# Publisher boilerplate repeated on every listing — strip it so cards read cleanly.
_BOILER = re.compile(
    r"External casting listing[^.]*\.|"
    r"AIO Cine Productions is the discovery publisher, not the hiring employer\.|"
    r"Applications go to the original source\.|"
    r"Production or hiring organisation|Published details", re.I)


def _normalise(job, url, source):
    if "_org" in job:                                  # microdata shape
        org, city, region = job.get("_org", ""), job.get("_city", ""), job.get("_region", "")
    else:                                              # JSON-LD shape
        o = job.get("hiringOrganization") or {}
        org = o.get("name") if isinstance(o, dict) else o
        loc = job.get("jobLocation") or {}
        if isinstance(loc, list):
            loc = loc[0] if loc else {}
        addr = (loc or {}).get("address") or {}
        city = addr.get("addressLocality", "")
        region = addr.get("addressRegion", "")

    title = clean_text(job.get("title"), 160)
    if not title:
        return None
    desc = clean_text(_BOILER.sub("", job.get("description") or ""), 400)
    if is_injection(title, desc):
        return None

    org = clean_text(org, 90)
    # AIO Cine publishes hiringOrganization.name as null even when the employer
    # is clearly stated in the title and body. Recover it rather than letting the
    # trust scorer flag a legitimate listing as "no named organisation".
    if not org:
        m = re.search(r"Hiring organisation\s+(.+?)\s+(?:Role|Requirement)\b",
                      desc, re.I)
        if m:
            org = clean_text(m.group(1), 90)
    if not org:
        m = re.split(r"\s+[—–]\s+|\s+-\s+", title, maxsplit=1)
        if len(m) == 2 and 2 < len(m[1]) < 60:
            org = clean_text(m[1], 90)
    city = clean_text(city, 60)
    region = clean_text(region, 60)
    if region.upper() == "IN":
        region = ""
    location = ", ".join([p for p in [city.split(",")[0].strip(), region] if p]) or "India"

    trust, reasons, score = assess_trust(
        title, desc, org, source.get("credibility", 3))
    if trust == "blocked":
        return None                                    # never store fee-demand scams

    return dict(
        id=fingerprint(source["id"], title, url),
        kind="opportunity",
        category=source["category"],
        source=source["name"],
        source_id=source["id"],
        publisher=source["name"],
        source_url=source.get("sitemap") or url,
        display_mode="full",
        verified_at="",
        title=title,
        description=desc,
        link=url,
        org=org,
        location=location,
        region_tier=region_tier(title, city, region, desc),
        employment_type=clean_text(job.get("employmentType"), 40).replace("_", " ").title(),
        posted_at=_norm_date(job.get("datePosted")),
        deadline=_norm_date(job.get("validThrough")),
        trust=trust,
        trust_reasons=reasons,
        raw={},
    )


def _fetch_one(args):
    """(url, item|None) once the page was actually retrieved; None if the fetch
    itself failed — those stay unseen so a transient error gets another run."""
    url, source = args
    try:
        html_text = get(url, browser_ua=True)
    except (Blocked, FetchError):
        return None
    job = _from_jsonld(html_text) or _from_microdata(html_text)
    if not job:
        return url, None
    try:
        return url, _normalise(job, url, source)
    except Exception:
        return url, None


def scrape(source):
    sm = _sitemap_url(source)
    urls = _sitemap_urls(get(sm), source.get("max_age_days"))
    limit = min(source.get("limit", DETAIL_LIMIT), DETAIL_LIMIT)

    # Advance into listings we've never parsed. Castkro publishes 456 URLs and
    # AIO Cine 370; taking urls[:limit] every run re-read the same head slice
    # forever and the other ~90% were never seen.
    batch = db.unseen_urls(source["id"], urls, limit)
    if not batch:
        # ponytail: whole sitemap crawled — fall back to re-reading the newest
        # slice, which refreshes deadlines on live listings. Swap for an
        # oldest-first re-check cursor if staleness in the tail starts to matter.
        batch = urls[:limit]

    out, fetched = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for res in ex.map(_fetch_one, [(u, source) for u in batch]):
            if res is None:
                continue                               # retry next run
            url, item = res
            fetched.append(url)
            if item:
                out.append(item)
    db.mark_urls_seen(source["id"], fetched)
    return out, len(batch)
