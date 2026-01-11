from __future__ import annotations

import re
import tempfile
from pathlib import Path


def _slugify(value: str, *, max_len: int = 80) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"['’]", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    if not value:
        value = "untitled"
    return value[:max_len].strip("-") or "untitled"


def triage_output_path(
    output_dir: Path,
    *,
    title: str | None,
    slug_max_len: int = 60,
) -> Path:
    """
    Returns a non-existing path under `output_dir`:
      <slug>.md, or <slug>-2.md, <slug>-3.md, ...

    Note: this is best-effort and not perfectly race-proof across concurrent writers, but
    `wmt` is designed to run as a single writer in normal usage.
    """
    slug = _slugify(title or "", max_len=slug_max_len)
    candidate = output_dir / f"{slug}.md"
    if not candidate.exists():
        return candidate

    for i in range(2, 10_000):
        candidate = output_dir / f"{slug}-{i}.md"
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Could not find available filename for: {slug}.md")


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
