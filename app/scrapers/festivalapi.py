"""
Festival API client (festivalapi.com).

The only paid product in the pipeline, and it runs on the free tier.
Credits are consumed per search. Named query plans stop at
FESTIVAL_API_CREDIT_CAP. A failed page is recorded, not swallowed as a
short successful list. Auth / 402 remain terminal Blocked.
"""
import datetime
from ..fetcher import get_json, Blocked, FetchError
from ..config import FESTIVAL_API_KEY, FESTIVAL_API_CREDIT_CAP
from ..filters import clean_text, fingerprint, build_item, region_tier

BASE = "https://festivalapi.com/v1"

_run_notes = []


def take_run_notes():
    notes = list(_run_notes)
    _run_notes.clear()
    return notes


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
    deadline = (f.get("deadline_regular") or f.get("nearest_deadline")
                or f.get("deadline") or "")[:10]
    if not tier:
        country = (f.get("country") or "")
        tier = "india" if country.lower() == "india" else "global"

    return build_item(
        {"id": "festivalapi", "name": "Festival API", "category": "festivals",
         "publisher": "Festival API"},
        id=fingerprint("festivalapi", name, link),
        kind="festival",
        title=name,
        link=link,
        display_mode="full",
        description=(f"Accepts: {cats}" if cats else clean_text(f.get("description"), 250)),
        org=clean_text(f.get("organizer"), 90),
        location=loc,
        region_tier=tier,
        fee=fee,
        posted_at="",
        deadline=deadline,
        raw={"event_dates": f.get("event_dates"), "query_tier": tier},
    )


def query_plans(today=None):
    """Named searches, cheapest India-first. Cost is Festival API credits."""
    today = today or datetime.date.today().isoformat()
    return [
        dict(id="india_open", cost=1, tier="india",
             url=(f"{BASE}/festivals/?country=India&deadline_after={today}"
                  f"&sort=deadline&sort_dir=asc&limit=20&page=1")),
        dict(id="india_short", cost=1, tier="india",
             url=(f"{BASE}/festivals/?country=India&category=short_film"
                  f"&deadline_after={today}&limit=20&page=1")),
        dict(id="closing_soon", cost=2, tier="",
             url=f"{BASE}/deadlines/closing-soon?days=21&limit=20"),
        dict(id="india_doc", cost=1, tier="india",
             url=(f"{BASE}/festivals/?country=India&category=documentary"
                  f"&deadline_after={today}&limit=20&page=1")),
        dict(id="global_open", cost=1, tier="global",
             url=(f"{BASE}/festivals/?deadline_after={today}&limit=20&page=1")),
    ]


def scrape(source):
    """India / short / closing-soon first, then a bounded international slice."""
    _run_notes.clear()
    cap = int(source.get("credit_cap") or FESTIVAL_API_CREDIT_CAP)
    spent = 0
    out, raw_count = [], 0
    seen = set()
    headers = _headers()
    planned = query_plans()
    ran = []

    for plan in planned:
        if spent + plan["cost"] > cap:
            _run_notes.append(
                f"skipped {plan['id']} (would be {spent + plan['cost']}/{cap} credits)")
            continue
        try:
            data = get_json(plan["url"], headers=headers)
        except Blocked:
            raise
        except FetchError as e:
            _run_notes.append(f"{plan['id']}: {e}")
            continue
        except Exception as e:
            _run_notes.append(f"{plan['id']}: {type(e).__name__}: {e}")
            continue
        spent += plan["cost"]
        ran.append(plan["id"])
        results = data.get("results") or data.get("festivals") or []
        if isinstance(data, list):
            results = data
        raw_count += len(results)
        for f in results:
            fid = f.get("id") or f.get("name")
            if fid in seen:
                continue
            seen.add(fid)
            item = _norm(f, plan["tier"])
            if item:
                out.append(item)

    _run_notes.append(f"credits={spent}/{cap} queries={','.join(ran) or 'none'}")
    return out, raw_count
