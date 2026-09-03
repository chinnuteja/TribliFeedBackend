"""
Filtering and trust scoring.

Three separate jobs, deliberately kept apart:

  1. sanitise()      — security. Strip/reject injection payloads.
                       This is not paranoia: SRFTI's official feed (a government
                       film school) has served <script>alert(1)</script> as a post
                       title. Anything reaching the DB must be inert.

  2. editorial()     — policy. Drop content TRIBLI has decided isn't useful to a
                       working filmmaker: box office, trailers, reviews, gossip,
                       affiliate gear deals.

  3. assess_trust()  — safety. Score opportunities for the fee-first / casting-couch
                       scam patterns that are well documented in this industry.
                       We never auto-publish a risky listing as trustworthy.
"""
import re, html, hashlib

# ---------------------------------------------------------------- sanitising
_TAG = re.compile(r"<[^>]+>")
_INJECT = re.compile(
    r"<\s*/?\s*script|<\s*iframe|javascript\s*:|on(?:error|click|load|mouse\w+)\s*=|"
    r"data\s*:\s*text/html|<\s*xss|alert\s*\(", re.I)


def clean_text(raw, limit=420):
    """HTML -> plain inert text."""
    if not raw:
        return ""
    t = _TAG.sub(" ", str(raw))
    t = html.unescape(t)
    t = t.replace("\u200b", "")
    # markdown emphasis leaks through several feeds (Castkro especially)
    t = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", t)
    t = re.sub(r"[`_]{2,}", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


def is_injection(*fields):
    blob = " ".join(str(f or "") for f in fields)
    return bool(_INJECT.search(blob))


# ---------------------------------------------------------------- editorial
_REJECT_TITLE = re.compile(
    r"box office|opening day collection|day \d+ collection|worldwide collection|"
    r"trailer (?:out|launch|drop|review)|teaser (?:out|launch)|first look|"
    r"movie review|film review|^review:|song (?:out|launch|release)|"
    r"birthday|wedding|dating|net worth|spotted at|red carpet|"
    r"on sale for|% off|discount of|save \$|black friday|cyber monday|price drop|"
    r"deal of the day|best deals", re.I)

_REJECT_ANY = re.compile(r"box office (?:collection|report|day)", re.I)


def editorial_ok(title, description=""):
    """True if this belongs in a professional feed."""
    t = (title or "").strip()
    if len(t) < 8:
        return False
    if _REJECT_TITLE.search(t):
        return False
    if _REJECT_ANY.search(t + " " + (description or "")[:200]):
        return False
    return True


# ---------------------------------------------------------------- scam / trust
# Documented patterns in Indian casting fraud. Sources: fee-for-audition scams,
# fake "artist card" rackets, casting-couch solicitation, credential phishing.
_FEE_DEMAND = re.compile(
    r"registration fee|joining fee|security deposit|refundable deposit|"
    r"pay (?:rs|₹|inr)\s?\d|processing fee|artist card fee|audition fee|"
    r"membership charges|token amount|pay to (?:apply|register|confirm)", re.I)

_ID_PHISH = re.compile(
    r"\baadhaar\b|\bpan card\b|bank (?:account|details)|passbook|"
    r"original documents|share your otp", re.I)

_INTIMATE = re.compile(
    r"\bbold\b|semi[- ]?nude|\bnude\b|intimate scene|adult (?:content|scene|film)|"
    r"glam(?:our)?\s*(?:shoot|shot|photoshoot)?|\bbikini\b|\blingerie\b|"
    r"swimwear|private (?:shoot|apartment|residence)|"
    r"body[- ]?show|no dress code|\bsensual\b", re.I)

_URGENCY = re.compile(
    r"urgent(?:ly)? (?:required|need)|immediate joining|confirm within|"
    r"limited seats|only \d+ slots|today only|hurry", re.I)

_OFFPLATFORM = re.compile(
    r"whatsapp (?:me|on|at)|dm me|telegram|contact on \+?\d{10}|"
    r"call me on|personal number", re.I)

_FREE_EMAIL = re.compile(r"@(?:gmail|yahoo|hotmail|outlook|rediffmail)\.", re.I)


def assess_trust(title, description, org="", source_credibility=3):
    """
    Returns (trust, reasons, score).

    trust:
      blocked      -> never surface. Fee demand or credential phishing.
      quarantine   -> hold for human review. Exploitation-risk pattern.
      caution      -> surface, but flagged.
      external     -> surface normally, still not TRIBLI-verified.

    No listing ever reaches 'verified' automatically. That requires a human or a
    confirmed Organization link — which is the whole point of TRIBLI's model.
    """
    blob = f"{title} {description} {org}"
    reasons, score = [], 0.0

    if _FEE_DEMAND.search(blob):
        reasons.append("Asks applicants for money — legitimate castings never charge to audition.")
        return "blocked", reasons, -10.0

    if _ID_PHISH.search(blob):
        reasons.append("Requests identity or bank documents up front — a known phishing pattern.")
        return "blocked", reasons, -10.0

    risk = 0
    if _INTIMATE.search(blob):
        reasons.append("Mentions intimate or 'bold' content — needs human review before surfacing.")
        risk += 2
    if _OFFPLATFORM.search(blob):
        reasons.append("Pushes contact off-platform to a personal number.")
        risk += 1
    if _FREE_EMAIL.search(blob):
        reasons.append("Contact is a free email address rather than a company domain.")
        risk += 1
    if _URGENCY.search(blob):
        reasons.append("Uses urgency pressure.")
        risk += 1
    if not (org or "").strip():
        reasons.append("No named hiring organisation.")
        risk += 1

    if risk >= 2 and _INTIMATE.search(blob):
        return "quarantine", reasons, -3.0
    if risk >= 3:
        return "quarantine", reasons, -2.0

    score = source_credibility - risk
    # A missing organisation on its own is weak evidence, not a warning sign —
    # plenty of legitimate indie listings omit it. Flag only on corroboration.
    return ("caution" if risk >= 2 else "external"), reasons, float(score)


# ---------------------------------------------------------------- quality gates
# A redirect card is only honest if `link` is the call itself — not a directory,
# homepage, login wall, or SEO index. Public robots access is not enough.
_INDEX_SLUGS = {
    "auditions", "alljobs", "jobs", "job", "search", "browse", "listings",
    "casting-calls", "casting", "feed", "blog", "news", "login", "signin",
    "sign-in", "signup", "register", "apply", "category", "categories",
    "tag", "tags", "page", "home",
}

_OPP_HIT = re.compile(
    r"\b(?:hir(?:e|ing)|job opening|\bjobs?\b|walk[- ]?in|vacanc(?:y|ies)|openings?\b|"
    r"we(?:'| a)re hiring|required at|looking for|now hiring|"
    r"compositor|roto(?:scop)?|vfx artist|cinematographer|"
    r"casting call|crew call)\b", re.I)

_OPP_NEWS = re.compile(
    r"what it is, why it matters|why it matters|learn how|"
    r"\btutorial\b|\bguide to\b|how it changes", re.I)

_CFE_HIT = re.compile(
    r"call for entr(?:y|ies)|entries invited|accepting (?:feature )?films|"
    r"submit(?: your)? (?:films?|entries)|submissions? (?:open|are open)|"
    r"deadline(?: is| of|:)|entry fee", re.I)

_CFE_NEWS = re.compile(
    r"opening film|will open the|award winners?|screening dates|"
    r"winner(?:s)? announced", re.I)

_DATE_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_DATE_TEXT = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+(20\d{2})\b",
    re.I)
