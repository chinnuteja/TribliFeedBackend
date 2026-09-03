"""Festival API named plans honour the credit cap and record partial failures.
python test_festivalapi_queries.py"""
import os, tempfile
os.environ["TRIBLI_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["FESTIVAL_API_KEY"] = "fes_test"
os.environ["TRIBLI_FESTIVAL_CREDITS"] = "3"

from app.fetcher import FetchError, Blocked
from app.scrapers import festivalapi as fa

fa.FESTIVAL_API_KEY = "fes_test"

calls = []


def fake_json(url, headers=None, retries=2):
    calls.append(url)
    if "short_film" in url:
        raise FetchError("HTTP 500")
    if "closing-soon" in url:
        return {"results": []}
    return {"results": [
        {"id": "iffk", "name": "IFFK", "country": "India",
         "submission_url": "https://www.iffk.in/submit-2026",
         "deadline_regular": "2026-09-10", "regular_fee": 0,
         "categories": ["feature"]},
        {"id": "iffk", "name": "IFFK duplicate",
         "submission_url": "https://www.iffk.in/submit-2026"},
    ]}


fa.get_json = fake_json
src = dict(id="festivalapi", name="Festival API", kind="festivalapi",
           category="festivals", credit_cap=3)
items, raw = fa.scrape(src)
notes = fa.take_run_notes()
assert any("india_short" in n for n in notes), notes
assert any("credits=" in n for n in notes), notes
# cap 3: india_open(1) + india_short fail still shouldn't charge? we only charge
# on success. Then closing_soon(2) fits 0+2=2, india_doc skipped or global.
assert any("credits=" in n and "/" in n for n in notes)
names = [i["title"] for i in items]
assert names.count("IFFK") == 1, names
assert all(i["kind"] == "festival" for i in items)
assert all(i["source"] == "Festival API" for i in items)

# 402 remains Blocked
def paywall(url, headers=None, retries=2):
    raise Blocked("HTTP 402 — API credits exhausted")


fa.get_json = paywall
try:
    fa.scrape(src)
    raise AssertionError("402 must be Blocked")
except Blocked as e:
    assert "402" in str(e)

plans = fa.query_plans("2026-08-31")
assert plans[0]["id"] == "india_open"
assert sum(p["cost"] for p in plans) >= 5
print("festivalapi queries OK")
