"""TRIBLI storage: SQLite locally, PostgreSQL/Supabase in production."""
import datetime, sqlite3, json, re, threading
from contextlib import contextmanager
from .config import DB_PATH, DATABASE_URL

try:  # psycopg is an optional local dependency; production installs it.
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised only when deployment is misconfigured
    psycopg = None
    dict_row = None

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
    trust           TEXT DEFAULT 'external',   -- external | caution | quarantine
    trust_reasons   TEXT,                      -- JSON array
    raw             TEXT,                      -- JSON of source fields
    source_id       TEXT,                      -- registry id; empty on pre-migration rows
    publisher       TEXT,                      -- display attribution
    source_url      TEXT,                      -- publisher home / feed, not the item link
    display_mode    TEXT DEFAULT 'full',       -- full | redirect
    verified_at     TEXT,                      -- ISO date the permalink was last confirmed
    acquisition_mode TEXT DEFAULT 'scraped',   -- scraped | shared
    apply_method    TEXT,                      -- web | whatsapp | phone | email
    apply_url       TEXT,
    expires_at      TEXT,                      -- operational expiry, not a publisher deadline
    submitted_at    TEXT,
    source_domain   TEXT,
    extract_confidence REAL,
    extract_evidence TEXT,                     -- JSON; never returned by the API
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

CREATE TABLE IF NOT EXISTS submissions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_hash    TEXT NOT NULL,
    status          TEXT NOT NULL,
    sanitized_text  TEXT,
    model           TEXT,
    reasons         TEXT,
    item_id         TEXT,
    submitted_by    TEXT,
    transport       TEXT,
    payload_shape   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sub_hash ON submissions(payload_hash);
CREATE INDEX IF NOT EXISTS idx_sub_status ON submissions(status, created_at);

CREATE TABLE IF NOT EXISTS share_devices (
    token_hash  TEXT PRIMARY KEY,
    label       TEXT,
    enabled     INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now')),
    last_used   TEXT
);

CREATE TABLE IF NOT EXISTS shared_domains (
    domain      TEXT PRIMARY KEY,
    hits        INTEGER DEFAULT 0,
    last_format TEXT,
    last_status TEXT,
    last_seen   TEXT DEFAULT (datetime('now'))
);
"""

# Supabase is used only as a managed Postgres host. Tables live in a private
# schema, not `public`, so the Data API cannot expose feed or device records.
SCHEMA_POSTGRES = """
CREATE SCHEMA IF NOT EXISTS tribli;
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL, category TEXT NOT NULL, source TEXT NOT NULL,
    title TEXT NOT NULL, description TEXT, link TEXT NOT NULL, org TEXT,
    location TEXT, region_tier TEXT, employment_type TEXT, fee TEXT,
    posted_at TEXT, deadline TEXT, trust TEXT DEFAULT 'external',
    trust_reasons TEXT, raw TEXT, source_id TEXT, publisher TEXT,
    source_url TEXT, display_mode TEXT DEFAULT 'full', verified_at TEXT,
    acquisition_mode TEXT DEFAULT 'scraped', apply_method TEXT, apply_url TEXT,
    expires_at TEXT, submitted_at TEXT, source_domain TEXT,
    extract_confidence DOUBLE PRECISION, extract_evidence TEXT,
    first_seen TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, active SMALLINT DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_items_cat ON items(category, active);
CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind, active);
CREATE INDEX IF NOT EXISTS idx_items_src ON items(source);
CREATE INDEX IF NOT EXISTS idx_items_seen ON items(last_seen);
CREATE TABLE IF NOT EXISTS runs (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL, started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ, status TEXT, fetched INTEGER DEFAULT 0,
    kept INTEGER DEFAULT 0, new_items INTEGER DEFAULT 0, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_src ON runs(source, started_at);
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY, source TEXT NOT NULL,
    seen_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_seen_src ON seen_urls(source);
CREATE TABLE IF NOT EXISTS submissions (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    payload_hash TEXT NOT NULL, status TEXT NOT NULL, sanitized_text TEXT,
    model TEXT, reasons TEXT, item_id TEXT, submitted_by TEXT, transport TEXT,
    payload_shape TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sub_hash ON submissions(payload_hash);
CREATE INDEX IF NOT EXISTS idx_sub_status ON submissions(status, created_at);
CREATE TABLE IF NOT EXISTS share_devices (
    token_hash TEXT PRIMARY KEY, label TEXT, enabled SMALLINT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, last_used TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS shared_domains (
    domain TEXT PRIMARY KEY, hits INTEGER DEFAULT 0, last_format TEXT,
    last_status TEXT, last_seen TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE seen_urls ENABLE ROW LEVEL SECURITY;
ALTER TABLE submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE share_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE shared_domains ENABLE ROW LEVEL SECURITY;
"""


def using_postgres():
    """True only when an operator explicitly supplies a server-side URL."""
    return bool(DATABASE_URL)


def _pg_sql(sql):
    """Translate the small SQLite dialect used by the repository to Postgres."""
    sql = sql.replace("datetime('now', ?)", "CURRENT_TIMESTAMP + %s::interval")
    sql = sql.replace("datetime('now', '-14 days')",
                      "CURRENT_TIMESTAMP - INTERVAL '14 days'")
    sql = sql.replace("datetime('now')", "CURRENT_TIMESTAMP")
    sql = sql.replace("date('now')", "CURRENT_DATE::text")
    sql = sql.replace("date(first_seen)",
                      "((first_seen AT TIME ZONE 'UTC')::date)::text")
    return sql.replace("?", "%s")


class _PostgresConnection:
    """Keeps repository calls portable without leaking SQL dialect upstream."""
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=None):
        return self.raw.execute(_pg_sql(sql), params or ())

    def executemany(self, sql, params_seq):
        return self.raw.executemany(_pg_sql(sql), params_seq)

    def __getattr__(self, name):
        return getattr(self.raw, name)


def get_conn():
    if not hasattr(_local, "conn"):
        if using_postgres():
            if psycopg is None:
                raise RuntimeError("TRIBLI_DATABASE_URL needs psycopg; install requirements.txt")
            raw = psycopg.connect(DATABASE_URL, row_factory=dict_row)
            # `tribli` is private; `public` stays available for Postgres internals.
            raw.execute("SET search_path TO tribli, public")
            _local.conn = _PostgresConnection(raw)
        else:
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


_NEW_COLUMNS = (
    ("source_id", "TEXT"),
    ("publisher", "TEXT"),
    ("source_url", "TEXT"),
    ("display_mode", "TEXT DEFAULT 'full'"),
    ("verified_at", "TEXT"),
    ("acquisition_mode", "TEXT DEFAULT 'scraped'"),
    ("apply_method", "TEXT"),
    ("apply_url", "TEXT"),
    ("expires_at", "TEXT"),
    ("submitted_at", "TEXT"),
    ("source_domain", "TEXT"),
    ("extract_confidence", "REAL"),
    ("extract_evidence", "TEXT"),
)


def _migrate(conn):
    """Add provenance columns to databases created before this schema."""
    if using_postgres():
        return
    have = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    for name, decl in _NEW_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE items ADD COLUMN {name} {decl}")
    conn.execute(
        "UPDATE items SET display_mode='full' "
        "WHERE display_mode IS NULL OR display_mode=''")
    conn.execute(
        "UPDATE items SET publisher=source "
        "WHERE publisher IS NULL OR publisher=''")
    conn.execute(
        "UPDATE items SET acquisition_mode='scraped' "
        "WHERE acquisition_mode IS NULL OR acquisition_mode=''")
    # Older Dazzlerr rows may contain unpadded D-M-YYYY values. SQLite and
    # browsers do not interpret those consistently, and the expiry query only
    # accepts canonical ISO dates. Repair them in place before expiry runs.
    rows = conn.execute(
        "SELECT id, deadline FROM items WHERE source='Dazzlerr' "
        "AND deadline IS NOT NULL AND deadline!='' "
        "AND deadline NOT GLOB '????-??-??'"
    ).fetchall()
    day_first = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")
    for row in rows:
        match = day_first.fullmatch(row["deadline"] or "")
        if not match:
            continue
        try:
            normalized = datetime.date(
                int(match.group(3)), int(match.group(2)), int(match.group(1))
            ).isoformat()
        except ValueError:
            continue
        conn.execute("UPDATE items SET deadline=? WHERE id=?",
                     (normalized, row["id"]))


def init_db():
    with tx() as c:
        if using_postgres():
            for statement in SCHEMA_POSTGRES.split(";"):
                if statement.strip():
                    c.execute(statement)
        else:
            c.executescript(SCHEMA)
            _migrate(c)


def _festival_duplicate(conn, it):
    """Same festival arriving from API and editorial RSS collapses to one row."""
    if it.get("kind") != "festival":
        return None
    from .filters import festival_stem
    stem = festival_stem(it.get("title"))
    if not stem:
        return None
    rows = conn.execute(
        "SELECT id, title, deadline, display_mode, fee, link, source "
        "FROM items WHERE kind='festival' AND active=1"
    ).fetchall()
    incoming_dl = (it.get("deadline") or "")[:10]
    for r in rows:
        if festival_stem(r["title"]) != stem:
            continue
        their_dl = (r["deadline"] or "")[:10]
        if their_dl and incoming_dl and their_dl != incoming_dl:
            continue
        return r
    return None


def upsert_items(items):
    """Insert new items, refresh mutable facts on ones we've seen before.
    Returns (new_count, seen_count)."""
    new = seen = 0
    with tx() as c:
        for it in items:
            row = c.execute(
                "SELECT id, display_mode FROM items WHERE id=?", (it["id"],)
            ).fetchone()
            if row is None:
                dup = _festival_duplicate(c, it)
                if dup is not None:
                    row = dup
                    it = {**it, "id": dup["id"]}
            if row:
                existing_mode = (row["display_mode"] if "display_mode" in row.keys()
                                 else None) or "full"
                incoming_mode = it.get("display_mode") or "full"
                # A redirect must not overwrite a richer full ingest of the
                # same festival / listing.
                if existing_mode == "full" and incoming_mode == "redirect":
                    c.execute(
                        "UPDATE items SET last_seen=datetime('now'), active=1 WHERE id=?",
                        (row["id"],),
                    )
                else:
                    c.execute(
                        """UPDATE items SET last_seen=datetime('now'), active=1,
                           title=?, description=?, link=?, org=?, location=?,
                           region_tier=?, employment_type=?, fee=?, posted_at=?,
                           deadline=?, trust=?, trust_reasons=?,
                           source_id=COALESCE(NULLIF(?,''), source_id),
                           publisher=COALESCE(NULLIF(?,''), publisher),
                           source_url=COALESCE(NULLIF(?,''), source_url),
                           display_mode=?,
                           verified_at=COALESCE(NULLIF(?,''), verified_at),
                           acquisition_mode=COALESCE(NULLIF(?,''), acquisition_mode),
                           apply_method=COALESCE(NULLIF(?,''), apply_method),
                           apply_url=COALESCE(NULLIF(?,''), apply_url),
                           expires_at=COALESCE(NULLIF(?,''), expires_at),
                           submitted_at=COALESCE(NULLIF(?,''), submitted_at),
                           source_domain=COALESCE(NULLIF(?,''), source_domain),
                           extract_confidence=COALESCE(?, extract_confidence)
                           WHERE id=?""",
                        (
                            it["title"], it.get("description"), it["link"],
                            it.get("org"), it.get("location"), it.get("region_tier"),
                            it.get("employment_type"), it.get("fee"),
                            it.get("posted_at"), it.get("deadline"),
                            it.get("trust", "external"),
                            json.dumps(it.get("trust_reasons", [])),
                            it.get("source_id") or "",
                            it.get("publisher") or "",
                            it.get("source_url") or "",
                            incoming_mode,
                            it.get("verified_at") or "",
                            it.get("acquisition_mode") or "",
                            it.get("apply_method") or "",
                            it.get("apply_url") or "",
                            it.get("expires_at") or "",
                            it.get("submitted_at") or "",
                            it.get("source_domain") or "",
                            it.get("extract_confidence"),
                            row["id"],
                        ),
                    )
                seen += 1
            else:
                c.execute(
                    """INSERT INTO items
                    (id,kind,category,source,title,description,link,org,location,
                     region_tier,employment_type,fee,posted_at,deadline,trust,
                     trust_reasons,raw,source_id,publisher,source_url,display_mode,
                     verified_at,acquisition_mode,apply_method,apply_url,expires_at,
                     submitted_at,source_domain,extract_confidence,extract_evidence)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        it["id"], it["kind"], it["category"], it["source"],
                        it["title"], it.get("description"), it["link"],
                        it.get("org"), it.get("location"), it.get("region_tier"),
                        it.get("employment_type"), it.get("fee"),
                        it.get("posted_at"), it.get("deadline"),
                        it.get("trust", "external"),
                        json.dumps(it.get("trust_reasons", [])),
                        json.dumps(it.get("raw", {}))[:8000],
                        it.get("source_id") or "",
                        it.get("publisher") or it.get("source") or "",
                        it.get("source_url") or "",
                        it.get("display_mode") or "full",
                        it.get("verified_at") or "",
                        it.get("acquisition_mode") or "scraped",
                        it.get("apply_method") or "",
                        it.get("apply_url") or "",
                        it.get("expires_at") or "",
                        it.get("submitted_at") or "",
                        it.get("source_domain") or "",
                        it.get("extract_confidence") or 0,
                        json.dumps(it.get("extract_evidence") or {})[:4000],
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
        if using_postgres():
            c.executemany(
                "INSERT INTO seen_urls (url,source) VALUES (?,?) "
                "ON CONFLICT(url) DO NOTHING",
                [(u, source_id) for u in urls],
            )
        else:
            c.executemany("INSERT OR IGNORE INTO seen_urls (url,source) VALUES (?,?)",
                          [(u, source_id) for u in urls])


def start_run(source):
    with tx() as c:
        if using_postgres():
            return c.execute("INSERT INTO runs (source) VALUES (?) RETURNING id",
                             (source,)).fetchone()["id"]
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
        c.execute(
            "UPDATE items SET active=0 WHERE active=1 AND expires_at IS NOT NULL "
            "AND length(expires_at)>=10 AND expires_at < date('now')"
        )


# --------------------------------------------------------------- read queries
def _row_to_item(r):
    d = dict(r)
    try:
        d["trust_reasons"] = json.loads(d.get("trust_reasons") or "[]")
    except Exception:
        d["trust_reasons"] = []
    d.pop("raw", None)
    d.pop("extract_evidence", None)
    d.pop("submitted_by", None)
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
    where.append("(expires_at IS NULL OR expires_at='' OR expires_at >= date('now'))")

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
        # Interleave after fetch so one board cannot own the page. Cap is a
        # safety bound, not a silent pagination cliff: 400 used to disagree
        # with `total` once the table grew past the prefetch.
        rows = c.execute(
            f"""SELECT * FROM items WHERE {clause}
                ORDER BY (deadline IS NOT NULL AND deadline!='') DESC,
                         COALESCE(NULLIF(posted_at,''), date(first_seen)) DESC
                LIMIT 5000""", params).fetchall()

    mixed = _interleave([_row_to_item(r) for r in rows])
    return mixed[offset:offset + limit], total


def category_counts():
    with tx() as c:
        rows = c.execute(
            "SELECT category, COUNT(*) n FROM items WHERE active=1 "
            "AND trust != 'quarantine' "
            "AND (expires_at IS NULL OR expires_at='' OR expires_at >= date('now')) "
            "GROUP BY category"
        ).fetchall()
        out = {r["category"]: r["n"] for r in rows}
        t = c.execute(
            "SELECT COUNT(*) n FROM items WHERE active=1 AND trust != 'quarantine' "
            "AND (expires_at IS NULL OR expires_at='' OR expires_at >= date('now')) "
            "AND kind='opportunity' AND region_tier IN ('telugu','south')"
        ).fetchone()["n"]
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


def find_share_duplicate(link="", apply_url="", title=""):
    """Same shared/scraped listing: exact URL/contact plus a close title stem."""
    from .filters import _NORM
    stem = _NORM.sub(" ", (title or "").lower()).strip()[:70]
    with tx() as c:
        if link:
            row = c.execute(
                "SELECT * FROM items WHERE active=1 AND (link=? OR apply_url=?)",
                (link, link),
            ).fetchone()
            if row:
                return _row_to_item(row)
        if apply_url:
            rows = c.execute(
                "SELECT * FROM items WHERE active=1 AND (apply_url=? OR link=?)",
                (apply_url, apply_url),
            ).fetchall()
            for r in rows:
                other = _NORM.sub(" ", (r["title"] or "").lower()).strip()[:70]
                if not stem or other == stem:
                    return _row_to_item(r)
        if stem:
            rows = c.execute(
                "SELECT * FROM items WHERE active=1 AND acquisition_mode='shared' "
                "AND last_seen > datetime('now', '-14 days')"
            ).fetchall()
            for r in rows:
                other = _NORM.sub(" ", (r["title"] or "").lower()).strip()[:70]
                if other == stem and (
                    (apply_url and (r["apply_url"] == apply_url or r["link"] == apply_url))
                    or (link and (r["link"] == link or r["apply_url"] == link))
                ):
                    return _row_to_item(r)
    return None


def record_submission(payload_hash, status, sanitized_text="", model="",
                      reasons=None, item_id="", submitted_by="", transport="",
                      payload_shape=None):
    with tx() as c:
        c.execute(
            """INSERT INTO submissions
               (payload_hash, status, sanitized_text, model, reasons, item_id,
                submitted_by, transport, payload_shape)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (payload_hash, status, (sanitized_text or "")[:2000], model or "",
             json.dumps(reasons or []), item_id or "", submitted_by or "",
             transport or "", json.dumps(payload_shape or {})),
        )


def share_stats():
    with tx() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) n FROM submissions GROUP BY status"
        ).fetchall()
    out = {r["status"]: r["n"] for r in rows}
    out["published"] = out.get("published", 0)
    out["duplicate"] = out.get("duplicate", 0)
    out["quarantined"] = out.get("quarantined", 0)
    out["rejected"] = out.get("rejected", 0)
    out["extraction_error"] = out.get("extraction_error", 0)
    out["needs_details"] = out.get("needs_details", 0)
    return out


def record_shared_domain(domain, fmt="", status=""):
    if not domain:
        return
    with tx() as c:
        c.execute(
            """INSERT INTO shared_domains (domain, hits, last_format, last_status)
               VALUES (?, 1, ?, ?)
               ON CONFLICT(domain) DO UPDATE SET
                 hits = hits + 1,
                 last_format = excluded.last_format,
                 last_status = excluded.last_status,
                 last_seen = datetime('now')""",
            (domain, fmt or "", status or ""),
        )


def put_share_device(token_hash, label=""):
    with tx() as c:
        if using_postgres():
            c.execute(
                "INSERT INTO share_devices (token_hash, label) VALUES (?,?) "
                "ON CONFLICT(token_hash) DO NOTHING",
                (token_hash, label or ""),
            )
        else:
            c.execute(
                "INSERT OR IGNORE INTO share_devices (token_hash, label) VALUES (?,?)",
                (token_hash, label or ""),
            )


def share_device_ok(token_hash):
    with tx() as c:
        row = c.execute(
            "SELECT enabled FROM share_devices WHERE token_hash=?", (token_hash,)
        ).fetchone()
        if not row or not row["enabled"]:
            return False
        c.execute("UPDATE share_devices SET last_used=datetime('now') WHERE token_hash=?",
                  (token_hash,))
        return True


def disable_share_device(token_hash):
    with tx() as c:
        c.execute("UPDATE share_devices SET enabled=0 WHERE token_hash=?", (token_hash,))
