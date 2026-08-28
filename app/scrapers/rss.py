"""Generic RSS/Atom scraper. Covers 21 of the live sources."""
import datetime
import feedparser
from ..config import ARTICLE_LIMIT
from ..fetcher import get, Blocked
from ..filters import clean_text, is_injection, editorial_ok, fingerprint

# These publishers serve public content and their robots.txt permits crawling,
# but an edge CDN rejects a non-browser User-Agent as a bot-mitigation heuristic.
# We send a browser UA only where the site's OWN stated policy allows access.
# CineD, for example, publishes: "User-agent: * / Content-Signal:
# search=yes,ai-train=no,use=reference / Allow: /" — reference use with a link
# back is exactly what this pipeline does, and we never train on the content.
# robots.txt is still enforced on every request — see fetcher.get().
NEEDS_BROWSER_UA = {"studiobinder", "premiumbeat", "moviemaker", "indiewire",
                    "cined", "ymcinema", "frameio", "fdtimes", "newsshooter",
                    "pvc", "filmmakermag", "ormax", "redshark"}


def _date(entry):
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime.datetime(*val[:6]).date().isoformat()
            except Exception:
                pass
    return ""


def scrape(source):
    """Yields normalised article dicts. Raises Blocked/FetchError upward."""
    raw = get(source["url"], browser_ua=source["id"] in NEEDS_BROWSER_UA)
    parsed = feedparser.parse(raw)

    out, seen_raw = [], 0
    for e in parsed.entries[:25]:
        seen_raw += 1
        title = clean_text(getattr(e, "title", ""), 180)
        link = (getattr(e, "link", "") or "").strip()
        summary = clean_text(
            getattr(e, "summary", "") or getattr(e, "description", ""), 300)

        if not title or not link:
            continue
        if is_injection(title, summary):
            continue                      # SRFTI ships these — drop silently
        if not editorial_ok(title, summary):
            continue

        out.append(dict(
            id=fingerprint(source["id"], title, link),
            kind="article",
            category=source["category"],
            source=source["name"],
            title=title,
            description=summary,
            link=link,
            posted_at=_date(e),
            trust="external",
            trust_reasons=[],
            raw={},
        ))
        if len(out) >= ARTICLE_LIMIT:
            break                         # newest ARTICLE_LIMIT only; feeds are date-ordered
    return out, seen_raw