_DATE_TEXT_US = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
    re.I)
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def is_permalink(url):
    """True when `url` can stand in as a single call, not a site section."""
    from urllib.parse import urlparse
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    parts = [p.lower() for p in parsed.path.split("/") if p]
    if not parts:
        return False
    if parts[-1] in _INDEX_SLUGS:
        return False
    return True


def opportunity_relevant(title, description=""):
    """True when this RSS/HTML blob is a job, not a blog post about jobs."""
    t = (title or "").strip()
    if len(t) < 8:
        return False
    blob = f"{t} {description or ''}"
    if _OPP_NEWS.search(blob):
        return False
    return bool(_OPP_HIT.search(blob))


def call_for_entry(title, description=""):
    """True when a festival post is an open call, not an opening-film recap."""
    t = (title or "").strip()
    if len(t) < 8:
        return False
    blob = f"{t} {description or ''}"
    if _CFE_NEWS.search(blob) and not _CFE_HIT.search(blob):
        return False
    return bool(_CFE_HIT.search(blob))


def extract_deadline(*fields):
    """Best-effort ISO date from free text. Empty if nothing confident."""
    blob = " ".join(str(f or "") for f in fields)
    m = _DATE_ISO.search(blob)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_TEXT.search(blob)
    if m:
        month = _MONTHS.get(m.group(2).lower())
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}"
    m = _DATE_TEXT_US.search(blob)
    if m:
        month = _MONTHS.get(m.group(1).lower())
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"
    return ""


