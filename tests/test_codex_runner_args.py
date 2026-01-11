import unittest

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from wmt.codex_runner import _inject_reasoning_effort, _inject_web_search


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


if __name__ == "__main__":
    unittest.main()
