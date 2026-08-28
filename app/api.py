"""
Read API. The frontend talks only to this — never to a source directly.
That's the whole point of having a backend: CORS blocks browsers from most of
these feeds, and we want filtering, dedupe and trust scoring applied server-side.
"""
import datetime
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from . import db
from .sources import SOURCES, NOT_INGESTING, CATEGORIES

app = FastAPI(title="TRIBLI Feed API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

# Categories that are views over other categories rather than their own sources
VIRTUAL = {"telugu"}


@app.on_event("startup")
def _startup():
    db.init_db()


def _rows_to_items(rows):
    out = []
    for r in rows:
        d = dict(r)
        d["trust_reasons"] = d.get("trust_reasons") or "[]"
        out.append(d)
    return out


@app.get("/api/feed")
def feed(category: str = Query("all"),
         limit: int = Query(30, ge=1, le=100),
         offset: int = Query(0, ge=0),
         tier: str = Query(None)):
    """Paginated feed. Sources are interleaved so no single outlet dominates."""
    items, total = db.query_items(category=category, limit=limit,
                                  offset=offset, tier=tier)
    return {"items": items, "total": total, "limit": limit, "offset": offset,
            "category": category}


@app.get("/api/categories")
def categories():
    counts = db.category_counts()
    out = []
    for c in CATEGORIES:
        live_sources = [s for s in SOURCES if s["category"] == c["id"]]
        out.append({**c,
                    "count": counts.get(c["id"], 0),
                    "live_sources": len(live_sources),
                    "virtual": c["id"] in VIRTUAL})
    # telugu is a filtered view over opportunities
    out_map = {c["id"]: c for c in out}
    if "telugu" in out_map:
        out_map["telugu"]["count"] = counts.get("_telugu", 0)
    return {"categories": out, "total_items": sum(counts.get(c["id"], 0)
                                                  for c in CATEGORIES)}


@app.get("/api/sources")
def sources():
    """Full source intelligence: what's feeding, what isn't, and exactly why."""
    health = db.latest_runs()
    live = []
    for s in SOURCES:
        h = health.get(s["name"], {})
        live.append({
            "name": s["name"], "category": s["category"], "kind": s["kind"],
            "credibility": s.get("credibility", 3),
            "note": s.get("note", ""),
            "status": h.get("status", "pending"),
            "items": db.items_by_source(s["name"]),
            "fetched": h.get("fetched", 0),
            "kept": h.get("kept", 0),
            "last_run": h.get("finished_at"),
            "detail": h.get("detail", ""),
        })
    return {
        "ingesting": live,
        "not_ingesting": NOT_INGESTING,
        "totals": {
            "mapped": len(SOURCES) + len(NOT_INGESTING),
            "configured": len(SOURCES),
            "feeding": sum(1 for s in live if s["status"] == "ok"),
            "blocked": sum(1 for s in live if s["status"] in ("blocked", "error")),
            "empty": sum(1 for s in live if s["status"] == "empty"),
        },
    }


@app.get("/api/health")
def health():
    runs = db.latest_runs()
    stats = db.stats()
    return {"ok": True, "generated_at": datetime.datetime.utcnow().isoformat(),
            "items": stats, "sources": len(runs),
            "healthy": sum(1 for r in runs.values() if r.get("status") == "ok")}


@app.post("/api/ingest")
def ingest(source: str = Query(None)):
    """Trigger a run on demand. The scheduler calls the same code path."""
    from .pipeline import run_all
    results = run_all(only=[source] if source else None, verbose=False)
    return {"ran": len(results), "results": results}


@app.get("/")
def index():
    f = FRONTEND / "index.html"
    return FileResponse(f) if f.exists() else {"error": "frontend not built"}


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
