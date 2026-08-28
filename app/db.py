"""SQLite storage. One table for items, one for source run history."""
import sqlite3, json, threading
from contextlib import contextmanager
from .config import DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id              TEXT PRIMARY KEY,      -- content hash, stable across runs
    kind            TEXT NOT NULL,         -- opportunity | festival | article
    category        TEXT NOT NULL,
    source          TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    link            TEXT NOT NULL,
    org             TEXT,
    location        TEXT,
    region_tier     TEXT,                  -- telugu | south | india | global
    employment_type TEXT,
    fee             TEXT,
    posted_at       TEXT,
    deadline        TEXT,
    trust           TEXT DEFAULT 'external',   -- external | flagged | verified
    trust_reasons   TEXT,                      -- JSON array
    raw             TEXT,                      -- JSON of source fields
    first_seen      TEXT DEFAULT (datetime('now')),
    last_seen       TEXT DEFAULT (datetime('now')),
    active          INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_items_cat  ON items(category, active);
CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind, active);
CREATE INDEX IF NOT EXISTS idx_items_src  ON items(source);
CREATE INDEX IF NOT EXISTS idx_items_seen ON items(last_seen);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    started_at  TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    status      TEXT,          -- ok | error | blocked | empty
    fetched     INTEGER DEFAULT 0,
    kept        INTEGER DEFAULT 0,
    new_items   INTEGER DEFAULT 0,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_src ON runs(source, started_at);

-- Listing URLs already fetched from a sitemap, so each run advances into
-- unseen ones instead of re-fetching the same head slice every time.
-- Recorded even when the page yielded nothing, or a dead URL is retried forever.
CREATE TABLE IF NOT EXISTS seen_urls (
    url     TEXT PRIMARY KEY,
    source  TEXT NOT NULL,
    seen_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_seen_src ON seen_urls(source);
"""


def get_conn():
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH, timeout=30)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=10000")
    return _local.conn


@contextmanager
def tx():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    with tx() as c:
        c.executescript(SCHEMA)


def upsert_items(items):
    """Insert new items, refresh last_seen on ones we've seen before.
    Returns (new_count, seen_count)."""
    new = seen = 0
    with tx() as c:
        for it in items:
            row = c.execute("SELECT id FROM items WHERE id=?", (it["id"],)).fetchone()
            if row:
                c.execute(
                    "UPDATE items SET last_seen=datetime('now'), active=1, "
                    "deadline=COALESCE(?,deadline) WHERE id=?",
                    (it.get("deadline"), it["id"]),
                )
                seen += 1
            else:
                c.execute(
                    """INSERT INTO items
                    (id,kind,category,source,title,description,link,org,location,
                     region_tier,employment_type,fee,posted_at,deadline,trust,trust_reasons,raw)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        it["id"], it["kind"], it["category"], it["source"],
                        it["title"], it.get("description"), it["link"],
                        it.get("org"), it.get("location"), it.get("region_tier"),
                        it.get("employment_type"), it.get("fee"),
                        it.get("posted_at"), it.get("deadline"),
                        it.get("trust", "external"),
                        json.dumps(it.get("trust_reasons", [])),
                        json.dumps(it.get("raw", {}))[:8000],
                    ),
                )
                new += 1
    return new, seen


def due_for_refresh(source_name, refresh_min):
    """False while a successful run for this source is newer than refresh_min.

    finished_at is written with SQLite's datetime('now'), i.e. UTC, so the
    comparison stays in one clock.
    """
    with tx() as c:
        row = c.execute(
            "SELECT finished_at FROM runs WHERE source=? AND status='ok' "
            "AND finished_at > datetime('now', ?) LIMIT 1",
            (source_name, f"-{int(refresh_min)} minutes")).fetchone()
    return row is None


def unseen_urls(source_id, urls, limit):
    """The first `limit` sitemap URLs this source hasn't fetched before."""
    with tx() as c:
        have = {r["url"] for r in
                c.execute("SELECT url FROM seen_urls WHERE source=?", (source_id,))}
    return [u for u in urls if u not in have][:limit]


def mark_urls_seen(source_id, urls):
    with tx() as c:
        c.executemany("INSERT OR IGNORE INTO seen_urls (url,source) VALUES (?,?)",
                      [(u, source_id) for u in urls])


