"""Job-oriented RSS. Same fetch path as craft blogs; different item kind.

Animation-and-VFX-Jobs is the first source. The feed mixes studio vacancies
with the occasional software explainer — `opportunity_relevant` drops the
explainers so they never land on the Opportunities rail.
"""
import re
import feedparser
from ..config import OPPORTUNITY_RSS_LIMIT
from ..fetcher import get, Blocked, FetchError
from ..filters import (
    clean_text, is_injection, assess_trust, region_tier,
    opportunity_relevant, extract_deadline, build_item, is_permalink,
)

_ORG_AT = re.compile(r"\bat\s+(.+)$", re.I)
_LABEL = re.compile(
    r"(?:^|\n)\s*(Studio|Company|Location|Job Opening|Job Type|Type|"
    r"Experience|Deadline)\s*[:\-]\s*(.+)",
    re.I)
NEEDS_BROWSER_UA = {"avjobs"}


def _date(entry):
    from ..scrapers.rss import _date as rss_date
    return rss_date(entry)


def _org_from_title(title):
    m = _ORG_AT.search(title or "")
    return clean_text(m.group(1), 90) if m else ""


def _labels(text):
    found = {}
    for m in _LABEL.finditer(text or ""):
        found[m.group(1).lower()] = clean_text(m.group(2), 120)
    return found


def _enrich(html_text):
    """Generic labeled-field scrape. Empty on missing labels — never guess."""
    if not html_text:
        return {}
    plain = clean_text(html_text, 4000)
    labels = _labels(plain.replace(". ", "\n"))
    out = {}
    if labels.get("studio") or labels.get("company"):
        out["org"] = labels.get("studio") or labels.get("company")
    if labels.get("location"):
        out["location"] = labels.get("location")
    if labels.get("job type") or labels.get("type"):
        out["employment_type"] = labels.get("job type") or labels.get("type")
    dl = extract_deadline(labels.get("deadline", ""), plain)
    if dl:
        out["deadline"] = dl
    return out


def scrape(source):
    raw = get(source["url"], browser_ua=source["id"] in NEEDS_BROWSER_UA)
    parsed = feedparser.parse(raw)
    out, seen_raw = [], 0
    for e in parsed.entries[:40]:
        seen_raw += 1
        title = clean_text(getattr(e, "title", ""), 180)
        link = (getattr(e, "link", "") or "").strip()
        summary = clean_text(
            getattr(e, "summary", "") or getattr(e, "description", ""), 400)
        cats = " ".join(
            (t.term if hasattr(t, "term") else str(t))
            for t in (getattr(e, "tags", None) or []))
        blob = f"{title} {summary} {cats}"

        if not title or not link:
            continue
        if not is_permalink(link):
            continue
        if is_injection(title, summary):
            continue
        if not opportunity_relevant(title, blob):
            continue

        org = _org_from_title(title)
        extra = {}
        try:
            extra = _enrich(get(link, browser_ua=source["id"] in NEEDS_BROWSER_UA))
        except (Blocked, FetchError):
            extra = {}
        org = extra.get("org") or org
        location = extra.get("location") or ""
        if not location:
            for token in ("Hyderabad", "Chennai", "Bengaluru", "Bangalore",
                          "Mumbai", "Kochi", "Andhra", "India"):
                if token.lower() in blob.lower():
                    location = token
                    break
        employment = extra.get("employment_type") or ""
        deadline = extra.get("deadline") or extract_deadline(blob)

        trust, reasons, _ = assess_trust(
            title, blob, org, source.get("credibility", 3))
        if trust == "blocked":
            continue

        out.append(build_item(
            source,
            kind="opportunity",
            title=title,
            link=link,
            display_mode="full",
            description=summary,
            org=org,
            location=location or "India",
            region_tier=region_tier(title, summary, cats, location),
            employment_type=employment,
            posted_at=_date(e),
            deadline=deadline,
            trust=trust,
            trust_reasons=reasons,
        ))
        if len(out) >= source.get("limit", OPPORTUNITY_RSS_LIMIT):
            break
    return out, seen_raw
