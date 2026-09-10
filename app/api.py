"""
Read API. The frontend talks only to this — never to a source directly.
That's the whole point of having a backend: CORS blocks browsers from most of
these feeds, and we want filtering, dedupe and trust scoring applied server-side.
"""
import datetime
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from . import db
from .sources import SOURCES, NOT_INGESTING, CATEGORIES
from .config import share_enabled, share_max_bytes, share_secret
from .share_auth import (
    COOKIE, authenticate_share, authenticate_operator, claim_secret_ok,
    issue_device_token, rate_ok,
)
from .share_ingest import ALLOWED_IMAGE, process_share

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
            "acquisition": ("redirect" if s["kind"] == "official_call" else "full"),
            "status": h.get("status", "pending"),
            "items": db.items_by_source(s["name"]),
            "fetched": h.get("fetched", 0),
            "kept": h.get("kept", 0),
            "last_run": h.get("finished_at"),
            "detail": h.get("detail", ""),
            # A cadence skip is only emitted when a recent successful run
            # exists, so the source is still feeding even though it was not
            # fetched again during this sweep.
            "feeding": h.get("status") in ("ok", "skipped"),
        })
    dead = []
    for s in NOT_INGESTING:
        dead.append({
            **s,
            "acquisition": s.get("acquisition") or (
                "rejected" if s.get("status") == "rejected" else
                "watch" if s.get("status") in ("untested", "nofeed") else
                s.get("status") or "watch"),
        })
    return {
        "ingesting": live,
        "not_ingesting": dead,
        "totals": {
            "mapped": len(SOURCES) + len(NOT_INGESTING),
            "configured": len(SOURCES),
            "feeding": sum(1 for s in live if s["feeding"]),
            "blocked": sum(1 for s in live if s["status"] in ("blocked", "error")),
            "empty": sum(1 for s in live if s["status"] == "empty"),
            "watching": sum(1 for s in dead if s.get("acquisition") == "watch"),
            "rejected_quality": sum(1 for s in dead if s.get("acquisition") == "rejected"),
        },
    }


@app.get("/api/health")
def health():
    runs = db.latest_runs()
    stats = db.stats()
    return {"ok": True, "generated_at": datetime.datetime.utcnow().isoformat(),
            "items": stats, "sources": len(runs),
            "healthy": sum(1 for r in runs.values()
                           if r.get("status") in ("ok", "skipped")),
            "share": db.share_stats()}


@app.post("/api/ingest")
async def ingest(request: Request, source: str = Query(None)):
    """Trigger a run on demand. The scheduler calls the same code path."""
    if not authenticate_operator(request):
        return JSONResponse({"error": "ingest requires operator secret"}, status_code=401)
    from .pipeline import run_all
    results = run_all(only=[source] if source else None, verbose=False)
    return {"ran": len(results), "results": results}


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


async def _form_payload(request: Request):
    text = url = title = ""
    data, mime = None, ""
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            body = await request.json()
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="malformed JSON payload")
        text = str((body or {}).get("text") or "")
        url = str((body or {}).get("url") or "")
        title = str((body or {}).get("title") or "")
        return text, url, title, data, mime
    form = await request.form()
    text = str(form.get("text") or "")
    url = str(form.get("url") or "")
    title = str(form.get("title") or "")
    image = form.get("image")
    filename = getattr(image, "filename", None)
    if image is not None and filename:
        reader = getattr(image, "read", None)
        if reader is not None:
            data = await image.read()
            mime = (getattr(image, "content_type", None) or "").split(";")[0].strip().lower()
    return text, url, title, data, mime


def _share_error(status: int, detail: str, html: bool):
    if html:
        return HTMLResponse(_result_html("Not published", [detail], setup=status in (401, 403)),
                            status_code=status)
    return JSONResponse({"error": detail, "status": "rejected"}, status_code=status)