def start_run(source):
    with tx() as c:
        cur = c.execute("INSERT INTO runs (source) VALUES (?)", (source,))
        return cur.lastrowid


def finish_run(run_id, status, fetched=0, kept=0, new_items=0, detail=""):
    with tx() as c:
        c.execute(
            "UPDATE runs SET finished_at=datetime('now'), status=?, fetched=?, "
            "kept=?, new_items=?, detail=? WHERE id=?",
            (status, fetched, kept, new_items, str(detail)[:500], run_id),
        )


def expire_stale(days=45):
    """Mark items we haven't re-seen in a while as inactive, and close out
    opportunities whose deadline has passed."""
    with tx() as c:
        c.execute(
            "UPDATE items SET active=0 WHERE active=1 "
            "AND last_seen < datetime('now', ?)",
            (f"-{days} days",),
        )
        c.execute(
            "UPDATE items SET active=0 WHERE active=1 AND deadline IS NOT NULL "
            "AND length(deadline)=10 AND deadline < date('now')"
        )


# --------------------------------------------------------------- read queries
def _row_to_item(r):
    d = dict(r)
    try:
        d["trust_reasons"] = json.loads(d.get("trust_reasons") or "[]")
    except Exception:
        d["trust_reasons"] = []
    d.pop("raw", None)
    return d


def _interleave(rows):
    """Round-robin by source so one prolific outlet can't own the top of the feed."""
    buckets = {}
    for r in rows:
        buckets.setdefault(r["source"], []).append(r)
    queues, out = list(buckets.values()), []
    moved = True
    while moved:
        moved = False
        for q in queues:
            if q:
                out.append(q.pop(0))
                moved = True
    return out


def query_items(category="all", limit=30, offset=0, tier=None,
                include_quarantine=False):
    # Quarantined listings are held back from the public feed by default.
    # They exist in the DB for a human to review, not for users to stumble into.
    where, params = ["active=1"], []
    if not include_quarantine:
        where.append("trust != 'quarantine'")

    if category == "telugu":
        where.append("kind='opportunity' AND region_tier IN ('telugu','south')")
    elif category and category != "all":
        where.append("category=?")
        params.append(category)

    if tier:
        where.append("region_tier=?")
        params.append(tier)

    clause = " AND ".join(where)
    with tx() as c:
        total = c.execute(f"SELECT COUNT(*) n FROM items WHERE {clause}",
                          params).fetchone()["n"]
        # Pull a wide slice, interleave, then page — keeps source mixing stable
        rows = c.execute(
            f"""SELECT * FROM items WHERE {clause}
                ORDER BY (deadline IS NOT NULL AND deadline!='') DESC,
                         COALESCE(NULLIF(posted_at,''), date(first_seen)) DESC
                LIMIT 400""", params).fetchall()

    mixed = _interleave([_row_to_item(r) for r in rows])
    return mixed[offset:offset + limit], total


def category_counts():
    with tx() as c:
        rows = c.execute(
            "SELECT category, COUNT(*) n FROM items WHERE active=1 GROUP BY category"
        ).fetchall()
        out = {r["category"]: r["n"] for r in rows}
        t = c.execute(
            "SELECT COUNT(*) n FROM items WHERE active=1 AND kind='opportunity' "
            "AND region_tier IN ('telugu','south')").fetchone()["n"]
    out["_telugu"] = t
    return out


def items_by_source(source):
    with tx() as c:
        return c.execute("SELECT COUNT(*) n FROM items WHERE active=1 AND source=?",
                         (source,)).fetchone()["n"]


def latest_runs():
    """Most recent run per source."""
    with tx() as c:
        rows = c.execute(
            """SELECT r.* FROM runs r
               JOIN (SELECT source, MAX(id) mid FROM runs GROUP BY source) m
                 ON r.id = m.mid""").fetchall()
    return {r["source"]: dict(r) for r in rows}


def stats():
    with tx() as c:
        total = c.execute("SELECT COUNT(*) n FROM items WHERE active=1").fetchone()["n"]
        by_kind = c.execute(
            "SELECT kind, COUNT(*) n FROM items WHERE active=1 GROUP BY kind"
        ).fetchall()
        quarantined = c.execute(
            "SELECT COUNT(*) n FROM items WHERE trust='quarantine'").fetchone()["n"]
    return {"active": total, "by_kind": {r["kind"]: r["n"] for r in by_kind},
            "quarantined": quarantined}
