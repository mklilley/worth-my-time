from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublishResult:
    publisher: str
    ok: bool
    url: str | None = None
    note_id: str | None = None
    error: str | None = None

