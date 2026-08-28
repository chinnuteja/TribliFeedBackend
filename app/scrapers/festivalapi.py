"""
Festival API client (festivalapi.com).

The only paid product in the pipeline, and it runs on the free tier.
Credits are consumed per search, so we deliberately make few, wide calls
rather than many narrow ones, and only ask for deadlines that are still open.
"""
import datetime
from ..fetcher import get_json, Blocked
from ..config import FESTIVAL_API_KEY
from ..filters import clean_text, fingerprint

BASE = "https://festivalapi.com/v1"


def _headers():
    if not FESTIVAL_API_KEY:
        raise Blocked("FESTIVAL_API_KEY is not set in the environment")
    return {"Authorization": f"Bearer {FESTIVAL_API_KEY}"}


def _norm(f, tier):
    name = clean_text(f.get("name"), 160)
    link = (f.get("submission_url") or f.get("website") or "").strip()
    if not name or not link:
        return None

    fee = ""
    raw_fee = f.get("regular_fee")
    if raw_fee not in (None, "", 0):
        try:
            fee = f"${float(raw_fee):.0f} entry"
        except (TypeError, ValueError):
            fee = str(raw_fee)[:20]

    loc = ", ".join([p for p in [f.get("city") or "", f.get("country") or ""] if p])
    cats = ", ".join((f.get("categories") or [])[:3])

    return dict(
        id=fingerprint("festivalapi", name, link),
        kind="festival",
        category="festivals",
        source="Festival API",
        title=name,
        description=(f"Accepts: {cats}" if cats else clean_text(f.get("description"), 250)),
        link=link,
        org=clean_text(f.get("organizer"), 90),
        location=loc,
        region_tier=tier,
        fee=fee,
        deadline=(f.get("deadline_regular") or "")[:10],
        posted_at="",
        trust="external",
        trust_reasons=[],
        raw={"event_dates": f.get("event_dates")},
    )


def scrape(source):
    """India-first, then a slice of open international calls."""
    today = datetime.date.today().isoformat()
    out, raw_count = [], 0

    plans = [
        (f"{BASE}/festivals/?country=India&deadline_after={today}&limit=20&page=1", "india"),
        (f"{BASE}/festivals/?country=India&deadline_after={today}&limit=20&page=2", "india"),
        (f"{BASE}/festivals/?deadline_after={today}&limit=20&page=1", "global"),
    ]

    seen = set()
    for url, tier in plans:
        try:
            data = get_json(url, headers=_headers())
        except Blocked:
            raise
        except Exception:
            continue
        results = data.get("results", [])
        raw_count += len(results)
        for f in results:
            fid = f.get("id")
            if fid in seen:
                continue
            seen.add(fid)
            item = _norm(f, tier)
            if item:
                out.append(item)
        if data.get("page", 1) >= data.get("total_pages", 1) and tier == "india":
            continue
    return out, raw_count
