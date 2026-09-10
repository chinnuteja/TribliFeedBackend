"""Push intake for WhatsApp / phone shares. Not a scheduled scraper."""
from __future__ import annotations
import datetime
import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

from . import db
from .config import DATA_DIR
from .filters import (
    assess_user_share, clean_text, deadline_current, extract_http_urls,
    is_apply_link, is_injection, is_permalink, region_tier, share_relevant,
    whatsapp_url_kind, build_item,
)
from .shared_opportunity import (
    SHARED_SOURCE, ExtractionError, default_expires_at, extract_fields,
)
from . import enrich

ALLOWED_IMAGE = {
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
}
_PHONE_RE = re.compile(r"(?:\+91[\s-]*)?[6-9](?:[\s-]?\d){9}")


class ShareRejected(Exception):
    def __init__(self, status, reasons, item_id=""):
        self.status = status
        self.reasons = reasons
        self.item_id = item_id
        super().__init__(status)


def mask_contact(value: str) -> str:
    s = value or ""
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 10:
        return "+•••" + digits[-2:]
    if "@" in s:
        name, _, host = s.partition("@")
        return (name[:1] or "•") + "••@" + host
    if s.startswith("http"):
        host = urlparse(s).netloc
        return host or "•" * 3
    return "•••"


def _sanitize_blob(text: str) -> str:
    t = clean_text(text, 2000)
    t = _PHONE_RE.sub(lambda m: mask_contact(m.group(0)), t)
    return t


def payload_hash(text: str, url: str, image_bytes: bytes | None) -> str:
    h = hashlib.sha256()
    h.update(clean_text(text, 4000).encode("utf-8"))
    h.update((url or "").strip().encode("utf-8"))
    if image_bytes:
        h.update(hashlib.sha256(image_bytes).digest())
    return h.hexdigest()


def _forget_upload(path: Path | None):
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as e:
        raise RuntimeError(f"could not delete upload {path}: {e}") from e


def _store_temp(image_bytes: bytes, mime: str) -> Path:
    folder = Path(DATA_DIR) / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    ext = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/heic": ".heic", "image/heif": ".heif",
    }.get(mime, ".bin")
    name = hashlib.sha256(image_bytes).hexdigest()[:16] + ext
    path = folder / name
    path.write_bytes(image_bytes)
    return path


def _source_domain(url: str) -> str:
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _cta_link(apply_method: str, apply_url: str, source_url: str) -> str:
    if apply_url:
        return apply_url
    return source_url


