import subprocess
import unittest
from unittest.mock import patch

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from wmt.codex_runner import (
    CodexModelUnsupportedError,
    _inject_reasoning_effort,
    _inject_web_search,
    run_codex,
)
from wmt.config import CodexConfig


class CodexRunnerArgTests(unittest.TestCase):
    def test_inject_web_search_before_exec(self) -> None:
        cmd = ["codex", "exec", "--sandbox", "read-only", "-"]
        out = _inject_web_search(cmd, True)
        self.assertEqual(out[:3], ["codex", "--search", "exec"])

    def test_inject_web_search_no_duplicates(self) -> None:
        cmd = ["codex", "--search", "exec", "-"]
        out = _inject_web_search(cmd, True)
        self.assertEqual(out, cmd)

    def test_inject_reasoning_effort_quotes_value(self) -> None:
        cmd = ["codex", "exec", "-"]
        out = _inject_reasoning_effort(cmd, "xhigh")
        joined = " ".join(out)
        self.assertIn('model_reasoning_effort="xhigh"', joined)

    def test_unsupported_chatgpt_model_has_specific_error(self) -> None:
        cfg = CodexConfig(
            enabled=True,
            command=("codex", "exec", "-"),
            model="gpt-old",
            model_reasoning_effort="",
            web_search_enabled=False,
            timeout_seconds=10,
        )
        failure = subprocess.CalledProcessError(
            1,
            ["codex"],
            stderr=(
                "The 'gpt-old' model is not supported when using Codex with a ChatGPT account."
            ),
        )
        with patch("wmt.codex_runner.subprocess.run", side_effect=failure):
            with self.assertRaisesRegex(CodexModelUnsupportedError, "gpt-old"):
                run_codex(cfg, stdin_prompt="test")


if __name__ == "__main__":
    unittest.main()
