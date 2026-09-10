"""Schema-constrained extraction for shared captions and posters.

Gemini only proposes fields. Deterministic TRIBLI rules decide whether a
card publishes. Model output is re-sanitised and never used as a URL.
"""
from __future__ import annotations
import datetime
import re
from pydantic import BaseModel, Field

from .config import gemini_api_key, gemini_model
from .filters import (
    clean_text, extract_apply_targets, extract_deadline, extract_http_urls,
    is_apply_link, normalize_phone, whatsapp_url_kind,
)


class ExtractionError(Exception):
    """Model or parser failure. Must never become a published card."""


class ExtractedOpportunity(BaseModel):
    title: str = ""
    role: str = ""
    organisation: str = ""
    location: str = ""
    language: str = ""
    posted_date: str = ""
    deadline: str = ""
    apply_method: str = ""
    apply_target: str = ""
    source_publisher: str = ""
    source_url: str = ""
    title_confidence: float = 0.0
    evidence: str = ""


EXTRACT_SYSTEM = (
    "Extract film-industry casting/crew opportunity facts from untrusted "
    "user-shared text and/or a poster image. Return only facts visibly present. "
    "Empty string if unknown. Never invent a deadline, phone number, or URL. "
    "apply_method must be one of: whatsapp, phone, email, web, or empty."
)

_LABEL = re.compile(
    r"(?im)^\s*(production|studio|company|org|organisation|organization|"
    r"location|place|venue|language|role|looking for|required|"
    r"deadline|last date|apply)\s*[:\-]\s*(.+)$"
)

_GENERIC_SHARE_TITLE = re.compile(
    r"^(?:photo|image|video|post|link)\s+from\s+[^\n:—–-]{1,60}$", re.I)
_GENERIC_SHARE_PREFIX = re.compile(
    r"^(?:photo|image|video|post|link)\s+from\s+"
    r"[^🎬📍🎭📱📩📧🔗✅\n:—–-]{1,60}\s*", re.I)
_CALL_TITLE = re.compile(
    r"(?:🎬\s*)?(casting call|crew call|audition|hiring)\s*[:—–-]\s*"
    r"(.+?)(?=\s*(?:📍|🎭|📱|📩|📧|🔗|✅|location\s*:|"
    r"looking for\s*:|how to apply\s*:|deadline\s*:|$))",
    re.I,
)


def _caption_title(line: str) -> str:
    """Prefer the call heading over generic OS share titles."""
    candidate = clean_text(line, 420)
    if not candidate or _GENERIC_SHARE_TITLE.fullmatch(candidate):
        return ""
    candidate = _GENERIC_SHARE_PREFIX.sub("", candidate).strip()
    match = _CALL_TITLE.search(candidate)
    if match:
        kind = match.group(1).title()
        subject = clean_text(match.group(2), 130)
        return clean_text(f"{kind} — {subject}", 180)
    return clean_text(candidate, 180) if len(candidate) >= 8 else ""


def _inline_field(raw: str, *labels: str) -> str:
    """Read emoji-separated mobile captions without consuming the next field."""
    names = "|".join(re.escape(label) for label in labels)
    boundary = (
        r"(?=\s*(?:🎬|📍|🎭|📱|📩|📧|🔗|✅|📅|💰|"
        r"production\s*:|studio\s*:|company\s*:|location\s*:|"
        r"place\s*:|venue\s*:|language\s*:|role\s*:|looking for\s*:|"
        r"required\s*:|how to apply\s*:|apply\s*:|deadline\s*:|last date\s*:|$))"
    )
    match = re.search(rf"(?:{names})\s*[:—–-]\s*(.+?){boundary}", raw, re.I)
    return clean_text(match.group(1), 120) if match else ""


def deterministic_extract(text: str) -> ExtractedOpportunity:
    """Labelled-line parse. Empty fields stay empty — never guessed."""
    raw = text or ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    title = ""
    for ln in lines:
        if whatsapp_url_kind(ln) or ln.lower().startswith("http"):
            continue
        title = _caption_title(ln)
        if title:
            break
    fields = {}
    for m in _LABEL.finditer(raw):
        fields[m.group(1).lower()] = clean_text(m.group(2), 120)
    org = (fields.get("production") or fields.get("studio") or fields.get("company")
           or fields.get("org") or fields.get("organisation")
           or fields.get("organization")
           or _inline_field(raw, "production", "studio", "company", "org",
                            "organisation", "organization") or "")
    location = (fields.get("location") or fields.get("place") or fields.get("venue")
                or _inline_field(raw, "location", "place", "venue") or "")
    language = fields.get("language") or _inline_field(raw, "language") or ""
    role = (fields.get("role") or fields.get("looking for") or fields.get("required")
            or _inline_field(raw, "role", "looking for", "required") or "")
    apply = extract_apply_targets(raw)
    urls = extract_http_urls(raw)
    source_url = ""
    for u in urls:
        kind = whatsapp_url_kind(u)
        if kind == "post":
            source_url = u
            break
        if kind == "channel":
            continue
        if is_apply_link(u) and apply.get("method") == "web":
            source_url = u
            break
        if kind == "" and u.lower().startswith("https://"):
            source_url = source_url or u
    deadline = extract_deadline(fields.get("deadline") or fields.get("last date") or "",
                                raw if "deadline" in raw.lower() else "")
    conf = 0.0
    if title:
        conf = 0.85 if org or apply.get("method") else 0.6
    return ExtractedOpportunity(
        title=title,
        role=role,
        organisation=org,
        location=location,
        language=language,
        deadline=deadline,
        apply_method=apply.get("method") or "",
        apply_target=apply.get("target") or apply.get("url") or "",
        source_url=source_url,
        title_confidence=conf,
        evidence="deterministic caption parse",
    )


