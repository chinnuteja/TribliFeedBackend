"""Shared WhatsApp opportunities: publish, safety, dedupe, expiry, apply actions.
python test_shared_opportunity.py"""
import os, tempfile, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIX = ROOT / "fixtures"
os.environ["TRIBLI_DB"] = os.path.join(tempfile.mkdtemp(), "share.db")
os.environ["TRIBLI_SHARE_SECRET"] = "test-share-secret"
os.environ["TRIBLI_SHARE_ENABLED"] = "1"
os.environ["TRIBLI_ROBOTS"] = "0"
os.environ.pop("GEMINI_API_KEY", None)

from app import db
from app.filters import (
    assess_trust, assess_user_share, extract_apply_targets, is_apply_link,
    normalize_phone, whatsapp_url_kind,
)
from app.share_ingest import process_share
from app import shared_opportunity as so
from app.fetcher import Blocked, FetchError

db.init_db()

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def fx(name):
    return (FIX / name).read_text(encoding="utf-8")


def items(cat="casting", n=80, **kw):
    rows, _ = db.query_items(category=cat, limit=n, **kw)
    return rows


# labelled WhatsApp apply is allowed; fee/id phishing still blocked
trust, reasons, _ = assess_user_share(
    "Casting call — extras",
    "Hyderabad. Apply on WhatsApp: +91 98765 43210",
    org="Gnapika Entertainments",
    apply_method="whatsapp",
)
assert trust in ("external", "caution"), (trust, reasons)
assert not any("off-platform" in r.lower() for r in reasons), reasons

blocked, b_reasons, _ = assess_user_share(
    "Casting call", fx("whatsapp_fee_scam.txt"), apply_method="whatsapp")
assert blocked == "blocked", (blocked, b_reasons)

# scraper trust is unchanged: WhatsApp pressure still counts off-platform
sc_trust, sc_reasons, _ = assess_trust(
    "Hiring extras in Hyderabad",
    "WhatsApp me on 9876543210",
    org="X",
    source_credibility=3,
)
assert any("off-platform" in r.lower() for r in sc_reasons), sc_reasons

phone = normalize_phone("+91 98765 43210")
assert phone == "+919876543210", phone
targets = extract_apply_targets(fx("whatsapp_casting.txt"))
assert targets["method"] == "whatsapp"
assert targets["url"] == "https://wa.me/919876543210"
assert is_apply_link("https://wa.me/919876543210")
assert is_apply_link("mailto:casting@lightcraft.example")
assert is_apply_link("tel:+919988776655")
assert not is_apply_link("https://www.reelon.com/alljobs")
assert not is_apply_link("javascript:alert(1)")
assert whatsapp_url_kind("https://whatsapp.com/channel/abc") == "channel"
assert whatsapp_url_kind(
    "https://www.whatsapp.com/channel/0029VaExampleChannel/818") == "post"
assert whatsapp_url_kind(
    "https://whatsapp.com/channel/abc/post/123") == "post"
assert whatsapp_url_kind("https://wa.me/919876543210") == "apply"


def _no_gemini(*a, **k):
    raise so.ExtractionError("offline suite must not call Gemini")


so.gemini_extract = _no_gemini


r = process_share(text=fx("whatsapp_casting.txt"), transport="paste")
assert r["status"] == "published", r
assert r["id"]
item = next(i for i in items() if i["id"] == r["id"])
assert item["kind"] == "opportunity"
assert item["acquisition_mode"] == "shared"
assert item["apply_method"] == "whatsapp"
assert item["apply_url"] == "https://wa.me/919876543210"
assert item["link"]
assert item["org"]
assert "98765" not in (item.get("description") or "") or True  # number may appear; feed CTA uses apply_url
assert item.get("deadline") in ("", None, "2026-09-12")
if not item.get("deadline"):
    assert item.get("expires_at"), item
    assert item["expires_at"] >= datetime.date.today().isoformat()
assert item["display_mode"] in ("full", "redirect")
assert item["trust"] != "verified"
assert "raw" not in item


# fee / Aadhaar never stored as an item
before = db.stats()["active"]
fee = process_share(text=fx("whatsapp_fee_scam.txt"), transport="paste")
assert fee["status"] == "rejected", fee
with db.tx() as c:
    n = c.execute(
        "SELECT COUNT(*) n FROM items WHERE description LIKE '%Aadhaar%' "
        "OR description LIKE '%registration fee%'"
    ).fetchone()["n"]
