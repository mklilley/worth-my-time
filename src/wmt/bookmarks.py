from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)


class BookmarksError(RuntimeError):
    pass


_CHROMIUM_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def chromium_date_added_to_datetime(value: str | int | None) -> datetime | None:
    """
    Chromium stores bookmark dates as microseconds since 1601-01-01 UTC.

    Example: "13412614145662919" ≈ 2026-01-?? UTC.
    """
    if value is None:
        return None
    try:
        micros = int(value)
    except (TypeError, ValueError):
        return None
    if micros <= 0:
        return None
    try:
        return _CHROMIUM_EPOCH + timedelta(microseconds=micros)
    except (OverflowError, ValueError):
        return None


@dataclass(frozen=True)
class BookmarkItem:
    url: str
    title: str | None
    guid: str | None
    id: str | None
    date_added_raw: str | None
    date_added: datetime | None

    def identity_string(self, *, normalized_url: str) -> str:
        """
        Stable identity string for idempotency.

        Brave/Chromium bookmark items can be edited (title changes), but `guid` and `date_added`
        are intended to remain stable for an item. We also include the (normalized) URL so obvious
        duplicates collapse better in later versions.
        """
        return "\n".join(
            [
                f"url={normalized_url}",
                f"date_added={self.date_added_raw or ''}",
                f"guid={self.guid or ''}",
                f"id={self.id or ''}",
            ]
        )

    def identity_sha256(self, *, normalized_url: str) -> str:
        return sha256(self.identity_string(normalized_url=normalized_url).encode("utf-8")).hexdigest()


def load_bookmarks_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise BookmarksError(f"Bookmarks file not found: {path}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BookmarksError(f"Bookmarks file is not valid JSON (maybe mid-write?): {path}") from e
    if not isinstance(data, dict):
        raise BookmarksError(f"Bookmarks JSON must be an object: {path}")
    return data


def _iter_children(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    children = node.get("children")
    if not isinstance(children, list):
        return []
    return [c for c in children if isinstance(c, dict)]


def _walk(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield node
    if node.get("type") == "folder":
        for child in _iter_children(node):
            yield from _walk(child)


def find_folder(root: dict[str, Any], *, name: str) -> dict[str, Any] | None:
    for node in _walk(root):
        if node.get("type") != "folder":
            continue
        if str(node.get("name", "")).strip() == name:
            return node
    return None


def list_folder_bookmarks(folder: dict[str, Any]) -> list[BookmarkItem]:
    items: list[BookmarkItem] = []
    for node in _walk(folder):
        if node.get("type") != "url":
            continue
        url = str(node.get("url", "")).strip()
        if not url:
            continue
        title = str(node.get("name", "")).strip() or None
        guid = str(node.get("guid", "")).strip() or None
        node_id = str(node.get("id", "")).strip() or None
        date_raw = str(node.get("date_added", "")).strip() or None
        date_added = chromium_date_added_to_datetime(date_raw)
        items.append(
            BookmarkItem(
                url=url,
                title=title,
                guid=guid,
                id=node_id,
                date_added_raw=date_raw,
                date_added=date_added,
            )
        )
    return items


def load_brave_inbox_bookmarks(
    *,
    bookmarks_path: Path,
    inbox_folder_name: str = "Inbox",
    root_name: str = "bookmark_bar",
) -> list[BookmarkItem]:
    """
    Loads Brave/Chromium bookmarks JSON and returns URL items under:
      roots.<root_name>.<children>.../<Inbox folder>/<url items>
    """
    data = load_bookmarks_file(bookmarks_path)
    roots = data.get("roots")
    if not isinstance(roots, dict):
        raise BookmarksError(f"Bookmarks JSON missing roots: {bookmarks_path}")

    root = roots.get(root_name)
    if not isinstance(root, dict):
        raise BookmarksError(f"Bookmarks JSON missing roots.{root_name}: {bookmarks_path}")

    inbox = find_folder(root, name=inbox_folder_name)
    if inbox is None:
        log.info("Inbox folder not found: roots.%s/%s", root_name, inbox_folder_name)
        return []

    return list_folder_bookmarks(inbox)
