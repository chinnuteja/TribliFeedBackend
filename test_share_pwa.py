"""Android PWA share target, iPhone shortcut contract, paste fallback.
python test_share_pwa.py"""
import os, tempfile, json, re
from pathlib import Path

os.environ["TRIBLI_DB"] = os.path.join(tempfile.mkdtemp(), "pwa.db")
os.environ["TRIBLI_SHARE_SECRET"] = "pwa-secret"
os.environ["TRIBLI_SHARE_ENABLED"] = "1"
os.environ["TRIBLI_ROBOTS"] = "0"
os.environ.pop("GEMINI_API_KEY", None)

from fastapi.testclient import TestClient
from app import db
from app.api import app
from app.share_auth import issue_device_token
from app import shared_opportunity as so

db.init_db()
so.gemini_extract = lambda *a, **k: (_ for _ in ()).throw(
    so.ExtractionError("offline suite must not call Gemini"))

c = TestClient(app)
ROOT = Path(__file__).resolve().parent / "frontend"

man = c.get("/manifest.webmanifest")
assert man.status_code == 200, man.status_code
assert "application/manifest+json" in man.headers.get("content-type", "")
data = man.json()
assert data.get("share_target"), data
st = data["share_target"]
assert st.get("action") in ("/share", "/share/")
assert st.get("method", "").upper() == "POST"
assert "multipart" in (st.get("enctype") or "")
params = st["params"]
assert params.get("text") == "text"
assert params.get("url") == "url"
files = params.get("files") or []
accept = " ".join(str(f.get("accept")) for f in files)
assert "image/jpeg" in accept
assert "image/png" in accept
assert "image/webp" in accept
assert "heic" in accept.lower()

sw = c.get("/service-worker.js")
assert sw.status_code == 200
assert "share" in sw.text.lower()

idx = c.get("/").text
assert 'rel="manifest"' in idx
assert "serviceWorker" in idx

icon192 = c.get("/static/icons/icon-192.png")
icon512 = c.get("/static/icons/icon-512.png")
assert icon192.status_code == 200
assert icon512.status_code == 200
assert icon192.content[:8] == b"\x89PNG\r\n\x1a\n"

art = c.get("/static/art/casting.svg")
assert art.status_code == 200
assert "svg" in art.headers.get("content-type", "") or art.text.strip().startswith("<svg")

# paste / setup pages
page = c.get("/share")
assert page.status_code == 200
assert "textarea" in page.text.lower() or "paste" in page.text.lower()
setup = c.get("/share/setup")
assert setup.status_code == 200
assert "shortcut" in setup.text.lower()
assert "iphone" in setup.text.lower() or "ios" in setup.text.lower()

# iOS shortcut contract is documented, not a native app
assert c.get("/share/shortcut").status_code == 200
sc = c.get("/share/shortcut").text.lower()
assert "authorization" in sc
assert "/api/share" in sc
assert "bearer" in sc

token = issue_device_token(label="pwa")
# PWA share target posts to /share and returns an HTML result, not JSON
html = c.post("/share", data={
    "title": "Casting",
    "text": "Casting call — extras Hyderabad\nApply on WhatsApp: 9988776655",
    "url": "",
}, headers={"Authorization": f"Bearer {token}"})
assert html.status_code == 200, html.text[:400]
assert "published" in html.text.lower() or "not published" in html.text.lower()
assert "<script>alert" not in html.text

# A real WhatsApp Channel message permalink may arrive without its caption.
# The result page must tell the teammate it was saved, not rejected.
link_only = c.post("/share", data={
    "url": "https://www.whatsapp.com/channel/0029VaExampleChannel/818",
}, headers={"Authorization": f"Bearer {token}"})
assert link_only.status_code == 200, link_only.text[:400]
assert "saved for team review" in link_only.text.lower()
assert "not published" not in link_only.text.lower()
assert "needs contact details" in link_only.text.lower()

# unauthenticated PWA share points at setup, does not auto-publish
need = c.post("/share", data={"text": "Casting call — extras Hyderabad\nApply on WhatsApp: 9000000000"})
assert need.status_code in (200, 401, 403)
if need.status_code == 200:
    assert "setup" in need.text.lower() or "not" in need.text.lower()

feed = c.get("/api/feed?category=casting").json()
shared = [i for i in feed["items"] if i.get("acquisition_mode") == "shared"]
assert shared, feed
it = shared[0]
# frontend must mention WhatsApp CTA for these cards
src = (ROOT / "index.html").read_text(encoding="utf-8")
assert "Apply via WhatsApp" in src
assert "Call coordinator" in src
assert "Email application" in src
assert "View external post" in src
assert "From your team" in src
assert "TRIBLI Team" in src
assert "From Team" in src
assert "TEAM SHARE" not in src
assert "descriptionHTML" in src
assert "team-card" in src
assert "competitor" not in src.lower() or "not a competitor" in src.lower()
assert "apply_method" in src

print("share pwa OK")