def process_share(text: str = "", url: str = "", image_bytes: bytes | None = None,
                  image_mime: str = "", submitted_by: str = "",
                  transport: str = "paste", title: str = "",
                  user_agent: str = "") -> dict:
    """Run extraction + gates. Always records a submission. Never stores images."""
    tmp = None
    reasons: list[str] = []
    model_name = ""
    shape = {
        "has_text": bool((text or "").strip()),
        "has_url": bool((url or "").strip()),
        "has_image": bool(image_bytes),
        "image_mime": image_mime or "",
        "file_count": 1 if image_bytes else 0,
        "text_len": len(text or ""),
        "title_len": len(title or ""),
        "ua": (user_agent or "")[:80],
        "transport": transport,
    }
    blob = "\n".join(x for x in (title, text, url) if x).strip()
    phash = payload_hash(blob, url, image_bytes)

    def finish(status, extra_reasons=None, item_id=""):
        all_reasons = reasons + (extra_reasons or [])
        db.record_submission(
            payload_hash=phash, status=status,
            sanitized_text=_sanitize_blob(blob),
            model=model_name, reasons=all_reasons, item_id=item_id,
            submitted_by=submitted_by, transport=transport,
            payload_shape=shape,
        )
        return {"status": status, "id": item_id or None, "reasons": all_reasons}

    try:
        if image_bytes:
            tmp = _store_temp(image_bytes, image_mime or "application/octet-stream")

        if is_injection(title, text, url):
            return finish("rejected", ["payload looks like script injection"])

        urls = extract_http_urls(blob)
        if url:
            urls = [url] + [u for u in urls if u != url]
        channel_only = False
        post_url = ""
        page_url = ""
        for u in urls:
            kind = whatsapp_url_kind(u)
            if kind == "channel":
                channel_only = True
            elif kind == "post":
                post_url = post_url or u
                channel_only = False
            elif kind == "apply":
                channel_only = False
            elif u.lower().startswith(("http://", "https://")):
                page_url = page_url or u
                channel_only = False
        shape["url_kind"] = (
            "post" if post_url else
            "channel" if channel_only else
            "http" if page_url else ""
        )
        if channel_only and not post_url:
            maybe = clean_text(blob[:180], 180)
            if (not maybe or maybe.lower().startswith("http")
                    or not share_relevant(maybe, blob)):
                return finish("rejected", [
                    "A WhatsApp channel invite is not evidence of a specific call."
                ])

        extracted = None
        try:
            extracted = extract_fields(blob, image_bytes, image_mime)
            if image_bytes:
                model_name = "gemini"
        except ExtractionError as e:
            if image_bytes and not (text or "").strip():
                return finish("extraction_error", [str(e)])
            from .shared_opportunity import deterministic_extract, merge_extract
            extracted = merge_extract(deterministic_extract(blob), None)
            reasons.append(f"model unavailable; used caption parse ({type(e).__name__})")

        opp_title = clean_text(extracted.title or title, 180)
        description = clean_text(blob, 420)
        org = clean_text(extracted.organisation, 90)
        location = clean_text(extracted.location, 90)
        apply_method = extracted.apply_method
        apply_url = extracted.apply_target
        if apply_method and apply_url and not is_apply_link(apply_url) and not apply_url.startswith(("mailto:", "tel:")):
            apply_method, apply_url = "", ""
        source_url = extracted.source_url or post_url or ""
        if source_url and whatsapp_url_kind(source_url) == "channel":
            source_url = ""
        if page_url and is_permalink(page_url):
            source_url = source_url or page_url

        post_needs_details = bool(post_url) and (
            not opp_title or not share_relevant(opp_title, description)
        )
        if post_needs_details:
            # Android's WhatsApp share sheet can send only the Channel message
            # permalink, without the visible caption/poster. The teammate's
            # explicit share is still a useful lead, but the URL proves no
            # casting facts and must never become an Apply action by itself.
            opp_title = "Team-shared WhatsApp post"
            apply_method, apply_url = "", ""
            reasons.append(
                "WhatsApp did not include enough post details; saved for team review."
            )
        elif not opp_title or not share_relevant(opp_title, description):
            return finish("rejected", ["not a specific casting or crew opportunity"])

        if extracted.title_confidence and extracted.title_confidence < 0.55:
            reasons.append("low extraction confidence")

        deadline = (extracted.deadline or "")[:10]
        if deadline and not deadline_current(deadline):
            return finish("rejected", ["stated deadline has already passed"])

        # Human shares are trusted as signals, not as automatic proof. Run the
        # hard safety gates before deciding whether a missing contact route is
        # an incomplete post or something we must reject outright.
        trust, trust_reasons, _ = assess_user_share(
            opp_title, description, org, apply_method=apply_method)
        if trust == "blocked":
            return finish("rejected", trust_reasons)

        display_mode = "full"
        verified_at = ""
        enrich_status = ""
        fetch_url = ""
        if apply_method == "web":
            fetch_url = apply_url
        elif page_url and is_permalink(page_url) and apply_method != "whatsapp":
            fetch_url = page_url
        if fetch_url and whatsapp_url_kind(fetch_url):
            fetch_url = ""
        if fetch_url:
            meta = enrich.enrich_url(fetch_url)
            enrich_status = meta.get("status") or ""
            db.record_shared_domain(_source_domain(fetch_url),
                                    meta.get("format") or "", enrich_status)
            if enrich_status == "ok":
                org = org or clean_text(meta.get("org"), 90)
                location = location or ""
                if meta.get("deadline") and not deadline:
                    deadline = str(meta["deadline"])[:10]
                if meta.get("canonical") and is_permalink(meta["canonical"]):
                    source_url = meta["canonical"]
                    apply_url = apply_url or source_url
                    apply_method = apply_method or "web"
                display_mode = "redirect" if apply_method == "web" else display_mode
            elif enrich_status in ("blocked", "login", "error"):
                # Caption already has a specific call + exact URL.
                if is_permalink(fetch_url) and share_relevant(opp_title, description):
                    display_mode = "redirect"
                    apply_method = apply_method or "web"
                    apply_url = apply_url or fetch_url
                    source_url = source_url or fetch_url
                    verified_at = ""
                    reasons.append(
                        f"publisher page {enrich_status}; card uses the shared URL, "
                        "not a scraped body"
                    )
                else:
                    return finish("rejected", [
                        f"could not confirm the listing ({enrich_status})"
                    ])
            elif enrich_status == "rejected":
                # A teammate may have shared a real call before they have its
                # precise application link. Keep the signal, but never turn a
                # homepage/directory into an apply CTA.
                reasons.append(meta.get("reason") or
                               "shared URL is not a specific application page")
                if apply_method == "web":
                    apply_method, apply_url = "", ""
                if page_url == fetch_url:
                    source_url = ""

        if not apply_method or not apply_url:
            # Do not throw away a relevant team share merely because a caption
            # lacks a direct URL, number, or email. It appears in the feed as
            # "Needs details" for seven days, with no misleading apply button.
            # The person who shared it can add contact details in a follow-up.
            # A human share is a useful lead, but an unlabelled personal-DM
            # request is not a safe team card. It stays out of the feed until
            # a human provides a verifiable application route.
            if trust == "quarantine" or any(
                "off-platform to a personal number" in reason.lower()
                for reason in trust_reasons
            ):
                return finish("quarantined", trust_reasons or reasons)
            expires_at = default_expires_at(deadline)
            source_link = source_url if source_url and (
                is_permalink(source_url) or whatsapp_url_kind(source_url) == "post"
            ) else ""
            item = build_item(
                {**SHARED_SOURCE, "publisher": "TRIBLI Team",
                 "url": source_link},
                kind="opportunity",
                title=opp_title,
                link=source_link,
                display_mode="full",
                verified_at="",
                description=description,
                org=org,
                location=location or "India",
                region_tier=region_tier(opp_title, description, location, extracted.language),
                employment_type=clean_text(extracted.role, 80) or "Contact details needed",
                posted_at=datetime.date.today().isoformat(),
                deadline=deadline,
                trust="caution" if trust == "caution" or reasons else trust,
                trust_reasons=trust_reasons + reasons + [
                    "No direct contact was included. Ask the teammate who shared this post."
                ],
                acquisition_mode="shared",
                apply_method="team_review",
                apply_url="",
                expires_at=expires_at,
                submitted_at=datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                source_domain=_source_domain(source_link),
                extract_confidence=float(extracted.title_confidence or 0),
                extract_evidence={"evidence": extracted.evidence},
                raw={"transport": transport, "shape": shape},
            )
            db.upsert_items([item])
            return finish("needs_details", trust_reasons + reasons + [
                "Saved for the team; add a direct contact before applying."
            ], item_id=item["id"])

        link = source_url or apply_url
        if not link:
            return finish("rejected", ["no outbound link"])
        if apply_method == "web" and not is_permalink(apply_url) and not is_apply_link(apply_url):
            return finish("rejected", ["apply URL is a homepage or directory, not a post"])

        if display_mode != "redirect" and apply_method == "web":
            display_mode = "redirect"

        expires_at = default_expires_at(deadline)
        if not deadline:
            # operational expiry only — do not present as publisher deadline
            pass

        publisher = "TRIBLI Team"
        domain = _source_domain(source_url or (apply_url if apply_method == "web" else ""))
        item = build_item(
            {**SHARED_SOURCE, "publisher": publisher,
             "url": source_url or apply_url},
            kind="opportunity",
            title=opp_title,
            link=link,
            display_mode=display_mode,
            verified_at=verified_at,
            description=description,
            org=org,
            location=location or "India",
            region_tier=region_tier(opp_title, description, location, extracted.language),
            employment_type=clean_text(extracted.role, 80),
            posted_at=datetime.date.today().isoformat(),
            deadline=deadline,
            trust=trust,
            trust_reasons=trust_reasons,
            acquisition_mode="shared",
            apply_method=apply_method,
            apply_url=apply_url,
            expires_at=expires_at,
            submitted_at=datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            source_domain=domain,
            extract_confidence=float(extracted.title_confidence or 0),
            extract_evidence={"evidence": extracted.evidence},
            raw={"transport": transport, "shape": shape},
        )

        dup = db.find_share_duplicate(link=link, apply_url=apply_url, title=opp_title)
        if dup:
            item["id"] = dup["id"]
            db.upsert_items([item])
            return finish("duplicate", ["already in the feed; refreshed"], item_id=dup["id"])

        if trust == "quarantine" or (extracted.title_confidence and extracted.title_confidence < 0.55):
            item["trust"] = "quarantine"
            db.upsert_items([item])
            return finish("quarantined", trust_reasons or reasons, item_id=item["id"])

        db.upsert_items([item])
        return finish("published", trust_reasons, item_id=item["id"])
    finally:
        _forget_upload(tmp)
