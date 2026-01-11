from __future__ import annotations

import importlib.metadata
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

log = logging.getLogger(__name__)


class YouTubeTranscriptError(RuntimeError):
    pass


@dataclass(frozen=True)
class YouTubeTranscript:
    text: str
    source: str
    language: str | None
    is_auto: bool | None
    notes: tuple[str, ...] = ()


def is_youtube_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "youtu.be" or host.endswith(".youtube.com") or host == "youtube.com"


def youtube_video_id(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()

    if host == "youtu.be":
        path = parts.path.strip("/")
        return path.split("/")[0] if path else None

    if host.endswith("youtube.com") or host == "youtube.com":
        if parts.path.rstrip("/") == "/watch":
            qs = parse_qs(parts.query)
            v = qs.get("v")
            if v and v[0]:
                return v[0]
        if parts.path.startswith("/shorts/"):
            segs = [s for s in parts.path.split("/") if s]
            if len(segs) >= 2:
                return segs[1]

    return None


def _vtt_to_text(vtt: str) -> str:
    """
    Very small WebVTT parser: keeps timestamps and text.
    """
    out: list[str] = []
    for line in vtt.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith("WEBVTT"):
            continue
        if "-->" in stripped:
            # Timestamp cue line.
            out.append(f"[{stripped}]")
            continue
        if stripped.startswith("NOTE"):
            continue
        if stripped.isdigit():
            continue
        out.append(stripped)
    text = "\n".join(out).strip()
    return text


def _srt_to_text(srt: str) -> str:
    out: list[str] = []
    for line in srt.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.isdigit():
            continue
        if "-->" in stripped:
            out.append(f"[{stripped}]")
            continue
        out.append(stripped)
    return "\n".join(out).strip()


def _try_youtube_transcript_api(video_id: str) -> YouTubeTranscript | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import-not-found]
    except Exception as e:
        # This is declared as a dependency in pyproject.toml, but keep this resilient in case
        # a user runs from source without installing deps.
        log.warning("youtube-transcript-api is not available: %s", e)
        return None

    # Best-effort: prefer English variants, fall back to whatever's available.
    preferred_langs = ["en", "en-US", "en-GB"]
    try:
        # youtube-transcript-api v1+ uses an instance API with `fetch()` returning a FetchedTranscript.
        # Older versions used classmethods like `get_transcript` / `list_transcripts`.
        if hasattr(YouTubeTranscriptApi, "__call__") or isinstance(YouTubeTranscriptApi, type):
            api = YouTubeTranscriptApi()  # type: ignore[call-arg]
        else:
            api = YouTubeTranscriptApi  # type: ignore[assignment]

        # v1+: api.fetch(video_id, languages=[...]) -> iterable of snippets with .text/.start
        if hasattr(api, "fetch"):
            fetched = api.fetch(video_id, languages=preferred_langs)  # type: ignore[attr-defined]
            segments = []
            for snippet in fetched:
                segments.append({"text": getattr(snippet, "text", ""), "start": getattr(snippet, "start", 0.0)})
            language = getattr(fetched, "language_code", None) or getattr(fetched, "language", None)
            is_auto = bool(getattr(fetched, "is_generated", False))
        # Older: classmethod get_transcript(video_id, languages=...) -> list[dict]
        elif hasattr(YouTubeTranscriptApi, "get_transcript"):
            try:
                segments = YouTubeTranscriptApi.get_transcript(video_id, languages=preferred_langs)  # type: ignore[attr-defined]
            except Exception:
                segments = YouTubeTranscriptApi.get_transcript(video_id)  # type: ignore[attr-defined]
            language = None
            is_auto = None
        else:
            raise YouTubeTranscriptError(
                "youtube-transcript-api API mismatch (expected .fetch() or .get_transcript())"
            )

        lines: list[str] = []
        for seg in segments:
            start = float(seg.get("start", 0.0))
            minutes = int(start // 60)
            seconds = int(start % 60)
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            lines.append(f"[{minutes:02d}:{seconds:02d}] {text}")

        text = "\n".join(lines).strip()
        if not text:
            return None
        return YouTubeTranscript(
            text=text,
            source="youtube-transcript-api",
            language=language,
            is_auto=is_auto,
        )
    except Exception as e:
        try:
            ver = importlib.metadata.version("youtube-transcript-api")
        except Exception:
            ver = "unknown"
        log.warning(
            "youtube-transcript-api failed for %s (v=%s, %s): %s",
            video_id,
            ver,
            type(e).__name__,
            e,
        )
        return None


def _pick_sub_file(files: list[Path]) -> Path | None:
    if not files:
        return None

    def score(p: Path) -> tuple[int, int]:
        name = p.name.lower()
        is_auto = 1 if "auto" in name else 0
        is_en = 0 if ".en" in name else 1
        return (is_auto, is_en)

    files.sort(key=score)
    return files[0]


def _yt_dlp_base_cmd() -> list[str] | None:
    """
    Prefer `python -m yt_dlp` so a pip-installed package works without Homebrew/system installs.
    Fall back to `yt-dlp` if available.
    """
    candidates: list[list[str]] = [
        [sys.executable, "-m", "yt_dlp"],
        ["yt-dlp"],
    ]
    for base in candidates:
        try:
            subprocess.run(base + ["--version"], capture_output=True, text=True, check=True)
            return base
        except Exception:
            continue
    return None


def _try_yt_dlp(url: str) -> YouTubeTranscript | None:
    """
    Uses `yt-dlp` if installed to fetch subtitles (manual or auto) and convert to text.
    """
    base = _yt_dlp_base_cmd()
    if not base:
        return None

    with tempfile.TemporaryDirectory(prefix="wmt_yt_") as td:
        tmp = Path(td)
        out_tmpl = str(tmp / "%(id)s.%(ext)s")
        cmd = base + [
            "--skip-download",
            "--no-warnings",
            "--write-subs",
            "--write-auto-subs",
            "--sub-format",
            "vtt/srt",
            "--sub-langs",
            "en.*,en",
            "-o",
            out_tmpl,
            url,
        ]
        log.info("Fetching YouTube subtitles via yt-dlp")
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
        except subprocess.TimeoutExpired:
            log.info("yt-dlp timed out fetching subtitles")
            return None
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            stdout = (e.stdout or "").strip()
            detail = stderr or stdout or f"exit {e.returncode}"
            log.info("yt-dlp failed: %s", detail)
            return None

        vtts = list(tmp.glob("*.vtt"))
        srts = list(tmp.glob("*.srt"))
        picked = _pick_sub_file(vtts) or _pick_sub_file(srts)
        if not picked:
            return None

        text_raw = picked.read_text(encoding="utf-8", errors="replace")
        if picked.suffix.lower() == ".vtt":
            text = _vtt_to_text(text_raw)
        else:
            text = _srt_to_text(text_raw)

        if not text.strip():
            return None

        name = picked.name.lower()
        is_auto = True if "auto" in name else None
        lang = None
        for part in picked.stem.split("."):
            if part.lower().startswith("en"):
                lang = part
                break
        return YouTubeTranscript(
            text=text.strip(),
            source="yt-dlp",
            language=lang,
            is_auto=is_auto,
        )


def get_youtube_transcript(url: str) -> YouTubeTranscript | None:
    video_id = youtube_video_id(url)
    if not video_id:
        return None

    from_api = _try_youtube_transcript_api(video_id)
    if from_api and from_api.text.strip():
        return from_api

    from_ytdlp = _try_yt_dlp(url)
    if from_ytdlp and from_ytdlp.text.strip():
        return from_ytdlp

    return None
