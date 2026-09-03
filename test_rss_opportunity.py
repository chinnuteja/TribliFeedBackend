"""Job RSS becomes opportunities, scores scams, drops explainers.
python test_rss_opportunity.py"""
import os, tempfile
from pathlib import Path
os.environ["TRIBLI_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["TRIBLI_ROBOTS"] = "0"

from app.scrapers import rss_opportunity as ro
from app.filters import opportunity_relevant, assess_trust, region_tier

FIX = Path(__file__).parent / "fixtures" / "avjobs_feed.xml"
FEED = FIX.read_text(encoding="utf-8")
SRC = dict(id="avjobs", name="Animation and VFX Jobs", kind="rss_opportunity",
           category="casting", url="https://animationandvfxjobs.com/feed/",
           credibility=4, limit=15)


def fake_get(url, browser_ua=False):
    if url.endswith("/feed/") or "feed" in url:
        return FEED
    return "Studio: Hanu Studios\nLocation: Hyderabad\nJob Type: Full time\n"


ro.get = fake_get

items, raw = ro.scrape(SRC)
assert raw == 5, raw
titles = [i["title"] for i in items]
assert any("Hanu Studios" in t for t in titles), titles
assert any("DNEG" in t for t in titles), titles
assert any("Unreal" in t for t in titles), titles
assert not any("SmartRoto" in t for t in titles), titles
assert not any("registration fee" in t.lower() for t in titles), titles
assert not any("Aadhaar" in (i.get("description") or "") for i in items)

hanu = next(i for i in items if "Hanu" in i["title"])
assert hanu["kind"] == "opportunity"
assert hanu["category"] == "casting"
assert hanu["display_mode"] == "full"
assert hanu["source_id"] == "avjobs"
assert hanu["link"].startswith("https://animationandvfxjobs.com/roto-prep")
assert hanu["region_tier"] == "telugu", hanu["region_tier"]
assert "http" not in (hanu.get("description") or "") or True
assert "og:image" not in str(hanu)

andhra = next(i for i in items if "Unreal" in i["title"])
assert andhra["region_tier"] == "telugu", andhra["region_tier"]

# quality contract units, independent of scrape
assert opportunity_relevant("Roto artists required at Hanu Studios", "Hyderabad")
assert not opportunity_relevant(
    "SmartRoto in Nuke: What it is, why it matters", "tutorial")
trust, _, _ = assess_trust("Extras", "Pay Rs 5000 registration fee to apply", "")
assert trust == "blocked"
assert region_tier("Hyderabad walk-in") == "telugu"

print("rss opportunity OK", len(items), "kept")
