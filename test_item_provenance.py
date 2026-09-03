"""Provenance columns migrate, upsert refreshes facts, pagination past 400 works.
python test_item_provenance.py"""
import os, sqlite3, tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
old_db = str(Path(tmp) / "old.db")
os.environ["TRIBLI_DB"] = old_db

# Build a pre-migration database by hand.
conn = sqlite3.connect(old_db)
conn.executescript("""
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    category TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    link TEXT NOT NULL,
    org TEXT, location TEXT, region_tier TEXT,
    employment_type TEXT, fee TEXT, posted_at TEXT, deadline TEXT,
    trust TEXT DEFAULT 'external',
    trust_reasons TEXT, raw TEXT,
    first_seen TEXT DEFAULT (datetime('now')),
    last_seen TEXT DEFAULT (datetime('now')),
    active INTEGER DEFAULT 1
);
INSERT INTO items (id,kind,category,source,title,link,trust)
VALUES ('legacy1','article','tech','CineD','Old cam','https://cined.com/a','external');
""")
conn.commit()
conn.close()

from app import db
db.init_db()
db.init_db()  # second migrate must be idempotent

with db.tx() as c:
    cols = {r[1] for r in c.execute("PRAGMA table_info(items)")}
    for need in ("source_id", "publisher", "source_url", "display_mode", "verified_at"):
        assert need in cols, cols
    row = c.execute("SELECT display_mode, publisher FROM items WHERE id='legacy1'").fetchone()
    assert row["display_mode"] == "full", row["display_mode"]
    assert row["publisher"] == "CineD", row["publisher"]

# refresh mutable fields on re-ingest
item = dict(id="legacy1", kind="article", category="tech", source="CineD",
            title="New cam title", description="updated", link="https://cined.com/b",
            source_id="cined", publisher="CineD", source_url="https://www.cined.com/feed/",
            display_mode="full", trust="external", trust_reasons=[])
new, seen = db.upsert_items([item])
assert new == 0 and seen == 1
got, total = db.query_items(category="tech", limit=10)
assert total >= 1
hit = next(i for i in got if i["id"] == "legacy1")
assert hit["title"] == "New cam title"
assert hit["link"] == "https://cined.com/b"
assert hit["display_mode"] == "full"

# redirect must not clobber a full row
db.upsert_items([dict(item, display_mode="redirect", title="should not win")])
got, _ = db.query_items(category="tech", limit=10)
hit = next(i for i in got if i["id"] == "legacy1")
assert hit["title"] == "New cam title"
assert hit["display_mode"] == "full"

# quarantine stays out of the public feed
q = dict(id="q1", kind="opportunity", category="casting", source="X",
         title="Risky", link="https://x.example/job/1", trust="quarantine",
         display_mode="full")
db.upsert_items([q])
pub, n = db.query_items(category="casting", limit=50)
assert all(i["id"] != "q1" for i in pub)
held, n2 = db.query_items(category="casting", limit=50, include_quarantine=True)
assert any(i["id"] == "q1" for i in held)

# pagination: more than 400 rows still reachable
bulk = [dict(id=f"p{i}", kind="article", category="ai", source=f"S{i % 3}",
             title=f"Post {i:04d} about craft", link=f"https://ex.example/p/{i}",
             display_mode="full", posted_at="2026-08-01")
        for i in range(450)]
db.upsert_items(bulk)
page0, total = db.query_items(category="ai", limit=30, offset=0)
page13, total2 = db.query_items(category="ai", limit=30, offset=420)
assert total == total2 == 450, (total, total2)
assert len(page0) == 30
assert len(page13) == 30, len(page13)
assert {i["id"] for i in page0}.isdisjoint({i["id"] for i in page13})

# festival API + editorial RSS collapse
db.upsert_items([
    dict(id="rss-iffk", kind="festival", category="festivals",
         source="Asian Film Festivals", title="31st IFFK",
         link="https://asianfilmfestivals.com/iffk", deadline="2026-09-10",
         display_mode="full", fee=""),
    dict(id="api-iffk", kind="festival", category="festivals",
         source="Festival API", title="31st IFFK",
         link="https://filmfreeway.com/IFFK", deadline="2026-09-10",
         display_mode="full", fee="$0 entry"),
])
fests, ft = db.query_items(category="festivals", limit=20)
iffks = [i for i in fests if "IFFK" in i["title"]]
assert len(iffks) == 1, [i["id"] for i in iffks]
assert iffks[0]["fee"] == "$0 entry" or iffks[0]["link"].startswith("https://filmfreeway")

print("item provenance OK")
