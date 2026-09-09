"""One robots-aware fetch of a shared HTTP(S) URL.

Generic JSON-LD / Open Graph / canonical / title only. No platform CSS
selectors, no login automation, no WhatsApp fetches. A block or login wall
is information: the exact URL can still be a redirect when the shared
caption already proves a specific current call.
"""
import json, re
from urllib.parse import urlparse, urljoin

from .fetcher import get, Blocked, FetchError
from .filters import clean_text, is_permalink, whatsapp_url_kind

_LDJSON = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)
_CANON = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.I)
_CANON2 = re.compile(
    r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']', re.I)
_OG = re.compile(
    r'<meta[^>]+property=["\']og:(title|url|description)["\'][^>]+content=["\']([^"\']*)["\']',
    re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_LOGIN = re.compile(
    r"type=['\"]password['\"]|name=['\"]password['\"]|sign[- ]?in|log[- ]?in",
    re.I)

NO_FETCH_HOSTS = {
    "whatsapp.com", "www.whatsapp.com", "wa.me", "api.whatsapp.com",
    "web.whatsapp.com", "chat.whatsapp.com",
}


def looks_like_login(html: str) -> bool:
    return bool(_LOGIN.search(html or ""))


def _ld_job(html: str):
    for m in _LDJSON.finditer(html or ""):
        try:
            data = json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue
        nodes = data if isinstance(data, list) else [data]
        stack = list(nodes)
        while stack:
            n = stack.pop()
            if isinstance(n, list):
                stack.extend(n)
                continue
            if not isinstance(n, dict):
                continue
            t = n.get("@type")
            types = t if isinstance(t, list) else [t]
            if "JobPosting" in types:
                return n
            for k in ("@graph", "mainEntity", "itemListElement"):
                if k in n:
                    stack.append(n[k])
    return None


def parse_public_html(url: str, html: str) -> dict:
    """Generic metadata. Empty strings when a field is missing."""
    og = {k.lower(): v for k, v in _OG.findall(html or "")}
    canon = ""
    m = _CANON.search(html or "") or _CANON2.search(html or "")
    if m:
        canon = urljoin(url, m.group(1).strip())
    title_m = _TITLE.search(html or "")
    page_title = clean_text(title_m.group(1), 180) if title_m else ""
    job = _ld_job(html)
    title = ""
    description = ""
    org = ""
    deadline = ""
    posted = ""
    fmt = "html"
    if job:
        fmt = "jsonld_jobposting"
        title = clean_text(job.get("title"), 180)
        description = clean_text(job.get("description"), 400)
        org_n = job.get("hiringOrganization")
        if isinstance(org_n, dict):
            org = clean_text(org_n.get("name"), 90)
        elif isinstance(org_n, str):
            org = clean_text(org_n, 90)
        deadline = str(job.get("validThrough") or "")[:10]
        posted = str(job.get("datePosted") or "")[:10]
    title = title or clean_text(og.get("title"), 180) or page_title
    description = description or clean_text(og.get("description"), 400)
    final_url = canon or og.get("url") or url
    return {
        "title": title,
        "description": description,
        "org": org,
        "deadline": deadline,
        "posted_at": posted,
        "canonical": final_url,
        "format": fmt,
        "login": looks_like_login(html),
    }


def enrich_url(url: str) -> dict:
    """Fetch once. Never raises — blocked/login become an honest status."""
    url = (url or "").strip()
    if not url.lower().startswith("https://") and not url.lower().startswith("http://"):
        return {"status": "skipped", "reason": "not http(s)"}
    if whatsapp_url_kind(url) or urlparse(url).netloc.lower() in NO_FETCH_HOSTS:
        return {"status": "skipped", "reason": "whatsapp-owned host is not fetched"}
    if not is_permalink(url):
        return {"status": "rejected", "reason": "not a permalink"}
    try:
        html = get(url)
    except Blocked as e:
        return {"status": "blocked", "reason": str(e), "url": url}
    except FetchError as e:
        return {"status": "error", "reason": str(e), "url": url}
    meta = parse_public_html(url, html)
    if meta.get("login"):
        return {"status": "login", "reason": "page requires sign-in", "url": url,
                **meta}
    return {"status": "ok", "url": url, **meta}
