from __future__ import annotations

import logging

from wmt.config import AppConfig
from wmt.publishers.base import PublishResult
from wmt.publishers.hackmd import publish_markdown as publish_hackmd

log = logging.getLogger(__name__)


def publish_all(cfg: AppConfig, *, markdown: str) -> list[PublishResult]:
    results: list[PublishResult] = []
    if cfg.hackmd.enabled:
        results.append(publish_hackmd(cfg.hackmd, markdown=markdown))
    return results

