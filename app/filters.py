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


# ---------------------------------------------------------------- identity
_NORM = re.compile(r"[^a-z0-9]+")


def fingerprint(source, title, link=""):
    """
    Stable id. Uses the normalised title stem plus source so the same listing
    reposted at a new URL doesn't duplicate, but two genuinely different roles
    at one company still count separately.
    """
    stem = _NORM.sub(" ", (title or "").lower()).strip()[:70]
    basis = f"{source}|{stem}" if stem else f"{source}|{link}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


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