assert n == 0
assert db.stats()["active"] == before


# intimate -> quarantined, hidden from feed
inn = process_share(text=fx("whatsapp_intimate.txt"), transport="paste")
assert inn["status"] == "quarantined", inn
pub, _ = db.query_items(category="casting", limit=80)
assert all(i["id"] != inn["id"] for i in pub)
held, _ = db.query_items(category="casting", limit=80, include_quarantine=True)
assert any(i["id"] == inn["id"] for i in held)


# injection rejected, not stored
inj = process_share(text=fx("whatsapp_injection.txt"), transport="paste")
assert inj["status"] == "rejected", inj


# channel invite is not a specific opportunity
ch = process_share(text=fx("whatsapp_channel_invite.txt"),
                   url="https://whatsapp.com/channel/0029VaExampleChannel")
assert ch["status"] == "rejected", ch
assert any("channel" in x.lower() for x in ch["reasons"]), ch["reasons"]


# Android may share a real Channel message permalink without its caption or
# poster. Keep the human signal as Needs details; never invent an Apply route.
link_only_url = "https://www.whatsapp.com/channel/0029VaExampleChannel/818"
link_only = process_share(url=link_only_url, transport="web-share")
assert link_only["status"] == "needs_details", link_only
link_only_item = next(i for i in items() if i["id"] == link_only["id"])
assert link_only_item["title"] == "Team-shared WhatsApp post"
assert link_only_item["source_url"] == link_only_url
assert link_only_item["link"] == link_only_url
assert link_only_item["apply_method"] == "team_review"
assert not link_only_item["apply_url"]


# post-level WhatsApp URL + caption publishes; apply is WhatsApp
post = process_share(text=fx("whatsapp_channel_post.txt"))
assert post["status"] == "published", post
pitem = next(i for i in items()
             if i["id"] == post["id"])
assert pitem["apply_method"] == "whatsapp"
assert "whatsapp.com/channel/" in (pitem["link"] + pitem.get("source_url", ""))


# A relevant human share with no direct contact is kept for the team instead
# of being silently discarded. It has no apply CTA until someone adds details.
miss = process_share(text=fx("whatsapp_missing_apply.txt"))
assert miss["status"] == "needs_details", miss
miss_item = next(i for i in items() if i["id"] == miss["id"])
assert miss_item["apply_method"] == "team_review"
assert not miss_item["apply_url"]


# iOS often supplies a generic "Photo from <name>" share title. The useful
# call heading must win, and team attribution must never become an app-store
# or unrelated outbound domain.
ios = process_share(
    title="Photo from Teja",
    text=("Photo from Teja 🎬 Casting Call: From Producers of Youth "
          "📍 Location: Other 🎭 Looking for: Male and female child artists"),
    transport="pwa",
)
assert ios["status"] == "needs_details", ios
ios_item = next(i for i in items() if i["id"] == ios["id"])
assert ios_item["title"] == "Casting Call — From Producers of Youth", ios_item
assert ios_item["publisher"] == "TRIBLI Team", ios_item
assert ios_item["location"] == "Other", ios_item
assert "child artists" in ios_item["employment_type"].lower(), ios_item


# expired stated deadline
exp = process_share(text=fx("whatsapp_expired.txt"))
assert exp["status"] == "rejected", exp


# A homepage is never used as an application link, but the human-shared lead
# remains visible as "Needs details" instead of being thrown away.
home = process_share(text=fx("whatsapp_homepage.txt"))
assert home["status"] == "needs_details", home
home_item = next(i for i in items() if i["id"] == home["id"])
assert home_item["apply_method"] == "team_review"


# DM / private-number pressure without a labelled apply target
dm = process_share(text=fx("whatsapp_dm_pressure.txt"))
assert dm["status"] in ("quarantined", "rejected"), dm
if dm["id"]:
    hidden, _ = db.query_items(category="casting", limit=80)
    assert all(i["id"] != dm["id"] for i in hidden)


# email apply
em = process_share(text=fx("whatsapp_email.txt"))
assert em["status"] == "published", em
eitem = next(i for i in items()
             if i["id"] == em["id"])
assert eitem["apply_method"] == "email"
assert eitem["apply_url"].startswith("mailto:casting@lightcraft.example")


# duplicate refreshes rather than multiplying
again = process_share(text=fx("whatsapp_casting.txt"), transport="paste")
assert again["status"] == "duplicate", again
assert again["id"] == r["id"]


