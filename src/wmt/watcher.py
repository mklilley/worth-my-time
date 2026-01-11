from __future__ import annotations

import logging
import signal
import time

from wmt.config import AppConfig
from wmt.pipeline import process_one_from_inbox
from wmt.state import StateStore, open_state_store
from wmt.stable import StableFileTracker

log = logging.getLogger(__name__)


class Watcher:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._stop = False
        self._stable = StableFileTracker(stable_seconds=cfg.processing.stable_seconds)

    def close(self) -> None:
        return

    def stop(self) -> None:
        self._stop = True

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())

        log.info("Watching bookmarks file: %s", self._cfg.paths.bookmarks_file)
        while not self._stop:
            self.run_once(log_when_idle=False, wait_for_stable=True)
            time.sleep(self._cfg.processing.poll_interval_seconds)

        log.info("Watcher stopped")

    def run_once(
        self,
        *,
        log_when_idle: bool = False,
        wait_for_stable: bool = False,
    ) -> None:
        bookmarks_path = self._cfg.paths.bookmarks_file
        if log_when_idle:
            log.info("Checking bookmarks file: %s", bookmarks_path)

        if not bookmarks_path.exists():
            if log_when_idle:
                log.warning("Bookmarks file does not exist: %s", bookmarks_path)
            return

        stable = self._stable.observe([bookmarks_path])
        if not stable and wait_for_stable and self._cfg.processing.stable_seconds > 0:
            deadline = time.monotonic() + float(self._cfg.processing.stable_seconds)
            while not stable and time.monotonic() < deadline and not self._stop:
                remaining = deadline - time.monotonic()
                time.sleep(min(0.5, max(0.0, remaining)))
                stable = self._stable.observe([bookmarks_path])

        if not stable:
            if log_when_idle:
                log.info(
                    "Bookmarks file not stable yet (need unchanged for %ss)",
                    self._cfg.processing.stable_seconds,
                )
            return

        # Reload the state store each run so manual edits to state.json take effect, and so
        # concurrent one-off runs (`wmt process-one`) don't require restarting the watcher.
        state: StateStore = open_state_store(path=self._cfg.state.path, backend=self._cfg.state.backend)
        try:
            outcome = process_one_from_inbox(self._cfg, state=state)
            if outcome:
                log.info(
                    "Processed bookmark -> %s (codex=%s)",
                    outcome.output_file,
                    outcome.codex_status,
                )
        finally:
            state.close()
