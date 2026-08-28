"""A source is skipped only while a recent *successful* run exists.
python test_refresh_cadence.py"""
import os, tempfile
os.environ["TRIBLI_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")

from app import db

db.init_db()

# never run before -> always due
assert db.due_for_refresh("Fest", 10080)

db.finish_run(db.start_run("Fest"), "ok", kept=40)
assert not db.due_for_refresh("Fest", 10080)     # weekly: not due again
assert db.due_for_refresh("Fest", 0)             # zero cadence: always due

# a later failure must not reset the clock — the good run still counts
db.finish_run(db.start_run("Fest"), "blocked", detail="HTTP 402")
assert not db.due_for_refresh("Fest", 10080)

# failures alone never satisfy the cadence
db.finish_run(db.start_run("Dead"), "blocked", detail="HTTP 403")
db.finish_run(db.start_run("Dead"), "empty")
assert db.due_for_refresh("Dead", 10080)

# a skip row is not a success either
db.finish_run(db.start_run("Dead"), "skipped")
assert db.due_for_refresh("Dead", 10080)

# aged-out success -> due again
with db.tx() as c:
    c.execute("UPDATE runs SET finished_at=datetime('now','-8 days') "
              "WHERE source='Fest' AND status='ok'")
assert db.due_for_refresh("Fest", 10080)
print("refresh cadence OK")
