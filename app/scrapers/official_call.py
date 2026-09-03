"""Curated official-call validator.

Does not infer facts from page prose. The registry already holds title,
permalink, deadline, and publisher. This scraper only confirms the permalink
is still a public, robots-allowed, non-index URL and that the deadline has
not passed. A blocked page is a source-health event, not a stale card.
"""
import datetime
from ..fetcher import get, FetchError
from ..filters import (
    clean_text, is_injection, is_permalink, deadline_current, build_item,
    region_tier,
)

KIND_FOR_CATEGORY = {
    "casting": "opportunity",
    "festivals": "festival",
    "grants": "article",
    "education": "article",
}


def _kind(source):
    return KIND_FOR_CATEGORY.get(source.get("category"), "article")


def scrape(source):
    call = source.get("call") or {}
    title = clean_text(call.get("title") or source.get("name"), 180)
    permalink = (call.get("permalink") or "").strip()
    deadline = (call.get("deadline") or "")[:10]
    publisher = call.get("publisher") or source.get("name")
    seen_raw = 1

    if not title or not permalink:
        return [], seen_raw
    if not is_permalink(permalink):
        return [], seen_raw
    if not deadline_current(deadline):
        return [], seen_raw
    if is_injection(title, publisher, permalink):
        return [], seen_raw

    # Reachability is the whole scrape. Body text is discarded on purpose.
    html_text = get(permalink)
    if not (html_text or "").strip():
        raise FetchError(f"empty body at {permalink}")
    low = html_text[:1500].lower()
    if ("sign in" in low or "log in" in low) and "password" in low:
        return [], seen_raw

    kind = _kind(source)
    loc = call.get("location") or ""
    item = build_item(
        source,
        kind=kind,
        title=title,
        link=permalink,
        display_mode="redirect",
        description=clean_text(call.get("description") or "", 240),
        org=clean_text(publisher, 90),
        location=clean_text(loc, 60),
        region_tier=call.get("region_tier") or region_tier(title, loc, publisher),
        fee=clean_text(call.get("fee") or "", 40),
        posted_at=(call.get("opened_at") or "")[:10],
        deadline=deadline,
        publisher=publisher,
        source_url=permalink,
        verified_at=datetime.date.today().isoformat(),
        trust="external",
        trust_reasons=[],
    )
    return [item], seen_raw
