from __future__ import annotations

import gzip
import logging
import re
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)


class FetchError(RuntimeError):
    pass


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str | None
    ok: bool
    status: int | None
    content_type: str | None
    content_encoding: str | None
    bytes_read: int
    truncated: bool
    text: str | None
    error: str | None


def _decode_body(body: bytes, *, content_type: str | None) -> str:
    charset: str | None = None
    if content_type:
        m = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, flags=re.IGNORECASE)
        if m:
            charset = m.group(1).strip()

    if charset:
        try:
            return body.decode(charset, errors="replace")
        except LookupError:
            pass
        except UnicodeDecodeError:
            pass

    # Light-touch HTML meta charset sniff.
    head = body[:4096].decode("utf-8", errors="ignore")
    m = re.search(r'(?i)<meta[^>]+charset=["\']?([A-Za-z0-9._-]+)', head)
    if m:
        guessed = m.group(1).strip()
        try:
            return body.decode(guessed, errors="replace")
        except Exception:
            pass

    return body.decode("utf-8", errors="replace")


def fetch_url(
    url: str,
    *,
    timeout_seconds: int = 20,
    max_bytes: int = 2_000_000,
) -> FetchResult:
    url = url.strip()
    if not url:
        raise FetchError("Empty URL")

    req = Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        },
    )

    body: bytes = b""
    status: int | None = None
    final_url: str | None = None
    content_type: str | None = None
    content_encoding: str | None = None
    truncated = False

    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            status = getattr(resp, "status", None)
            final_url = getattr(resp, "url", None)
            content_type = resp.headers.get("Content-Type")
            content_encoding = resp.headers.get("Content-Encoding")
            body = resp.read(max_bytes + 1)
            if len(body) > max_bytes:
                body = body[:max_bytes]
                truncated = True
    except HTTPError as e:
        status = getattr(e, "code", None)
        final_url = getattr(e, "url", None)
        content_type = e.headers.get("Content-Type") if e.headers else None
        content_encoding = e.headers.get("Content-Encoding") if e.headers else None
        try:
            body = e.read(max_bytes + 1)
            if len(body) > max_bytes:
                body = body[:max_bytes]
                truncated = True
        except Exception:
            body = b""
        error = (str(e) or f"HTTP {status}").strip()
        text = None
        if body:
            try:
                body = _maybe_decompress(body, content_encoding=content_encoding)
                text = _decode_body(body, content_type=content_type)
            except Exception:
                text = None
        return FetchResult(
            url=url,
            final_url=final_url,
            ok=False,
            status=status,
            content_type=content_type,
            content_encoding=content_encoding,
            bytes_read=len(body),
            truncated=truncated,
            text=text,
            error=error,
        )
    except URLError as e:
        return FetchResult(
            url=url,
            final_url=None,
            ok=False,
            status=None,
            content_type=None,
            content_encoding=None,
            bytes_read=0,
            truncated=False,
            text=None,
            error=str(e.reason) if getattr(e, "reason", None) else str(e),
        )

    body = _maybe_decompress(body, content_encoding=content_encoding)
    text = _decode_body(body, content_type=content_type) if body else ""
    ok = bool(status and 200 <= int(status) < 400)
    return FetchResult(
        url=url,
        final_url=final_url,
        ok=ok,
        status=status,
        content_type=content_type,
        content_encoding=content_encoding,
        bytes_read=len(body),
        truncated=truncated,
        text=text,
        error=None if ok else f"HTTP {status}",
    )


def _maybe_decompress(body: bytes, *, content_encoding: str | None) -> bytes:
    enc = (content_encoding or "").strip().lower()
    if not enc:
        return body
    if enc == "gzip":
        try:
            return gzip.decompress(body)
        except Exception:
            return body
    if enc == "deflate":
        try:
            return zlib.decompress(body)
        except Exception:
            try:
                return zlib.decompress(body, -zlib.MAX_WBITS)
            except Exception:
                return body
    return body


@dataclass(frozen=True)
class ExtractedPage:
    title: str | None
    text: str


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._in_ignored = 0
        self._in_title = False
        self._title_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"}:
            self._in_ignored += 1
            return
        if lowered == "title":
            self._in_title = True
            return
        if lowered in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"}:
            self._in_ignored = max(0, self._in_ignored - 1)
            return
        if lowered == "title":
            self._in_title = False
            return
        if lowered in {"p", "div", "li"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_ignored:
            return
        if self._in_title:
            self._title_chunks.append(data)
            return
        if data and data.strip():
            self._chunks.append(data)

    def title(self) -> str | None:
        t = " ".join(" ".join(self._title_chunks).split()).strip()
        return t or None

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        # Collapse whitespace but keep paragraph-ish newlines.
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def extract_text_from_html(html: str) -> ExtractedPage:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Even very broken HTML should still yield something via best-effort fallback.
        pass
    return ExtractedPage(title=parser.title(), text=parser.text())


def summarize_fetch_for_prompt(result: FetchResult) -> str:
    """
    Small, factual access report we can embed into the prompt (so the LLM doesn't bluff).
    """
    parts: list[str] = ["ACCESS REPORT (from this script):"]
    parts.append(f"- Requested: {result.url}")
    if result.final_url and result.final_url != result.url:
        parts.append(f"- Final URL: {result.final_url}")
    if result.status is not None:
        parts.append(f"- HTTP status: {result.status}")
    if result.content_type:
        parts.append(f"- Content-Type: {result.content_type}")
    if result.content_encoding:
        parts.append(f"- Content-Encoding: {result.content_encoding}")
    parts.append(f"- Bytes read: {result.bytes_read}{' (truncated)' if result.truncated else ''}")
    parts.append(f"- Fetch ok: {result.ok}")
    if result.error:
        parts.append(f"- Error: {result.error}")
    return "\n".join(parts).strip()