def deadline_current(deadline, today=None):
    """False when missing, malformed, or already past."""
    import datetime as _dt
    d = (deadline or "")[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return False
    today = today or _dt.date.today()
    try:
        return _dt.date.fromisoformat(d) >= today
    except ValueError:
        return False


# ---------------------------------------------------------------- identity
_NORM = re.compile(r"[^a-z0-9]+")


def festival_stem(title):
    """Identity used to collapse the same festival arriving from two sources."""
    t = (title or "").lower()
    t = re.sub(r"\b(?:call for entr(?:y|ies)|cfe)\b", " ", t)
    t = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)\b", " ", t)
    t = re.sub(r"\b20\d{2}\b", " ", t)
    return _NORM.sub(" ", t).strip()[:70]


def fingerprint(source, title, link=""):
    """
    Stable id. Uses the normalised title stem plus source so the same listing
    reposted at a new URL doesn't duplicate, but two genuinely different roles
    at one company still count separately.
    """
    stem = _NORM.sub(" ", (title or "").lower()).strip()[:70]
    basis = f"{source}|{stem}" if stem else f"{source}|{link}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def build_item(source, *, kind, title, link, display_mode="full", **extra):
    """Shared item shape so every scraper stamps the same provenance fields."""
    import datetime as _dt
    pub = (extra.pop("publisher", None) or source.get("publisher")
           or source.get("name") or "")
    src_url = (extra.pop("source_url", None) or source.get("url")
               or source.get("sitemap") or link)
    return dict(
        id=extra.pop("id", None) or fingerprint(source["id"], title, link),
        kind=kind,
        category=source["category"],
        source=source["name"],
        source_id=source["id"],
        publisher=pub,
        source_url=src_url,
        display_mode=display_mode,
        verified_at=extra.pop("verified_at", "") or (
            _dt.date.today().isoformat() if display_mode == "redirect" else ""),
        title=title,
        link=link,
        trust=extra.pop("trust", "external"),
        trust_reasons=extra.pop("trust_reasons", []),
        raw=extra.pop("raw", {}),
        **extra,
    )


# ---------------------------------------------------------------- region
_SOUTH = {
    "telangana": "telugu", "hyderabad": "telugu", "andhra": "telugu",
    "secunderabad": "telugu", "vijayawada": "telugu", "visakhapatnam": "telugu",
    "tamil nadu": "south", "chennai": "south", "kerala": "south",
    "kochi": "south", "cochin": "south", "trivandrum": "south",
    "thiruvananthapuram": "south", "karnataka": "south", "bengaluru": "south",
    "bangalore": "south", "mysore": "south", "coimbatore": "south",
}
_LANG = {"telugu": "telugu", "tollywood": "telugu",
         "tamil": "south", "malayalam": "south", "kannada": "south",
         "kollywood": "south", "mollywood": "south"}


def region_tier(*fields):
    blob = " ".join(str(f or "") for f in fields).lower()
    for k, v in _LANG.items():
        if k in blob:
            return v
    for k, v in _SOUTH.items():
        if k in blob:
            return v
    return "india"
