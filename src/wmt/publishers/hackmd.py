from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from wmt.config import HackMDConfig
from wmt.publishers.base import PublishResult

log = logging.getLogger(__name__)


class HackMDError(RuntimeError):
    pass


@dataclass(frozen=True)
class HackMDNote:
    note_id: str | None
    url: str | None
    raw: dict[str, Any]


def _extract_note_url(data: dict[str, Any]) -> str | None:
    # HackMD APIs have varied historically; try the common fields.
    for key in ("publishLink", "permalink", "link", "url"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def create_note(cfg: HackMDConfig, *, content: str) -> HackMDNote:
    if not cfg.api_token:
        raise HackMDError("HackMD api_token is empty")
    if not cfg.parent_folder_id:
        raise HackMDError("HackMD parent_folder_id is empty")

    url = cfg.api_base_url.rstrip("/") + "/notes"
    payload = {"parentFolderId": cfg.parent_folder_id, "content": content}
    body = json.dumps(payload).encode("utf-8")

    req = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(req, timeout=cfg.timeout_seconds) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace").strip()
            data = json.loads(text) if text else {}
            if not isinstance(data, dict):
                raise HackMDError("HackMD response was not a JSON object")
            note_id = data.get("id")
            note_id = note_id.strip() if isinstance(note_id, str) else None
            note_url = _extract_note_url(data)
            return HackMDNote(note_id=note_id, url=note_url, raw=data)
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        raise HackMDError(f"HTTP {e.code}: {detail or e.reason}") from e
    except URLError as e:
        raise HackMDError(str(getattr(e, "reason", e))) from e


def publish_markdown(cfg: HackMDConfig, *, markdown: str) -> PublishResult:
    """
    Publish markdown to HackMD as a new note in the configured parent folder.

    HackMD uses the first H1 (`# ...`) in the content as the note title if `title` is not provided.
    """
    try:
        note = create_note(cfg, content=markdown)
        if note.url:
            log.info("HackMD note created: %s", note.url)
        else:
            log.info("HackMD note created (no URL in response)")
        return PublishResult(publisher="hackmd", ok=True, url=note.url, note_id=note.note_id)
    except HackMDError as e:
        return PublishResult(publisher="hackmd", ok=False, error=str(e))

