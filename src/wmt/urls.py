from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable
from urllib.parse import parse_qsl, urlsplit, urlunsplit


_DROP_QUERY_KEYS = {
    # Common analytics / trackers
    "gclid",
    "fbclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    # Misc tracking
    "ref",
    "ref_src",
    "spm",
}


def is_probably_http_url(url: str) -> bool:
    url = (url or "").strip().lower()
    return url.startswith("http://") or url.startswith("https://")


def _drop_tracking_params(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in pairs:
        key = k.strip()
        lowered = key.lower()
        if not lowered:
            continue
        if lowered.startswith("utm_"):
            continue
        if lowered in _DROP_QUERY_KEYS:
            continue
        out.append((key, v))
    return out


_YOUTUBE_HOST_RE = re.compile(r"(^|\.)youtube\.com$", re.IGNORECASE)


def _is_youtube_host(host: str) -> bool:
    host = (host or "").strip().lower()
    return host == "youtu.be" or bool(_YOUTUBE_HOST_RE.search(host))


def _canonicalize_youtube(url: str) -> str | None:
    """
    Produces a stable canonical URL for YouTube videos:
      https://www.youtube.com/watch?v=<VIDEO_ID>

    Drops time/playlist/etc so duplicates collapse.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if not _is_youtube_host(host):
        return None

    video_id: str | None = None
    if host == "youtu.be":
        path = parts.path.strip("/")
        if path:
            video_id = path.split("/")[0]
    else:
        if parts.path.rstrip("/") == "/watch":
            qs = dict(parse_qsl(parts.query, keep_blank_values=True))
            video_id = qs.get("v") or None
        elif parts.path.startswith("/shorts/"):
            video_id = parts.path.split("/")[2] if len(parts.path.split("/")) > 2 else None

    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    yt = _canonicalize_youtube(url)
    if yt:
        return yt

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc

    # Lowercase host, keep userinfo/port as-is unless it's a default port.
    host = (parts.hostname or "").lower()
    port = parts.port
    userinfo = ""
    if "@" in netloc:
        userinfo = netloc.split("@", 1)[0] + "@"
    if port is None:
        netloc = f"{userinfo}{host}"
    else:
        if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
            netloc = f"{userinfo}{host}"
        else:
            netloc = f"{userinfo}{host}:{port}"

    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")

    query_pairs = _drop_tracking_params(parse_qsl(parts.query, keep_blank_values=True))
    query_pairs.sort(key=lambda kv: (kv[0].lower(), kv[1]))
    query = "&".join(f"{k}={v}" for k, v in query_pairs) if query_pairs else ""

    # Drop fragments entirely (often just scroll position / trackers).
    fragment = ""

    return urlunsplit((scheme, netloc, path, query, fragment))


@dataclass(frozen=True)
class LinkIdentity:
    normalized_url: str
    sha256: str


def link_identity(url: str) -> LinkIdentity:
    normalized = normalize_url(url)
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    return LinkIdentity(normalized_url=normalized, sha256=digest)
