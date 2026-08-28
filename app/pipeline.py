"""
Ingestion orchestrator.

Runs every source, records a health row per source per run, and writes items.
A failing source never takes down the run — it's recorded and the rest continue,
because "this source is blocked" is information the product needs to display,
not an error to crash on.
"""
import time, traceback
from . import db
from .config import INGEST_INTERVAL_MIN
from .sources import SOURCES
from .fetcher import Blocked, FetchError, take_retry_notes
from .scrapers import rss, jobposting, festivalapi

SCRAPERS = {"rss": rss, "jobposting": jobposting, "festivalapi": festivalapi}


def run_source(source):
    run_id = db.start_run(source["name"])
    t0 = time.time()
    take_retry_notes()                      # notes are per-source; start clean

    def detail(extra=""):
        """Run detail plus any retries the fetcher recorded for this source."""
        return "; ".join(x for x in [extra, *take_retry_notes()] if x)

    try:
        mod = SCRAPERS[source["kind"]]
        items, raw_count = mod.scrape(source)
        new, seen = db.upsert_items(items)
        status = "ok" if items else "empty"
        db.finish_run(run_id, status, fetched=raw_count, kept=len(items),
                      new_items=new, detail=detail())
        return dict(source=source["name"], status=status, fetched=raw_count,
                    kept=len(items), new=new, seen=seen,
                    ms=int((time.time() - t0) * 1000))
    except Blocked as e:
        db.finish_run(run_id, "blocked", detail=detail(str(e)))
        return dict(source=source["name"], status="blocked", error=str(e),
                    ms=int((time.time() - t0) * 1000))
    except FetchError as e:
        db.finish_run(run_id, "error", detail=detail(str(e)))
        return dict(source=source["name"], status="error", error=str(e),
                    ms=int((time.time() - t0) * 1000))
    except Exception as e:
        db.finish_run(run_id, "error", detail=detail(f"{type(e).__name__}: {e}"))
        traceback.print_exc()
        return dict(source=source["name"], status="error",
                    error=f"{type(e).__name__}: {e}",
                    ms=int((time.time() - t0) * 1000))


def skip_source(source):
    """Record a cadence skip as its own run row, so /api/sources shows the real
    reason a source is quiet instead of implying it failed."""
    refresh = source.get("refresh_min", INGEST_INTERVAL_MIN)
    run_id = db.start_run(source["name"])
    db.finish_run(run_id, "skipped",
                  detail=f"refreshes every {refresh} min; last good run is newer")
    return dict(source=source["name"], status="skipped", refresh_min=refresh, ms=0)


def run_all(only=None, verbose=True):
    db.init_db()
    results = []
    targets = [s for s in SOURCES if not only or s["id"] in only]
    for s in targets:
        # An explicit single-source trigger is a deliberate human action and
        # overrides the cadence; the scheduled sweep respects it.
        if not only and not db.due_for_refresh(
                s["name"], s.get("refresh_min", INGEST_INTERVAL_MIN)):
            results.append(skip_source(s))
            if verbose:
                print(f"SKIP  {s['name']:24s} not due for refresh")
            continue
        r = run_source(s)
        results.append(r)
        if verbose:
            flag = {"ok": "OK  ", "empty": "EMPTY", "blocked": "BLOCK",
                    "error": "ERR ", "skipped": "SKIP "}
            print(f"{flag.get(r['status'],'?'):5s} {r['source']:24s} "
                  f"fetched={r.get('fetched',0):4d} kept={r.get('kept',0):4d} "
                  f"new={r.get('new',0):4d} {r.get('error','')[:60]}")
    db.expire_stale()
    if verbose:
        ok = sum(1 for r in results if r["status"] == "ok")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        tot_new = sum(r.get("new", 0) for r in results)
        print(f"\n{ok}/{len(results) - skipped} sources healthy · "
              f"{skipped} skipped (not due) · {tot_new} new items")
    return results


if __name__ == "__main__":
    run_all()
