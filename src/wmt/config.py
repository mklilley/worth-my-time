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


@dataclass(frozen=True)
class PathsConfig:
    bookmarks_file: Path
    output_dir: Path
    log_file: Path


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
class AppConfig:
    paths: PathsConfig
    bookmarks: BookmarksConfig
    state: StateConfig
    processing: ProcessingConfig
    fetch: FetchConfig
    codex: CodexConfig
    config_path: Path


DEFAULT_CONFIG: dict[str, Any] = {
    "paths": {
        "bookmarks_file": "~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Bookmarks",
        "output_dir": "~/Syncthing/WorthMyTime",
        "log_file": "~/Library/Logs/worth_my_time.log",
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

    return AppConfig(
        paths=PathsConfig(
            bookmarks_file=_expand_path(str(paths.get("bookmarks_file"))) or Path(),
            output_dir=_expand_path(str(paths.get("output_dir"))) or Path(),
            log_file=_expand_path(str(paths.get("log_file"))) or Path(),
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
        config_path=config_path.resolve(),
    )
