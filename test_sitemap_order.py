"""Sitemap URLs must come back newest-lastmod-first. python test_sitemap_order.py"""
from app.scrapers.jobposting import _sitemap_urls


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
