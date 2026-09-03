"""API returns provenance, hides quarantine, escapes nothing in JSON (frontend escapes).
python test_api_cards.py"""
import os, tempfile
os.environ["TRIBLI_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")

from fastapi.testclient import TestClient
from app import db
from app.api import app

db.init_db()
db.upsert_items([
    dict(id="full1", kind="opportunity", category="casting", source="AIO Cine",
         source_id="aiocine", publisher="AIO Cine", display_mode="full",
         title="Gaffer — Hyderabad", description="Crew call",
         link="https://aiocine.com/jobs/gaffer", location="Hyderabad",
         region_tier="telugu", org="Example PH", trust="external",
         deadline="2026-09-15"),
    dict(id="redir1", kind="article", category="grants", source="ALT EFF Film Fund",
         source_id="alteff", publisher="ALT EFF", display_mode="redirect",
         title="ALT EFF Film Fund 2026", description="Apply on the official page.",
         link="https://www.alteff.in/film-fund", trust="external",
         deadline="2026-12-10", verified_at="2026-08-31"),
    dict(id="q1", kind="opportunity", category="casting", source="X",
         title="Bold shoot", link="https://x.example/q", trust="quarantine",
         display_mode="full"),
])

c = TestClient(app)
feed = c.get("/api/feed?category=casting").json()
ids = [i["id"] for i in feed["items"]]
assert "full1" in ids
assert "q1" not in ids
full = next(i for i in feed["items"] if i["id"] == "full1")
assert full["display_mode"] == "full"
assert full["source_id"] == "aiocine"
assert "raw" not in full

grants = c.get("/api/feed?category=grants").json()
redir = next(i for i in grants["items"] if i["id"] == "redir1")
assert redir["display_mode"] == "redirect"
assert redir["link"] == "https://www.alteff.in/film-fund"
assert redir["publisher"] == "ALT EFF"

src = c.get("/api/sources").json()
assert "watching" in src["totals"]
assert "rejected_quality" in src["totals"]
assert any(s["kind"] == "rss_opportunity" for s in src["ingesting"])
assert any(s.get("acquisition") == "rejected" for s in src["not_ingesting"])
live = next(s for s in src["ingesting"] if s["kind"] == "official_call")
assert live["acquisition"] == "redirect"

print("api cards OK")
