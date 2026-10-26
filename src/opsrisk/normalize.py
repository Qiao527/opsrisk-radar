"""Text and URL normalization applied once, at ingestion.

Everything downstream (storage, deduplication, scoring, reports) sees the
cleaned values, so feed quirks are handled here and nowhere else.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_RE_TAGS = re.compile(r"<[^>]+>")
_RE_WS = re.compile(r"\s+")
# WordPress feeds append "The post <title> appeared first on <site>." to every
# summary; it carries no information and pollutes keyword matching.
_RE_WP_FOOTER = re.compile(r"\s*The post .{0,300}? appeared first on .{1,120}?\s*\.?\s*$", re.S)
_RE_READ_MORE = re.compile(r"(\[\s*(…|\.\.\.)\s*\]|(…|\.\.\.)\s*Read More\b|\bRead More\b)", re.I)

# Query parameters that identify a campaign or click, not the content.
_TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid|ref|cmpid|_hsenc|_hsmi)$", re.I)

SUMMARY_MAX_CHARS = 1000


def clean_text(raw: str | None, max_chars: int | None = None) -> str:
    """Strip markup, decode entities, drop feed boilerplate, collapse whitespace."""
    text = raw or ""
    # Unescape twice: some feeds double-encode (``&amp;#8230;``).
    text = html.unescape(html.unescape(text))
    text = _RE_TAGS.sub(" ", text)
    text = unicodedata.normalize("NFKC", text)
    text = _RE_WS.sub(" ", text).strip()
    text = _RE_WP_FOOTER.sub("", text)
    text = _RE_READ_MORE.sub("", text)
    text = _RE_WS.sub(" ", text).strip()
    if max_chars is not None and len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def canonical_url(url: str) -> str:
    """A stable identity for an article URL.

    Lowercases scheme and host, drops default ports, fragments and tracking
    parameters, sorts the remaining query and removes a trailing slash.
    ``http`` and ``https`` are treated as the same article.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING_PARAMS.match(k)
    )
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit(("https", netloc, path, urlencode(query), ""))


_STOPWORDS = frozenset(
    "a an and as at by for from in into is of on or the to with after amid over new".split()
)
_RE_WORD = re.compile(r"[a-z0-9]+")


def title_tokens(title: str) -> frozenset[str]:
    """Content words of a title, used for near-duplicate detection."""
    words = _RE_WORD.findall(unicodedata.normalize("NFKC", title).lower())
    return frozenset(w for w in words if w not in _STOPWORDS)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def content_hash(title: str, summary: str) -> str:
    """Hash of the normalized text a scorer sees; changes trigger rescoring."""
    payload = f"{title.strip()}\n{summary.strip()}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def to_utc_naive(dt: datetime | None) -> datetime | None:
    """Convert to UTC and drop tzinfo, the storage convention for every timestamp.

    A naive input is assumed to already be UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0)


def utc_iso(dt: datetime | None) -> str | None:
    dt = to_utc_naive(dt)
    return dt.isoformat() if dt else None
