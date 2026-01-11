from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class StatSnapshot:
    size: int
    mtime_ns: int


StatProvider = Callable[[Path], StatSnapshot]
Clock = Callable[[], float]


def _default_stat_provider(path: Path) -> StatSnapshot:
    st = os.stat(path)
    return StatSnapshot(size=st.st_size, mtime_ns=st.st_mtime_ns)


class StableFileTracker:
    def __init__(
        self,
        *,
        stable_seconds: int,
        stat_provider: StatProvider | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._stable_seconds = stable_seconds
        self._stat = stat_provider or _default_stat_provider
        self._clock = clock or time.monotonic
        self._seen: dict[Path, tuple[StatSnapshot, float]] = {}

    def observe(self, candidates: list[Path]) -> list[Path]:
        now = self._clock()
        stable: list[Path] = []

        current_set = set(candidates)
        for path in list(self._seen.keys()):
            if path not in current_set:
                self._seen.pop(path, None)

        for path in candidates:
            try:
                snap = self._stat(path)
            except FileNotFoundError:
                continue

            prior = self._seen.get(path)
            if prior is None:
                self._seen[path] = (snap, now)
                if self._stable_seconds <= 0:
                    stable.append(path)
                continue

            prior_snap, last_change = prior
            if snap != prior_snap:
                self._seen[path] = (snap, now)
                continue

            if (now - last_change) >= self._stable_seconds:
                stable.append(path)

        return stable

    def forget(self, path: Path) -> None:
        self._seen.pop(path, None)