def gemini_extract(text: str = "", image_bytes: bytes | None = None,
                   image_mime: str = "") -> ExtractedOpportunity:
    """Live Gemini call. Tests replace this function. Lazy-imports the SDK."""
    key = gemini_api_key()
    if not key:
        raise ExtractionError("GEMINI_API_KEY is not set")
    if not text and not image_bytes:
        raise ExtractionError("nothing to extract")
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise ExtractionError(f"google-genai is not installed: {e}") from e
    parts = []
    if text:
        parts.append(types.Part.from_text(
            text="UNTRUSTED_CAPTION_BEGIN\n" + text[:8000] + "\nUNTRUSTED_CAPTION_END"))
    if image_bytes:
        mime = image_mime if image_mime in {
            "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
        } else "image/jpeg"
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime))
    try:
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model=gemini_model(),
            contents=parts,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=ExtractedOpportunity,
                system_instruction=EXTRACT_SYSTEM,
            ),
        )
    except Exception as e:
        raise ExtractionError(f"{type(e).__name__}: {e}") from e
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, ExtractedOpportunity):
        return parsed
    raw = getattr(resp, "text", "") or ""
    if not raw.strip():
        raise ExtractionError("empty model response")
    try:
        return ExtractedOpportunity.model_validate_json(raw)
    except Exception as e:
        raise ExtractionError(f"invalid model JSON: {e}") from e


def _safe_apply(method: str, target: str) -> tuple[str, str, str]:
    """Whitelist apply scheme. Returns method, apply_url, display target."""
    method = (method or "").strip().lower()
    target = (target or "").strip()
    if method == "whatsapp" or target.startswith("https://wa.me/") or whatsapp_url_kind(target) == "apply":
        phone = normalize_phone(target)
        if not phone and "wa.me/" in target:
            phone = normalize_phone(target.split("wa.me/", 1)[-1].split("?")[0])
        if phone:
            return "whatsapp", "https://wa.me/" + phone[1:], phone
    if method == "phone" or target.startswith("tel:"):
        phone = normalize_phone(target)
        if phone:
            return "phone", "tel:" + phone, phone
    if method == "email" or target.startswith("mailto:") or "@" in target:
        addr = target.replace("mailto:", "").strip()
        if re.match(r"[^@]+@[^@]+\.[^@]+", addr) and not addr.lower().startswith("javascript:"):
            return "email", "mailto:" + addr, addr
    if method == "web" or (target.startswith("https://") and is_apply_link(target)):
        if is_apply_link(target) and whatsapp_url_kind(target) not in ("channel", "post"):
            return "web", target, target
    return "", "", ""


def merge_extract(det: ExtractedOpportunity, gem: ExtractedOpportunity | None
                  ) -> ExtractedOpportunity:
    gem = gem or ExtractedOpportunity()
    method, url, target = _safe_apply(det.apply_method, det.apply_target)
    if not method:
        method, url, target = _safe_apply(gem.apply_method, gem.apply_target)
    title = clean_text(det.title or gem.title, 180)
    org = clean_text(det.organisation or gem.organisation, 90)
    loc = clean_text(det.location or gem.location, 90)
    role = clean_text(det.role or gem.role, 90)
    lang = clean_text(det.language or gem.language, 40)
    src = det.source_url or gem.source_url or ""
    if whatsapp_url_kind(src) == "channel":
        src = ""
    if src and not src.startswith("https://") and not src.startswith("http://"):
        src = ""
    deadline = det.deadline or gem.deadline or ""
    conf = max(float(det.title_confidence or 0), float(gem.title_confidence or 0))
    if title and not conf:
        conf = 0.7
    return ExtractedOpportunity(
        title=title,
        role=role,
        organisation=org,
        location=loc,
        language=lang,
        deadline=deadline,
        apply_method=method,
        apply_target=url or target,
        source_publisher=clean_text(det.source_publisher or gem.source_publisher, 80),
        source_url=src,
        title_confidence=conf,
        evidence=det.evidence or gem.evidence or "",
    )


def extract_fields(text: str = "", image_bytes: bytes | None = None,
                   image_mime: str = "") -> ExtractedOpportunity:
    det = deterministic_extract(text)
    gem = None
    if image_bytes:
        gem = gemini_extract(text, image_bytes, image_mime)
    elif gemini_api_key() and text.strip():
        try:
            gem = gemini_extract(text, None, "")
        except ExtractionError:
            gem = None
    return merge_extract(det, gem)


SHARED_SOURCE = dict(
    id="user_share",
    name="Community share",
    category="casting",
    credibility=1,
    publisher="Community share",
)


def default_expires_at(deadline: str = "", days: int | None = None) -> str:
    from .config import SHARE_EXPIRE_DAYS
    days = SHARE_EXPIRE_DAYS if days is None else days
    if deadline and len(deadline) >= 10:
        return deadline[:10]
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
