"""Only call-for-entry posts become festivals.
python test_festival_rss.py"""
import os, tempfile
from pathlib import Path
os.environ["TRIBLI_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["TRIBLI_ROBOTS"] = "0"

from app.scrapers import rss_festival as rf
from app.filters import call_for_entry

FIX = Path(__file__).parent / "fixtures" / "asianff_feed.xml"
SRC = dict(id="asianfilmfestivals", name="Asian Film Festivals",
           kind="rss_festival", category="festivals",
           url="https://asianfilmfestivals.com/feed/", credibility=4)


def fake_get(url, browser_ua=False):
    return FIX.read_text(encoding="utf-8")


rf.get = fake_get
items, raw = rf.scrape(SRC)
assert raw == 3, raw
titles = [i["title"] for i in items]
assert any("Kerala" in t and "Call for Entry" in t for t in titles), titles
assert not any("Opening Film" in t for t in titles), titles
iffk = next(i for i in items if "Kerala" in i["title"] and "Documentary" not in i["title"])
assert iffk["kind"] == "festival"
assert iffk["deadline"] == "2026-09-10", iffk["deadline"]
assert iffk["fee"].lower().startswith("free"), iffk["fee"]
assert iffk["link"].startswith("https://www.iffk.in/")
assert "filmfreeway.com" not in iffk["link"]  # editorial permalink or official site
assert call_for_entry("IFFK – Call for Entry 2026", "accepting feature films")
assert not call_for_entry("Aichi – Opening Film 2026",
                          "Victoria will open the festival. Screening dates.")
print("festival rss OK", len(items), "kept")
