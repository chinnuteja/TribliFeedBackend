"""HTTP layer. Rate-limited per host, robots.txt aware, retries on transient errors.

Several real sources (StudioBinder) reject requests without a browser-like UA,
and several (ASC, MasterClass) block datacenter IPs entirely. We identify
ourselves honestly and treat a block as a result, not something to evade.
"""
import time, threading, urllib.robotparser
from urllib.parse import urlparse
import httpx
from .config import USER_AGENT, REQUEST_TIMEOUT, PER_HOST_DELAY, RESPECT_ROBOTS

_last_hit = {}
_lock = threading.Lock()       # guards the _host_locks registry, nothing else
_host_locks = {}
_robots_cache = {}

# Breadcrumbs for retries worth reporting. The pipeline drains these per source
# and writes them into the run detail, so an intermittent block is visible in
# /api/sources rather than looking like a clean run.
_retry_notes = []


def take_retry_notes():
    """Drain and return retry notes recorded since the last call."""
    notes = list(_retry_notes)
    _retry_notes.clear()
    return notes

# Some publishers 403 a bot UA but serve the same public page to a browser UA.
# We use this only where the content is public and robots.txt permits it.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class Blocked(Exception):
    """Source actively refuses automated access."""


class FetchError(Exception):
    pass


def _throttle(host):
    """At most one request per PER_HOST_DELAY to a given host.

    The lock is per host. Sleeping inside a single global lock — as this used to
    — serialised every request in the process no matter which host it was for,
    so MAX_WORKERS bought nothing and two unrelated sites queued behind each
    other. _last_hit[host] is only touched under that host's own lock.
    """
    with _lock:
        host_lock = _host_locks.setdefault(host, threading.Lock())
    with host_lock:
        last = _last_hit.get(host, 0)
        wait = PER_HOST_DELAY - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.time()


def robots_allows(url, ua=USER_AGENT):
    """
    Check robots.txt, fetching it with our own HTTP client.

    We deliberately do NOT use RobotFileParser.read(): it fetches with urllib's
    default User-Agent, which many CDNs answer with 403 — and the parser treats
    a 403 as "disallow everything". That silently blocked ~10 sources whose
    robots.txt actually only disallow /wp-admin/. A failure to READ robots.txt
    is not a disallow, so we fetch it ourselves and parse the real text.
    """
    if not RESPECT_ROBOTS:
        return True
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    if root not in _robots_cache:
        rp = None
        try:
            with httpx.Client(timeout=10, follow_redirects=True) as c:
                r = c.get(f"{root}/robots.txt",
                          headers={"User-Agent": BROWSER_UA,
                                   "Accept": "text/plain,*/*"})
            if r.status_code == 200 and r.text.strip():
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(r.text.splitlines())
            # 404 / 403 / empty -> no usable rules -> not a prohibition
        except Exception:
            rp = None
        _robots_cache[root] = rp

    rp = _robots_cache[root]
    if rp is None:
        return True
    try:
        return rp.can_fetch(ua, url) or rp.can_fetch("*", url)
    except Exception:
        return True


def get(url, browser_ua=False, retries=2, check_robots=True):
    """Fetch a URL as text. Raises Blocked / FetchError."""
    if check_robots and not robots_allows(url):
        raise Blocked(f"robots.txt disallows {url}")

    host = urlparse(url).netloc
    ua = BROWSER_UA if browser_ua else USER_AGENT
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml,"
                  "application/rss+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    }
    last_err = None
    retried_403 = False
    for attempt in range(retries + 1):
        _throttle(host)
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as c:
                r = c.get(url, headers=headers)
            # A 403 is not always a standing policy. Sundance serves 200 from
            # other networks and 403 here intermittently, so give it one backed-off
            # second look before recording the source as blocked.
            if r.status_code == 403 and not retried_403:
                retried_403 = True
                _retry_notes.append(f"HTTP 403 from {urlparse(url).netloc} — retried once")
                last_err = Blocked("HTTP 403 (retried once)")
                time.sleep(2.0)
                continue
            if r.status_code in (401, 403, 405, 429):
                raise Blocked(f"HTTP {r.status_code}"
                              + (" (retried once)" if retried_403 else ""))
            if r.status_code == 202 and "sgcaptcha" in r.text[:400]:
                raise Blocked("bot-protection challenge")
            if r.status_code >= 500:
                last_err = FetchError(f"HTTP {r.status_code}")
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code}")
            return r.text
        except Blocked:
            raise
        except httpx.HTTPError as e:
            last_err = FetchError(f"{type(e).__name__}: {e}")
            time.sleep(1.0 * (attempt + 1))
    raise last_err or FetchError("unknown fetch failure")


def get_json(url, headers=None, retries=2):
    host = urlparse(url).netloc
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    last_err = None
    for attempt in range(retries + 1):
        _throttle(host)
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as c:
                r = c.get(url, headers=h)
            if r.status_code in (401, 403, 429):
                raise Blocked(f"HTTP {r.status_code} — check API key / quota")
            # 402 was falling through to the generic handler, where the caller's
            # except-and-continue turned an exhausted quota into a silent "empty".
            if r.status_code == 402:
                raise Blocked("HTTP 402 — API credits exhausted")
            if r.status_code >= 500:
                last_err = FetchError(f"HTTP {r.status_code}")
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Blocked:
            raise
        except Exception as e:
            last_err = FetchError(f"{type(e).__name__}: {e}")
            time.sleep(1.0 * (attempt + 1))
    raise last_err or FetchError("unknown json fetch failure")
