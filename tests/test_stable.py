import unittest
from pathlib import Path

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from wmt.stable import StableFileTracker, StatSnapshot


class StableTrackerTests(unittest.TestCase):
    def test_becomes_stable_after_window(self) -> None:
        p = Path("/tmp/a.m4a")
        now = 0.0
        snap = StatSnapshot(size=123, mtime_ns=1)
        stats = {p: snap}

        def clock() -> float:
            return now

        def stat_provider(path: Path) -> StatSnapshot:
            return stats[path]

        t = StableFileTracker(stable_seconds=10, stat_provider=stat_provider, clock=clock)
        self.assertEqual(t.observe([p]), [])

        now = 9.0
        self.assertEqual(t.observe([p]), [])

        now = 10.1
        self.assertEqual(t.observe([p]), [p])

    def test_change_resets_timer(self) -> None:
        p = Path("/tmp/a.m4a")
        now = 0.0
        stats = {p: StatSnapshot(size=1, mtime_ns=1)}

        def clock() -> float:
            return now

        def stat_provider(path: Path) -> StatSnapshot:
            return stats[path]

        t = StableFileTracker(stable_seconds=5, stat_provider=stat_provider, clock=clock)
        t.observe([p])

        now = 6.0
        self.assertEqual(t.observe([p]), [p])

        # File changes; stability window restarts.
        stats[p] = StatSnapshot(size=2, mtime_ns=2)
        now = 6.1
        self.assertEqual(t.observe([p]), [])
        now = 10.9
        self.assertEqual(t.observe([p]), [])
        now = 11.2
        self.assertEqual(t.observe([p]), [p])


if __name__ == "__main__":
    unittest.main()
