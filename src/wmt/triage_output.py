from __future__ import annotations

import re
import tempfile
from datetime import datetime
from pathlib import Path


def _slugify(value: str, *, max_len: int = 80) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"['’]", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    if not value:
        value = "untitled"
    return value[:max_len].strip("-") or "untitled"


def triage_output_filename(
    *,
    title: str | None,
    added_at: datetime | None,
    short_id: str,
) -> str:
    date_prefix = (added_at or datetime.now()).strftime("%Y-%m-%d")
    slug = _slugify(title or "")
    short = re.sub(r"[^a-fA-F0-9]", "", short_id)[:10].lower() or short_id[:10]
    return f"{date_prefix}--{slug}--{short}.md"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
    ) as f:
        tmp_path = Path(f.name)
        f.write(text.rstrip("\n") + "\n")
    tmp_path.replace(path)
