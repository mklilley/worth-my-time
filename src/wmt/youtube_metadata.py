from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from wmt.fetch import fetch_url
from wmt.youtube_transcripts import is_youtube_url

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class YouTubeMetadata:
    title: str | None
    channel: str | None
    channel_url: str | None
    upload_date: str | None  # YYYY-MM-DD if known
    duration_seconds: int | None
    source: str
    notes: tuple[str, ...] = ()


def _parse_upload_date(value: str | None) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    # yt-dlp uses YYYYMMDD.
    if len(v) == 8 and v.isdigit():
        try:
            dt = datetime.strptime(v, "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
    return None


def _try_oembed(url: str, *, timeout_seconds: int) -> tuple[dict[str, object] | None, str | None]:
    endpoint = "https://www.youtube.com/oembed?" + urlencode({"format": "json", "url": url})
    res = fetch_url(endpoint, timeout_seconds=timeout_seconds, max_bytes=200_000)
    if not res.ok or not res.text:
        detail = res.error or f"HTTP {res.status}" if res.status else "unknown error"
        return None, detail
    try:
        data = json.loads(res.text)
    except Exception as e:
        return None, f"invalid json: {type(e).__name__}: {e}"
    if not isinstance(data, dict):
        return None, "unexpected oEmbed payload"
    return data, None


def _try_yt_dlp_json(url: str, *, timeout_seconds: int) -> tuple[dict[str, object] | None, str | None]:
    candidates: list[list[str]] = [
        [sys.executable, "-m", "yt_dlp"],
        ["yt-dlp"],
    ]
    base: list[str] | None = None
    for c in candidates:
        try:
            subprocess.run(c + ["--version"], capture_output=True, text=True, check=True)
            base = c
            break
        except Exception:
            continue

    if base is None:
        return None, "yt-dlp not installed"

    cmd = base + [
        "--dump-json",
        "--skip-download",
        "--no-warnings",
        "--no-playlist",
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=max(5, timeout_seconds),
        )
    except subprocess.TimeoutExpired:
        return None, "yt-dlp timed out"
    except subprocess.CalledProcessError as e:
        detail = ((e.stderr or "").strip() or (e.stdout or "").strip() or f"exit {e.returncode}").strip()
        return None, f"yt-dlp failed: {detail}"

    stdout = (proc.stdout or "").strip()
    if not stdout:
        return None, "yt-dlp returned empty output"
    # yt-dlp should return a single JSON object for a single video; be defensive anyway.
    first_line = stdout.splitlines()[0].strip()
    try:
        data = json.loads(first_line)
    except Exception as e:
        return None, f"invalid yt-dlp json: {type(e).__name__}: {e}"
    if not isinstance(data, dict):
        return None, "unexpected yt-dlp payload"
    return data, None


def get_youtube_metadata(url: str, *, timeout_seconds: int = 20) -> YouTubeMetadata | None:
    """
    Best-effort YouTube metadata retrieval without API keys.

    - First tries YouTube oEmbed (title + channel).
    - Optionally enriches with `yt-dlp` (duration + upload date) if installed.
    """
    if not is_youtube_url(url):
        return None

    notes: list[str] = []
    title: str | None = None
    channel: str | None = None
    channel_url: str | None = None
    upload_date: str | None = None
    duration_seconds: int | None = None
    sources: list[str] = []

    oembed, oembed_err = _try_oembed(url, timeout_seconds=timeout_seconds)
    if oembed:
        sources.append("oembed")
        title = str(oembed.get("title") or "").strip() or title
        channel = str(oembed.get("author_name") or "").strip() or channel
        channel_url = str(oembed.get("author_url") or "").strip() or channel_url
    elif oembed_err:
        notes.append(f"oEmbed unavailable: {oembed_err}")

    ytdlp, ytdlp_err = _try_yt_dlp_json(url, timeout_seconds=timeout_seconds)
    if ytdlp:
        sources.append("yt-dlp")
        title = str(ytdlp.get("title") or "").strip() or title
        channel = (
            str(ytdlp.get("uploader") or "").strip()
            or str(ytdlp.get("channel") or "").strip()
            or channel
        )
        channel_url = (
            str(ytdlp.get("uploader_url") or "").strip()
            or str(ytdlp.get("channel_url") or "").strip()
            or channel_url
        )
        try:
            dur = ytdlp.get("duration")
            duration_seconds = int(dur) if dur is not None else duration_seconds
        except Exception:
            pass
        upload_date = _parse_upload_date(str(ytdlp.get("upload_date") or "")) or upload_date
    elif ytdlp_err and ytdlp_err != "yt-dlp not installed":
        notes.append(ytdlp_err)

    if not any([title, channel, channel_url, upload_date, duration_seconds]):
        log.info("YouTube metadata unavailable for %s (%s)", url, "; ".join(notes) if notes else "no details")
        return None

    meta = YouTubeMetadata(
        title=title,
        channel=channel,
        channel_url=channel_url,
        upload_date=upload_date,
        duration_seconds=duration_seconds,
        source="+".join(sources) if sources else "unknown",
        notes=tuple(notes),
    )
    log.info(
        "Retrieved YouTube metadata via %s (title=%s, channel=%s)",
        meta.source,
        (meta.title or "").strip()[:80] or "unknown",
        (meta.channel or "").strip()[:80] or "unknown",
    )
    return meta