def _result_html(headline: str, reasons: list, setup: bool = False, item_id: str = ""):
    why = "".join(f"<li>{_esc(r)}</li>" for r in reasons) or "<li>No extra detail.</li>"
    setup_line = ('<p class="status bad"><a href="/share/setup">Connect this device</a> once, then sharing is two taps.</p>'
                  if setup else "")
    published = headline.lower().startswith("published")
    saved = headline.lower().startswith("saved")
    mark_bg = "#E7F7F0" if published else "#FFF1D6" if saved else "#F7DFDF"
    mark_color = "#156A4B" if published else "#8A5A00" if saved else "#941E1E"
    intro = (
        "Your post is now available to the TRIBLI team."
        if published else
        "This post is in the team feed and needs contact details before anyone applies."
        if saved else
        "TRIBLI kept this out of the feed."
    )
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#FFFFFF"><link rel="manifest" href="/manifest.webmanifest">
<title>TRIBLI share — {_esc(headline)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Open+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/share.css">
<style>.result-mark{{width:52px;height:52px;border-radius:50%;display:grid;place-items:center;margin-bottom:18px;background:{mark_bg};color:{mark_color};font-size:24px;font-weight:750}}.result-list{{margin:0;padding-left:19px;color:#666;font:13px/1.55 'Open Sans',sans-serif}}.result-list li+li{{margin-top:6px}}.item-id{{color:#999;font:11px/1.4 ui-monospace,monospace;overflow-wrap:anywhere;margin-top:14px}}</style>
</head><body><div class="share-shell"><header class="share-header"><a class="icon-button" href="/" aria-label="Back to feed"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m15 18-6-6 6-6" stroke-linecap="round" stroke-linejoin="round"/></svg></a><a class="brand" href="/" aria-label="TRIBLI home"><span class="brand-glyph"></span><span>TRIBLI</span></a><span></span></header><main class="share-main">
<p class="eyebrow">Team intake</p><div class="panel"><div class="result-mark">{'✓' if published or saved else '!'}</div><h1>{_esc(headline)}</h1>
<p class="intro">{intro}</p>
<ul class="result-list">{why}</ul>{setup_line}<p class="item-id">{_esc(item_id)}</p>
</div><div class="cta-frame"><button class="primary-button" type="button" onclick="location.href='/'">Open team feed</button></div>
<nav class="link-row" aria-label="Share result"><a href="/share">Share another</a><span>·</span><a href="/share/setup">Device setup</a></nav>
</main></div></body></html>"""


async def _handle_share(request: Request, html: bool):
    if not share_enabled() or not share_secret():
        return _share_error(503, "share intake is disabled", html)
    device = authenticate_share(request)
    if not device:
        return _share_error(401, "device not set up", html)
    ip = request.client.host if request.client else "0"
    if not rate_ok(device, ip):
        return _share_error(429, "too many shares from this device", html)
    text, url, title, data, mime = await _form_payload(request)
    max_b = share_max_bytes()
    if data and len(data) > max_b:
        return _share_error(413, "image too large", html)
    if data and mime not in ALLOWED_IMAGE:
        return _share_error(415, "image type not allowed", html)
    result = process_share(
        text=text or "", url=url or "", title=title or "",
        image_bytes=data, image_mime=mime,
        submitted_by=device, transport="pwa" if html else "api",
        user_agent=request.headers.get("user-agent", ""),
    )
    if html:
        if result["status"] in ("published", "duplicate"):
            head = "Published"
        elif result["status"] == "needs_details":
            head = "Saved for team review"
        else:
            head = "Not published"
        return HTMLResponse(_result_html(head, result.get("reasons") or [],
                                         item_id=result.get("id") or ""))
    return JSONResponse(result)


@app.post("/api/share/claim")
async def share_claim(request: Request):
    if not share_enabled() or not share_secret():
        return JSONResponse({"error": "share intake is disabled"}, status_code=503)
    secret = ""
    try:
        body = await request.json()
        secret = str((body or {}).get("secret") or "")
    except Exception:
        secret = ""
    if not claim_secret_ok(secret):
        return JSONResponse({"error": "bad secret"}, status_code=401)
    token = issue_device_token(label="claimed")
    resp = JSONResponse({"token": token, "cookie": COOKIE})
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax",
                    max_age=366 * 24 * 3600, path="/")
    return resp


@app.post("/api/share")
async def api_share(request: Request):
    return await _handle_share(request, html=False)


@app.post("/share")
async def pwa_share(request: Request):
    return await _handle_share(request, html=True)


@app.get("/share")
def share_page():
    f = FRONTEND / "share.html"
    return FileResponse(f) if f.exists() else JSONResponse({"error": "missing"}, status_code=404)


@app.get("/share/setup")
def share_setup():
    f = FRONTEND / "share-setup.html"
    return FileResponse(f) if f.exists() else JSONResponse({"error": "missing"}, status_code=404)


@app.get("/share/shortcut")
def share_shortcut():
    f = FRONTEND / "share-shortcut.html"
    return FileResponse(f) if f.exists() else JSONResponse({"error": "missing"}, status_code=404)


@app.get("/manifest.webmanifest")
def manifest():
    f = FRONTEND / "manifest.webmanifest"
    return FileResponse(f, media_type="application/manifest+json") if f.exists() else JSONResponse({"error": "missing"}, status_code=404)


@app.get("/service-worker.js")
def service_worker():
    f = FRONTEND / "service-worker.js"
    return FileResponse(f, media_type="application/javascript") if f.exists() else JSONResponse({"error": "missing"}, status_code=404)


@app.get("/")
def index():
    f = FRONTEND / "index.html"
    return FileResponse(f) if f.exists() else {"error": "frontend not built"}


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
