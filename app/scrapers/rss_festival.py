"""Editorial festival call-for-entry RSS (Asian Film Festivals).

The main feed mixes CFEs with opening-film news. `call_for_entry` is the gate.
The outbound link is the editorial permalink unless the body contains a
confirmed http(s) application URL — we never fetch FilmFreeway to republish it.
"""
import re
import feedparser
from ..config import ARTICLE_LIMIT
from ..fetcher import get
from ..filters import (
    clean_text, is_injection, call_for_entry, extract_deadline,
    deadline_current, fingerprint, region_tier, build_item, is_permalink,
)

_FEE = re.compile(
    r"(?:entry fee|submission fee|fee)\s*[:\-]?\s*(free|\$?\s*\d[\d,]*)",
    re.I)
_HTTP = re.compile(r"https?://[^\s<>\"']+", re.I)
_MEDIA_HOST = (
    "youtube.com", "youtu.be", "vimeo.com", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "tiktok.com", "gravatar.com",
    "wp.com", "wordpress.com",
)
NEEDS_BROWSER_UA = {"asianfilmfestivals"}


def _date(entry):
    from ..scrapers.rss import _date as rss_date
    return rss_date(entry)


def _fee(blob):
    m = _FEE.search(blob or "")
    if not m:
        return ""
    raw = m.group(1).strip()
    if raw.lower() == "free":
        return "Free entry"
    return clean_text(raw, 20)


def _app_url(blob, fallback):
    from urllib.parse import urlparse
    for url in _HTTP.findall(blob or ""):
        url = url.rstrip(").,;]")
        host = (urlparse(url).netloc or "").lower()
        if "asianfilmfestivals.com" in host:
            continue
        if any(h in host for h in _MEDIA_HOST):
            continue
        if is_permalink(url):
            return url
    return fallback


def scrape(source):
    raw = get(source["url"], browser_ua=source["id"] in NEEDS_BROWSER_UA)
    parsed = feedparser.parse(raw)
    out, seen_raw = [], 0
    for e in parsed.entries[:25]:
        seen_raw += 1
        title = clean_text(getattr(e, "title", ""), 180)
        link = (getattr(e, "link", "") or "").strip()
        summary = clean_text(
            getattr(e, "summary", "") or getattr(e, "description", ""), 400)
        content = ""
        if getattr(e, "content", None):
            content = clean_text(e.content[0].value, 800)
        blob = f"{title} {summary} {content}"
        if not title or not link:
            continue
        if is_injection(title, summary, content):
            continue
        if not call_for_entry(title, blob):
            continue
        deadline = extract_deadline(title, blob)
        if deadline and not deadline_current(deadline):
            continue
        loc = "India" if re.search(r"\bIndia\b|\bKerala\b|\bGoa\b|\bChennai\b|"
                                   r"\bBengaluru\b|\bBangalore\b", blob, re.I) else ""
        outbound = _app_url(blob, link)
        out.append(build_item(
            source,
            id=fingerprint(source["id"], title, deadline or link),
            kind="festival",
            title=title,
            link=outbound,
            display_mode="full",
            description=summary,
            location=loc,
            region_tier=region_tier(title, summary) if loc else "global",
            fee=_fee(blob),
            posted_at=_date(e),
            deadline=deadline,
        ))
        if len(out) >= source.get("limit", ARTICLE_LIMIT):
            break
    return out, seen_raw
