"""Share/ingest write paths are authenticated, rate-limited, and secret-safe.
python test_share_security.py"""
import os, tempfile, io, logging
from pathlib import Path

os.environ["TRIBLI_DB"] = os.path.join(tempfile.mkdtemp(), "sec.db")
os.environ["TRIBLI_SHARE_SECRET"] = "operator-secret-xyz"
os.environ["TRIBLI_SHARE_ENABLED"] = "1"
os.environ["TRIBLI_SHARE_RATE"] = "8"
os.environ["TRIBLI_SHARE_MAX_BYTES"] = "4096"
os.environ["TRIBLI_ROBOTS"] = "0"
os.environ.pop("GEMINI_API_KEY", None)

from fastapi.testclient import TestClient
from app import db
from app.api import app
from app.share_auth import issue_device_token, hash_token
from app import shared_opportunity as so

db.init_db()


def _no_gemini(*a, **k):
    raise so.ExtractionError("offline suite must not call Gemini")


so.gemini_extract = _no_gemini

c = TestClient(app)
CAST = ("Casting call — Male extras in Hyderabad\n"
        "Apply on WhatsApp: +91 98765 43210\n")

# unauthenticated share is refused
r = c.post("/api/share", data={"text": CAST})
assert r.status_code in (401, 403), r.status_code

# ingest is no longer an open scrape trigger
ing = c.post("/api/ingest")
assert ing.status_code in (401, 403), ing.status_code

# wrong operator secret cannot claim a device
bad = c.post("/api/share/claim", json={"secret": "nope"})
assert bad.status_code in (401, 403)

# claim with operator secret issues a device token, not the operator secret
claim = c.post("/api/share/claim", json={"secret": "operator-secret-xyz"})
assert claim.status_code == 200, claim.text
body = claim.json()
token = body["token"]
assert token
assert token != "operator-secret-xyz"
assert "operator-secret-xyz" not in claim.text

ok = c.post("/api/share", data={"text": CAST},
            headers={"Authorization": f"Bearer {token}"})
assert ok.status_code == 200, ok.text
payload = ok.json()
assert payload["status"] in ("published", "duplicate"), payload
assert "9876543210" not in ok.text
assert "operator-secret-xyz" not in ok.text

# A malformed JSON request must be rejected safely instead of becoming a 500.
bad_json = c.post(
    "/api/share", content="not-json",
    headers={"Authorization": f"Bearer {token}",
             "Content-Type": "application/json"},
)
assert bad_json.status_code == 400, bad_json.status_code

# cookie from claim also authenticates
c2 = TestClient(app)
claimed = c2.post("/api/share/claim", json={"secret": "operator-secret-xyz"})
assert claimed.status_code == 200
cookie_ok = c2.post("/api/share", data={"text": CAST + "Second production house\n"})
assert cookie_ok.status_code == 200, cookie_ok.text

# javascript / data URLs never become apply targets
js = c.post("/api/share",
            data={"text": "Casting call — extras Hyderabad\nApply: javascript:alert(1)"},
            headers={"Authorization": f"Bearer {token}"})
assert js.status_code == 200
assert js.json()["status"] == "rejected"

# oversized upload rejected
big = b"x" * 5000
huge = c.post(
    "/api/share",
    data={"text": "Casting call poster"},
    files={"image": ("x.png", io.BytesIO(big), "image/png")},
    headers={"Authorization": f"Bearer {token}"},
)
assert huge.status_code in (413, 400), huge.status_code

# disallowed MIME
bad_mime = c.post(
    "/api/share",
    files={"image": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    headers={"Authorization": f"Bearer {token}"},
)
assert bad_mime.status_code in (400, 415), bad_mime.status_code

# kill switch
os.environ["TRIBLI_SHARE_ENABLED"] = "0"
killed = c.post("/api/share", data={"text": CAST},
                headers={"Authorization": f"Bearer {token}"})
assert killed.status_code == 503
os.environ["TRIBLI_SHARE_ENABLED"] = "1"

# rate limit: independent of ingest
os.environ["TRIBLI_SHARE_RATE"] = "2"
from app import share_auth
share_auth.reset_rate_limits()
t2 = issue_device_token(label="rate")
texts = [
    CAST + "Role A walk-in extras\n",
    CAST + "Role B crew call cinematographer\n",
    CAST + "Role C hiring compositor\n",
]
codes = []
for t in texts:
    resp = c.post("/api/share", data={"text": t},
                  headers={"Authorization": f"Bearer {t2}"})
    codes.append(resp.status_code)
assert 429 in codes, codes

# ingest with bearer of the *share device* token is not enough; needs operator secret
nope = c.post("/api/ingest", headers={"Authorization": f"Bearer {token}"})
assert nope.status_code in (401, 403)

from app import pipeline
pipeline.run_all = lambda **kw: [{"source": "mock", "status": "ok"}]
ing_ok_auth = c.post("/api/ingest",
                     headers={"Authorization": "Bearer operator-secret-xyz"})
assert ing_ok_auth.status_code == 200, ing_ok_auth.status_code

# hashed storage only
assert hash_token(token) != token
with db.tx() as conn:
    rows = conn.execute("SELECT token_hash FROM share_devices").fetchall()
    assert rows
    assert all(r["token_hash"] != token for r in rows)

log = logging.getLogger("app.share_ingest")
# complete numbers must not be formatted into log records by process helpers
from app.share_ingest import mask_contact
assert mask_contact("+919876543210") != "+919876543210"
assert "43210" not in mask_contact("+919876543210") or mask_contact("+919876543210").count("4") < 5

print("share security OK")
