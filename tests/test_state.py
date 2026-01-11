import tempfile
import unittest
from pathlib import Path

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from wmt.state import open_state_store


class StateStoreTests(unittest.TestCase):
    def test_idempotency_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            for backend, filename in (("json", "state.json"), ("sqlite", "state.sqlite3")):
                path = Path(td) / filename
                s = open_state_store(path=path, backend=backend)
                try:
                    sha = f"abc123_{backend}"
                    source = Path("/tmp/a.m4a")
                    mtime_ns = 123
                    size = 456

                    self.assertFalse(s.is_processed(sha))

                    s.mark_in_progress(
                        sha,
                        source,
                        source_mtime_ns=mtime_ns,
                        source_size=size,
                        force=True,
                    )
                    self.assertFalse(s.is_processed(sha))
                    self.assertFalse(s.allow_retry_in_progress(sha, ttl_seconds=3600))

                    s.mark_processed(
                        sha,
                        archive_path=Path("/tmp/archive/a.m4a"),
                        topic_file=Path("/tmp/topic.md"),
                        codex_status="ok",
                        source_path=source,
                        source_mtime_ns=mtime_ns,
                        source_size=size,
                    )
                    self.assertTrue(s.is_processed(sha))
                    self.assertTrue(s.is_source_processed(source, source_mtime_ns=mtime_ns, source_size=size))
                    self.assertFalse(s.allow_retry_in_progress(sha, ttl_seconds=0))
                finally:
                    s.close()


if __name__ == "__main__":
    unittest.main()
