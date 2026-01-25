from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from wmt.config import CodexConfig

log = logging.getLogger(__name__)


class CodexError(RuntimeError):
    pass


class CodexDisabledError(CodexError):
    pass


class CodexNotFoundError(CodexError):
    pass


class CodexTimeoutError(CodexError):
    pass


class CodexFailedError(CodexError):
    pass


class CodexEmptyOutputError(CodexError):
    pass


@dataclass(frozen=True)
class CodexResult:
    markdown: str


def _ensure_output_last_message(cmd: list[str], output_path: Path) -> list[str]:
    if any(part in {"-o", "--output-last-message"} for part in cmd):
        return cmd

    # Inject before prompt argument (`-`) if present.
    try:
        idx = cmd.index("-")
    except ValueError:
        cmd = cmd + ["-"]
        idx = len(cmd) - 1

    return cmd[:idx] + ["--output-last-message", str(output_path)] + cmd[idx:]


def _inject_model(cmd: list[str], model: str) -> list[str]:
    model = model.strip()
    if not model:
        return cmd
    if any(part in {"-m", "--model"} for part in cmd):
        return cmd
    try:
        idx = cmd.index("-")
    except ValueError:
        idx = len(cmd)
    return cmd[:idx] + ["--model", model] + cmd[idx:]


def _inject_reasoning_effort(cmd: list[str], reasoning_effort: str) -> list[str]:
    reasoning_effort = reasoning_effort.strip()
    if not reasoning_effort:
        return cmd

    # If the user already supplied a config override for this, respect it.
    for part in cmd:
        if "model_reasoning_effort" in part:
            return cmd

    try:
        idx = cmd.index("-")
    except ValueError:
        idx = len(cmd)

    # Codex CLI parses the value as TOML, so we must quote the string.
    return cmd[:idx] + ["-c", f'model_reasoning_effort="{reasoning_effort}"'] + cmd[idx:]


def _inject_web_search(cmd: list[str], enabled: bool) -> list[str]:
    if not enabled:
        return cmd
    if "--search" in cmd:
        return cmd

    # `--search` is a global flag and must appear before the `exec` subcommand.
    for subcmd in ("exec", "e"):
        if subcmd in cmd:
            idx = cmd.index(subcmd)
            return cmd[:idx] + ["--search"] + cmd[idx:]

    # Fallback: insert right after the binary.
    if cmd:
        return [cmd[0], "--search", *cmd[1:]]
    return cmd


def run_codex(cfg: CodexConfig, *, stdin_prompt: str) -> CodexResult:
    if not cfg.enabled:
        raise CodexDisabledError("Codex is disabled in config")
    if not cfg.command:
        raise CodexError("codex.command is empty")

    base_cmd = list(cfg.command)
    env = dict(os.environ)
    env.setdefault("NO_COLOR", "1")

    with tempfile.TemporaryDirectory(prefix="wmt_codex_") as tmp:
        out_path = Path(tmp) / "codex_last_message.txt"
        cmd = _inject_web_search(base_cmd, cfg.web_search_enabled)
        cmd = _ensure_output_last_message(cmd, out_path)
        cmd = _inject_model(cmd, cfg.model)
        cmd = _inject_reasoning_effort(cmd, cfg.model_reasoning_effort)

        log.info("Running Codex: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                input=stdin_prompt,
                text=True,
                capture_output=True,
                timeout=cfg.timeout_seconds,
                env=env,
                check=True,
            )
        except FileNotFoundError as e:
            raise CodexNotFoundError(f"Codex command not found: {cmd[0]}") from e
        except subprocess.TimeoutExpired as e:
            if out_path.exists():
                text = out_path.read_text(encoding="utf-8").strip()
                if text:
                    log.warning(
                        "Codex timed out after %ss but produced an output file; using partial output",
                        cfg.timeout_seconds,
                    )
                    return CodexResult(markdown=text)
            raise CodexTimeoutError(
                f"Codex timed out after {cfg.timeout_seconds}s "
                f"(increase codex.timeout_seconds in config.yaml)"
            ) from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            stdout = (e.stdout or "").strip()
            detail = stderr or stdout or f"exit {e.returncode}"
            raise CodexFailedError(f"Codex failed: {detail}") from e

        if out_path.exists():
            text = out_path.read_text(encoding="utf-8").strip()
        else:
            text = ""
        if not text:
            raise CodexEmptyOutputError("Codex produced no output (empty last message)")
        return CodexResult(markdown=text)
