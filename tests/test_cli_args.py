import unittest

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from wmt.cli import _normalize_argv, build_parser


class CliArgTests(unittest.TestCase):
    def test_config_after_subcommand_is_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            _normalize_argv(["watch", "--once", "--config", "/tmp/wmt_config.yaml"])
        )
        self.assertEqual(args.cmd, "watch")
        self.assertTrue(args.once)
        self.assertEqual(args.config, "/tmp/wmt_config.yaml")

    def test_verbose_after_subcommand_is_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(_normalize_argv(["watch", "--once", "--verbose"]))
        self.assertTrue(args.verbose)


if __name__ == "__main__":
    unittest.main()
