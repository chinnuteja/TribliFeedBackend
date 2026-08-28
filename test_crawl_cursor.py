"""Check the incremental crawl cursor actually advances. python test_crawl_cursor.py"""
import os, tempfile
os.environ["TRIBLI_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")

from app import db

db.init_db()
urls = [f"https://x/{i}" for i in range(10)]

first = db.unseen_urls("s", urls, 4)
assert first == urls[:4], first
db.mark_urls_seen("s", first)

second = db.unseen_urls("s", urls, 4)
assert second == urls[4:8], second            # advanced, did not repeat
db.mark_urls_seen("s", second)

assert db.unseen_urls("other", urls, 4) == urls[:4]   # cursor is per source
assert db.unseen_urls("s", urls, 4) == urls[8:]       # tail only
db.mark_urls_seen("s", urls)
assert db.unseen_urls("s", urls, 4) == []             # exhausted -> caller re-reads head
print("crawl cursor OK")
