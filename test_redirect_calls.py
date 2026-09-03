"""Redirect cards require a single-call permalink, title, and current deadline.
python test_redirect_calls.py"""
import os, tempfile
os.environ["TRIBLI_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["TRIBLI_ROBOTS"] = "0"

from app.filters import is_permalink, deadline_current
from app.scrapers import official_call as oc
from app.fetcher import Blocked

SRC_BASE = dict(id="alteff", name="ALT EFF Film Fund", kind="official_call",
                category="grants", credibility=5, publisher="ALT EFF")


def src(**call):
    s = dict(SRC_BASE)
    s["call"] = call
    return s


def fake_ok(url, browser_ua=False):
    return "<html><body>Film Fund 2026 application</body></html>"


oc.get = fake_ok

good = src(title="ALT EFF Film Fund 2026 — DocEdge window",
           permalink="https://www.alteff.in/film-fund",
           deadline="2026-12-10",
           publisher="ALT EFF")
items, raw = oc.scrape(good)
assert raw == 1
assert len(items) == 1, items
it = items[0]
assert it["display_mode"] == "redirect"
assert it["kind"] == "article"
assert it["category"] == "grants"
assert it["link"] == "https://www.alteff.in/film-fund"
assert it["trust"] == "external"
assert "img" not in (it.get("description") or "")
assert it["deadline"] == "2026-12-10"

# homepage / index / missing deadline / expired / injection / unreachable
assert oc.scrape(src(title="CastYou", permalink="https://castyou.in/",
                     deadline="2026-12-10"))[0] == []
assert oc.scrape(src(title="Auditions", permalink="https://castyou.in/auditions/",
                     deadline="2026-12-10"))[0] == []
assert oc.scrape(src(title="Jobs", permalink="https://www.reelon.com/alljobs",
                     deadline="2026-12-10"))[0] == []
assert oc.scrape(src(title="Fund", permalink="https://www.alteff.in/film-fund",
                     deadline=""))[0] == []
assert oc.scrape(src(title="Fund", permalink="https://www.alteff.in/film-fund",
                     deadline="2020-01-01"))[0] == []
assert oc.scrape(src(title="<script>alert(1)</script>",
                     permalink="https://www.alteff.in/film-fund",
                     deadline="2026-12-10"))[0] == []


def login_page(url, browser_ua=False):
    return "<html><body>Sign in <input type='password' name='password'></body></html>"


oc.get = login_page
assert oc.scrape(good)[0] == []


def boom(url, browser_ua=False):
    raise Blocked("HTTP 403")


oc.get = boom
try:
    oc.scrape(good)
    raise AssertionError("blocked permalink must surface as Blocked")
except Blocked:
    pass

assert is_permalink("https://www.alteff.in/film-fund")
assert not is_permalink("https://castyou.in/")
assert not is_permalink("https://castyou.in/auditions/")
assert not deadline_current("2020-01-01")
assert deadline_current("2099-01-01")
print("redirect calls OK")
