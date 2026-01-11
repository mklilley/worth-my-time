import os
import tempfile
import unittest
from pathlib import Path

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from wmt.config import ConfigError, load_config


class HackMDConfigTests(unittest.TestCase):
    def _write_cfg(self, td: str, text: str) -> Path:
        path = Path(td) / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_disabled_allows_missing_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = self._write_cfg(td, "hackmd:\n  enabled: false\n")
            cfg = load_config(cfg_path)
            self.assertFalse(cfg.hackmd.enabled)

    def test_enabled_requires_token_and_folder(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = self._write_cfg(
                td,
                "hackmd:\n  enabled: true\n  api_token: tok\n  parent_folder_id: folder\n",
            )
            cfg = load_config(cfg_path)
            self.assertTrue(cfg.hackmd.enabled)
            self.assertEqual(cfg.hackmd.api_token, "tok")
            self.assertEqual(cfg.hackmd.parent_folder_id, "folder")

    def test_token_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            os.environ["WMT_TEST_HACKMD_TOKEN"] = "tok_from_env"
            try:
                cfg_path = self._write_cfg(
                    td,
                    "hackmd:\n  enabled: true\n  api_token_env: WMT_TEST_HACKMD_TOKEN\n  parent_folder_id: folder\n",
                )
                cfg = load_config(cfg_path)
                self.assertEqual(cfg.hackmd.api_token, "tok_from_env")
            finally:
                os.environ.pop("WMT_TEST_HACKMD_TOKEN", None)

    def test_enabled_missing_token_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = self._write_cfg(td, "hackmd:\n  enabled: true\n  parent_folder_id: folder\n")
            with self.assertRaises(ConfigError):
                load_config(cfg_path)

    def test_enabled_missing_folder_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = self._write_cfg(td, "hackmd:\n  enabled: true\n  api_token: tok\n")
            with self.assertRaises(ConfigError):
                load_config(cfg_path)


if __name__ == "__main__":
    unittest.main()