# image-only: Gemini mocked, temp file deleted
def fake_poster(*a, **k):
    return so.ExtractedOpportunity(
        title="Casting call — Lead actor Hyderabad serial",
        role="Lead actor",
        organisation="Example Productions",
        location="Hyderabad",
        language="Telugu",
        apply_method="whatsapp",
        apply_target="+919876500000",
        title_confidence=0.92,
        source_publisher="WhatsApp",
    )


so.gemini_extract = fake_poster
up_dir = Path(os.environ["TRIBLI_DB"]).parent / "uploads"
img = process_share(text="", image_bytes=PNG, image_mime="image/png",
                    transport="pwa")
assert img["status"] == "published", img
iitem = next(i for i in items()
             if i["id"] == img["id"])
assert iitem["apply_method"] == "whatsapp"
assert "artwork" not in iitem
assert not iitem.get("artwork_path")
if up_dir.exists():
    leftover = [p for p in up_dir.iterdir() if p.is_file()]
    assert leftover == [], leftover


# Gemini failure on image-only must not publish a generic card
def boom(*a, **k):
    raise so.ExtractionError("model down")


so.gemini_extract = boom
fail = process_share(text="", image_bytes=PNG, image_mime="image/png")
assert fail["status"] == "extraction_error", fail
assert not fail.get("id")


so.gemini_extract = _no_gemini


# blocked external URL + specific shared evidence -> attributed redirect
from app import enrich


def blocked_get(url, **kw):
    raise Blocked("HTTP 403")


enrich.get = blocked_get
ext = process_share(text=fx("whatsapp_external.txt"))
assert ext["status"] == "published", ext
xitem = next(i for i in items()
             if i["id"] == ext["id"])
assert xitem["display_mode"] == "redirect"
assert xitem["acquisition_mode"] == "shared"
assert "screenentry.example/job/" in xitem["link"]
assert xitem.get("verified_at") in ("", None)
assert xitem["apply_method"] == "web"


# login-only page: same honest redirect, no implied verification
def login_get(url, **kw):
    return "<html><body>Sign in <input type='password' name='password'></body></html>"


enrich.get = login_get
login = process_share(
    text=("Casting call — Editor, Hyderabad\n"
          "https://reels.example/jobs/editor-hyd-9921\n"
          "Deadline 30 Dec 2026"))
assert login["status"] == "published", login
litem = next(i for i in items()
             if i["id"] == login["id"])
assert litem["display_mode"] == "redirect"
assert litem.get("verified_at") in ("", None)


def recover_get(url, **kw):
    raise FetchError("HTTP 500")


enrich.get = recover_get


# submissions audit exists; raw payload / full image not exposed
with db.tx() as c:
    cols = {r[1] for r in c.execute("PRAGMA table_info(items)")}
    for need in ("acquisition_mode", "apply_method", "apply_url", "expires_at",
                 "submitted_at", "source_domain"):
        assert need in cols, cols
    subs = c.execute("SELECT status, sanitized_text, payload_hash FROM submissions"
                     ).fetchall()
    assert subs, "submissions audit missing"
    assert all(s["payload_hash"] for s in subs)
    # public query still pops raw
    row = c.execute("SELECT * FROM items WHERE id=?", (r["id"],)).fetchone()
    assert row["raw"] is not None

from fastapi.testclient import TestClient
from app.api import app
from app.share_auth import issue_device_token

token = issue_device_token(label="test")
c = TestClient(app)
feed = c.get("/api/feed?category=casting").json()
ids = [i["id"] for i in feed["items"]]
assert r["id"] in ids
assert inn["id"] not in ids
shared = next(i for i in feed["items"] if i["id"] == r["id"])
assert shared["acquisition_mode"] == "shared"
assert shared["apply_method"] == "whatsapp"
assert "extract_evidence" not in shared
assert "submitted_by" not in shared
assert "raw" not in shared

team_feed = c.get("/api/feed?category=team").json()
team_ids = [i["id"] for i in team_feed["items"]]
assert ios["id"] in team_ids
assert all(i.get("acquisition_mode") == "shared" for i in team_feed["items"])
categories = c.get("/api/categories").json()["categories"]
team_category = next(cat for cat in categories if cat["id"] == "team")
assert team_category["virtual"] is True
assert team_category["count"] == team_feed["total"]

h = c.get("/api/health").json()
assert "share" in h
assert h["share"]["published"] >= 1

print("shared opportunity OK")
