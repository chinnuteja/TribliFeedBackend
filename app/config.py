"""Configuration. Secrets come from the environment, never from source."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(path=None):
    """Load KEY=value pairs from .env into the process environment.

    A real environment variable always wins, so an exported secret overrides the
    file and CI needs no .env at all. Stdlib only: a dotenv dependency would be
    more surface to audit than the ten lines it replaces.
    """
    path = path or BASE_DIR / ".env"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return                                  # no .env is a normal setup
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):          # README documents `export FOO=`;
            line = line[len("export "):].strip()  # accept it pasted verbatim
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env()

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = os.getenv("TRIBLI_DB", str(DATA_DIR / "tribli.db"))

# Festival API key — set via environment, e.g. export FESTIVAL_API_KEY=fes_...
FESTIVAL_API_KEY = os.getenv("FESTIVAL_API_KEY", "").strip()

USER_AGENT = os.getenv(
    "TRIBLI_UA",
    "TribliFeedBot/0.1 (+https://tribli.example/bot; contact@tribli.example)",
)

# Politeness
REQUEST_TIMEOUT = int(os.getenv("TRIBLI_TIMEOUT", "25"))
PER_HOST_DELAY = float(os.getenv("TRIBLI_DELAY", "1.0"))   # seconds between hits to same host
MAX_WORKERS = int(os.getenv("TRIBLI_WORKERS", "8"))
RESPECT_ROBOTS = os.getenv("TRIBLI_ROBOTS", "1") == "1"

# How many detail pages to pull per opportunity source per run
DETAIL_LIMIT = int(os.getenv("TRIBLI_DETAIL_LIMIT", "60"))

# How many articles one feed may contribute per run. 20 tech blogs at 25 entries
# each buried the categories people actually open the app for.
ARTICLE_LIMIT = int(os.getenv("TRIBLI_ARTICLE_LIMIT", "5"))

# Job RSS is denser than craft blogs; still cap so one hourly board cannot
# bury AIO Cine / Castkro in the interleaved Opportunities rail.
OPPORTUNITY_RSS_LIMIT = int(os.getenv("TRIBLI_OPP_RSS_LIMIT", "15"))

# Festival API bills per search. A named query plan must stop before this cap.
FESTIVAL_API_CREDIT_CAP = int(os.getenv("TRIBLI_FESTIVAL_CREDITS", "6"))

# Scheduler
INGEST_INTERVAL_MIN = int(os.getenv("TRIBLI_INTERVAL_MIN", "180"))  # every 3 hours
RUN_ON_BOOT = os.getenv("TRIBLI_RUN_ON_BOOT", "1") == "1"

API_HOST = os.getenv("TRIBLI_HOST", "0.0.0.0")
API_PORT = int(os.getenv("TRIBLI_PORT", "8000"))
