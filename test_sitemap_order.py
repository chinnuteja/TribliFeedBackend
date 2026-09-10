"""Sitemap URLs must come back newest-lastmod-first. python test_sitemap_order.py"""
from app.scrapers.jobposting import _norm_date, _sitemap_urls


def sm(*pairs):
    body = "".join(
        f"<url><loc>{u}</loc>" + (f"<lastmod>{lm}</lastmod>" if lm else "")
        + "<changefreq>weekly</changefreq></url>"
        for u, lm in pairs)
    return f"<urlset>{body}</urlset>"


# Dazzlerr's real shape: oldest first, newest last, unordered in between
out = _sitemap_urls(sm(("/a", "2020-11-25T04:00:00+05:30"),
                       ("/b", "2026-08-19T04:00:00+05:30"),
                       ("/c", "2023-01-02T04:00:00+05:30")))
assert out == ["/b", "/c", "/a"], out

# equal lastmod keeps file order; undated entries sort last, file order kept
out = _sitemap_urls(sm(("/x", "2026-08-20"), ("/y", "2026-08-20"),
                       ("/n1", ""), ("/z", "2026-08-21"), ("/n2", "")))
assert out == ["/z", "/x", "/y", "/n1", "/n2"], out

# a sitemap with no <url> wrappers still yields its locs, in file order
assert _sitemap_urls("<urlset><loc>/p</loc><loc>/q</loc></urlset>") == ["/p", "/q"]
assert _sitemap_urls("<urlset></urlset>") == []
print("sitemap order OK")

# --- max_age_days -----------------------------------------------------------
import datetime
from app.scrapers.jobposting import _sitemap_urls as _su

recent = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
old = (datetime.date.today() - datetime.timedelta(days=400)).isoformat()
edge = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()

xml = sm(("/new", recent + "T04:00:00+05:30"),
         ("/old", old + "T04:00:00+05:30"),
         ("/edge", edge + "T23:59:59+05:30"),
         ("/undated", ""))
assert _su(xml, 60) == ["/new", "/edge", "/undated"], _su(xml, 60)   # edge kept
assert _su(xml, None) == ["/new", "/edge", "/old", "/undated"]       # off = unchanged
assert _su(xml, 1) == ["/undated"], _su(xml, 1)                      # unknown age kept
print("max_age_days OK")

# Dazzlerr uses both padded and unpadded day-first dates.
assert _norm_date("31-08-2026T00:00") == "2026-08-31"
assert _norm_date("9-7-2026") == "2026-07-09"
assert _norm_date("2026-09-08") == "2026-09-08"
assert _norm_date("31-02-2026") == ""
print("deadline normalisation OK")

# Dazzlerr's public sitemap rejects the identified crawler UA from Render even
# though robots allow it. Confirm its explicit browser-UA source flag reaches
# the first sitemap request; listing pages already use this UA.
from app.scrapers import jobposting as _jp
from app.sources import SOURCES

_dazzlerr = next(s for s in SOURCES if s["id"] == "dazzlerr")
assert _dazzlerr.get("sitemap_browser_ua") is True
_calls = []
_old_get, _old_unseen, _old_mark = _jp.get, _jp.db.unseen_urls, _jp.db.mark_urls_seen
try:
    def _fake_get(url, browser_ua=False, **kwargs):
        _calls.append((url, browser_ua))
        return "<urlset></urlset>"

    _jp.get = _fake_get
    _jp.db.unseen_urls = lambda source_id, urls, limit: []
    _jp.db.mark_urls_seen = lambda source_id, urls: None
    _jp.scrape(_dazzlerr)
finally:
    _jp.get, _jp.db.unseen_urls, _jp.db.mark_urls_seen = _old_get, _old_unseen, _old_mark

assert _calls and _calls[0] == (_dazzlerr["sitemap"], True), _calls
print("Dazzlerr sitemap UA OK")
