from __future__ import annotations

from importlib import resources
from pathlib import Path


def _load_packaged_prompt_template() -> str:
    return (
        resources.files("wmt")
        .joinpath("prompts/triage_prompt.md")
        .read_text(encoding="utf-8")
        .strip()
    )


def _load_prompt_template(prompt_file: Path | None) -> str:
    if prompt_file is None:
        return _load_packaged_prompt_template()

    path = Path(prompt_file).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Triage prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()

def build_triage_prompt(
    *,
    link: str,
    transcript: str,
    metadata: str,
    output_file: str,
    prompt_file: Path | None = None,
) -> str:
    # Important: only fill the *input value slots* (first occurrence), leaving later references
    # like "If {TRANSCRIPT} is present..." intact as variable names (not duplicated transcript text).
    prompt = _load_prompt_template(prompt_file)
    prompt = prompt.replace("{LINK}", link or "", 1)
    prompt = prompt.replace("{TRANSCRIPT}", transcript or "", 1)
    prompt = prompt.replace("{METADATA}", metadata or "", 1)
    prompt = prompt.replace("{OUTPUT_FILE}", output_file or "", 1)
    return prompt
