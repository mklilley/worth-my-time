from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config not found: {path}")

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as e:
        raise ConfigError(
            "PyYAML is required to parse config.yaml. Install it with: pip install pyyaml"
        ) from e

    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e

    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ConfigError(f"Invalid config: expected a top-level mapping in {path}")
    return parsed


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def _expand_path(value: str | None) -> Path | None:
    if value is None:
        return None
    return Path(os.path.expandvars(value)).expanduser()


def _optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return _expand_path(s)


@dataclass(frozen=True)
class PathsConfig:
    bookmarks_file: Path
    output_dir: Path
    log_file: Path
    triage_prompt_file: Path | None


@dataclass(frozen=True)
class BookmarksConfig:
    root_name: str
    inbox_folder_name: str


@dataclass(frozen=True)
class StateConfig:
    backend: str
    path: Path


@dataclass(frozen=True)
class ProcessingConfig:
    stable_seconds: int
    poll_interval_seconds: int
    in_progress_ttl_seconds: int
    max_items_per_run: int


@dataclass(frozen=True)
class FetchConfig:
    timeout_seconds: int
    max_bytes: int
    max_transcript_chars: int


@dataclass(frozen=True)
class CodexConfig:
    enabled: bool
    command: tuple[str, ...]
    model: str
    model_reasoning_effort: str
    web_search_enabled: bool
    timeout_seconds: int


@dataclass(frozen=True)
class HackMDConfig:
    enabled: bool
    api_base_url: str
    api_token: str
    parent_folder_id: str
    timeout_seconds: int


@dataclass(frozen=True)
class AppConfig:
    paths: PathsConfig
    bookmarks: BookmarksConfig
    state: StateConfig
    processing: ProcessingConfig
    fetch: FetchConfig
    codex: CodexConfig
    hackmd: HackMDConfig
    config_path: Path


DEFAULT_CONFIG: dict[str, Any] = {
    "paths": {
        "bookmarks_file": "~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Bookmarks",
        "output_dir": "~/Syncthing/WorthMyTime",
        "log_file": "~/Library/Logs/worth_my_time.log",
        "triage_prompt_file": "",
    },
    "bookmarks": {"root_name": "bookmark_bar", "inbox_folder_name": "Inbox"},
    "state": {"backend": "json", "path": "~/.config/wmt/state.json"},
    "processing": {
        "stable_seconds": 2,
        "poll_interval_seconds": 30,
        "in_progress_ttl_seconds": 3600,
        "max_items_per_run": 1,
    },
    "fetch": {
        "timeout_seconds": 20,
        "max_bytes": 2_000_000,
        "max_transcript_chars": 120_000,
    },
    "codex": {
        "enabled": True,
        "command": ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "-"],
        "model": "",
        "model_reasoning_effort": "",
        "web_search_enabled": True,
        "timeout_seconds": 900,
    },
    "hackmd": {
        "enabled": False,
        "api_base_url": "https://api.hackmd.io/v1",
        "api_token": "",
        "api_token_env": "",
        "parent_folder_id": "",
        "timeout_seconds": 20,
    },
}


def default_config_path() -> Path:
    env = os.environ.get("WMT_CONFIG")
    if env:
        return Path(env).expanduser()

    cwd_config = Path.cwd() / "config.yaml"
    if cwd_config.exists():
        return cwd_config

    return Path("~/.config/wmt/config.yaml").expanduser()


def load_config(path: Path | None = None) -> AppConfig:
    config_path = (path or default_config_path()).expanduser()
    data = _load_yaml(config_path)
    merged = _deep_merge(DEFAULT_CONFIG, data)

    paths = merged.get("paths", {})
    bookmarks = merged.get("bookmarks", {})
    state = merged.get("state", {})
    processing = merged.get("processing", {})
    fetch = merged.get("fetch", {})
    codex = merged.get("codex", {})
    hackmd = merged.get("hackmd", {})

    triage_prompt_file = _optional_path(paths.get("triage_prompt_file"))
    if triage_prompt_file is not None and not triage_prompt_file.exists():
        raise ConfigError(f"paths.triage_prompt_file does not exist: {triage_prompt_file}")

    hackmd_enabled = bool(hackmd.get("enabled", False))
    api_base_url = str(hackmd.get("api_base_url", "https://api.hackmd.io/v1")).strip().rstrip("/")
    api_token = str(hackmd.get("api_token", "")).strip()
    api_token_env = str(hackmd.get("api_token_env", "")).strip()
    if not api_token and api_token_env:
        api_token = str(os.environ.get(api_token_env, "")).strip()
    parent_folder_id = str(hackmd.get("parent_folder_id", "")).strip()
    hackmd_timeout = int(hackmd.get("timeout_seconds", 20))

    if hackmd_enabled:
        if not api_token:
            raise ConfigError("hackmd.enabled is true but hackmd.api_token is empty")
        if not parent_folder_id:
            raise ConfigError("hackmd.enabled is true but hackmd.parent_folder_id is empty")

    return AppConfig(
        paths=PathsConfig(
            bookmarks_file=_expand_path(str(paths.get("bookmarks_file"))) or Path(),
            output_dir=_expand_path(str(paths.get("output_dir"))) or Path(),
            log_file=_expand_path(str(paths.get("log_file"))) or Path(),
            triage_prompt_file=triage_prompt_file,
        ),
        bookmarks=BookmarksConfig(
            root_name=str(bookmarks.get("root_name", "bookmark_bar")),
            inbox_folder_name=str(bookmarks.get("inbox_folder_name", "Inbox")),
        ),
        state=StateConfig(
            backend=str(state.get("backend", "json")).strip().lower(),
            path=_expand_path(str(state.get("path", "~/.config/wmt/state.json"))) or Path(),
        ),
        processing=ProcessingConfig(
            stable_seconds=int(processing.get("stable_seconds", 2)),
            poll_interval_seconds=int(processing.get("poll_interval_seconds", 30)),
            in_progress_ttl_seconds=int(processing.get("in_progress_ttl_seconds", 3600)),
            max_items_per_run=int(processing.get("max_items_per_run", 1)),
        ),
        fetch=FetchConfig(
            timeout_seconds=int(fetch.get("timeout_seconds", 20)),
            max_bytes=int(fetch.get("max_bytes", 2_000_000)),
            max_transcript_chars=int(fetch.get("max_transcript_chars", 120_000)),
        ),
        codex=CodexConfig(
            enabled=bool(codex.get("enabled", True)),
            command=tuple(str(x) for x in codex.get("command", []) if str(x).strip()),
            model=str(codex.get("model", "")).strip(),
            model_reasoning_effort=str(codex.get("model_reasoning_effort", "")).strip(),
            web_search_enabled=bool(codex.get("web_search_enabled", True)),
            timeout_seconds=int(codex.get("timeout_seconds", 900)),
        ),
        hackmd=HackMDConfig(
            enabled=hackmd_enabled,
            api_base_url=api_base_url,
            api_token=api_token,
            parent_folder_id=parent_folder_id,
            timeout_seconds=hackmd_timeout,
        ),
        config_path=config_path.resolve(),
    )
