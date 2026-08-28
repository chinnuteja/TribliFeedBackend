#!/usr/bin/env python3
"""
TRIBLI feed backend.

  python run.py              serve API + frontend, scrape on boot, then on schedule
  python run.py --ingest     run one ingestion pass and exit
  python run.py --no-scrape  serve only, don't scrape
"""
import sys, threading, time
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler

from app import db
from app.config import (API_HOST, API_PORT, INGEST_INTERVAL_MIN,
                        RUN_ON_BOOT, FESTIVAL_API_KEY)
from app.pipeline import run_all


def banner():
    print("=" * 60)
    print("  TRIBLI feed backend")
    print("=" * 60)
    if not FESTIVAL_API_KEY:
        print("  ! FESTIVAL_API_KEY not set — the Festivals category will be empty.")
        print("    put FESTIVAL_API_KEY=fes_... in .env (see .env.example)")
    print(f"  API      http://{API_HOST}:{API_PORT}")
    print(f"  Schedule every {INGEST_INTERVAL_MIN} min")
    print("=" * 60)


def main():
    db.init_db()
    if "--ingest" in sys.argv:
        run_all()
        return

    banner()
    scrape = "--no-scrape" not in sys.argv
    if scrape:
        sched = BackgroundScheduler(daemon=True)
        sched.add_job(run_all, "interval", minutes=INGEST_INTERVAL_MIN,
                      id="ingest", max_instances=1, coalesce=True)
        sched.start()
        if RUN_ON_BOOT:
            threading.Thread(target=run_all, daemon=True).start()

    uvicorn.run("app.api:app", host=API_HOST, port=API_PORT, log_level="warning")


if __name__ == "__main__":
    main()
