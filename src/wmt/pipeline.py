from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from wmt.bookmarks import BookmarkItem, BookmarksError, load_brave_inbox_bookmarks
from wmt.codex_runner import CodexError, run_codex
from wmt.config import AppConfig
from wmt.publish import publish_all
from wmt.state import StateStore
from wmt.triage_output import atomic_write_text, triage_output_path
from wmt.triage_prompt import build_triage_prompt
from wmt.urls import is_probably_http_url, normalize_url
from wmt.youtube_metadata import YouTubeMetadata, get_youtube_metadata
from wmt.youtube_transcripts import get_youtube_transcript, is_youtube_url

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessOutcome:
    item_id: str
    url: str
    output_file: Path
    codex_status: str


def _truncate(text: str, *, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        return text, False
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + "\n\n[TRUNCATED]\n", True


def _format_youtube_metadata(meta: YouTubeMetadata | None) -> str:
    if meta is None:
        return ""
    lines: list[str] = ["METADATA (script-provided; best-effort):"]
    if meta.title:
        lines.append(f"- Title: {meta.title}")
    if meta.channel:
        if meta.channel_url:
            lines.append(f"- Channel: {meta.channel} ({meta.channel_url})")
        else:
            lines.append(f"- Channel: {meta.channel}")
    if meta.upload_date:
        lines.append(f"- Upload date: {meta.upload_date}")
    if meta.duration_seconds is not None:
        lines.append(f"- Duration seconds: {meta.duration_seconds}")
    lines.append(f"- Retrieved via: {meta.source}")
    if meta.notes:
        lines.append("- Notes:")
        lines.extend([f"  - {n}" for n in meta.notes])
    return "\n".join(lines).strip()


def _build_transcript_payload(
    cfg: AppConfig,
    *,
    url: str,
    title_hint: str | None,
) -> tuple[str, str | None, str]:
    """
    Returns (transcript_payload, extracted_title, metadata_payload).

    For v1 we only provide a transcript when we can reliably retrieve one (YouTube),
    or when a user supplies it directly via `process-url --transcript-stdin`.

    For normal webpages, we leave the transcript empty and rely on Codex web search/browsing
    to read what it can from the URL.
    """
    normalized = normalize_url(url)

    if is_youtube_url(normalized):
        meta = get_youtube_metadata(normalized, timeout_seconds=cfg.fetch.timeout_seconds)
        extracted_title = meta.title if meta and meta.title else title_hint
        metadata_payload = _format_youtube_metadata(meta)

        yt = get_youtube_transcript(normalized)
        if yt and yt.text.strip():
            log.info(
                "Retrieved YouTube transcript via %s (chars=%s)",
                yt.source,
                len(yt.text),
            )
            header = [
                "TRANSCRIPT SOURCE: YouTube captions",
                f"- Retrieved via: {yt.source}",
            ]
            if yt.language:
                header.append(f"- Language: {yt.language}")
            if yt.is_auto is not None:
                header.append(f"- Auto-generated: {yt.is_auto}")
            if yt.notes:
                header.append("- Notes:")
                header.extend([f"  - {n}" for n in yt.notes])
            payload = "\n".join(header).strip() + "\n\n" + yt.text.strip()
            payload, _trunc = _truncate(payload, max_chars=cfg.fetch.max_transcript_chars)
            return payload, extracted_title, metadata_payload
        log.info("No YouTube transcript available; leaving transcript empty: %s", normalized)
        return "", extracted_title, metadata_payload

    return "", title_hint, ""


def _should_skip_due_to_state(state: StateStore, item_id: str, *, force: bool) -> bool:
    if force:
        return False
    rec = state.get(item_id)
    if rec is None:
        return False
    return rec.status in {"processed", "failed"}


def process_bookmark_item(
    cfg: AppConfig,
    *,
    bookmark: BookmarkItem,
    state: StateStore,
    force: bool = False,
) -> ProcessOutcome | None:
    normalized_url = normalize_url(bookmark.url)
    if not is_probably_http_url(normalized_url):
        log.info("Skipping non-http URL: %s", bookmark.url)
        return None

    item_id = bookmark.identity_sha256(normalized_url=normalized_url)

    if _should_skip_due_to_state(state, item_id, force=force):
        log.info("Already processed (bookmark id): %s", normalized_url)
        return None

    if not state.allow_retry_in_progress(item_id, cfg.processing.in_progress_ttl_seconds) and not force:
        log.info("In-progress elsewhere (skipping for now): %s", normalized_url)
        return None

    title_for_log = (bookmark.title or "").strip() or "(no title)"
    log.info("Processing bookmark: %s — %s", title_for_log, normalized_url)

    state.mark_in_progress(
        item_id,
        cfg.paths.bookmarks_file,
        source_mtime_ns=None,
        source_size=None,
        force=True,
    )

    transcript_payload, extracted_title, metadata_payload = _build_transcript_payload(
        cfg,
        url=normalized_url,
        title_hint=bookmark.title,
    )
    if is_youtube_url(normalized_url) and not transcript_payload.strip():
        err = "No YouTube transcript available (skipping)"
        log.warning("%s: %s", err, normalized_url)
        state.mark_failed(item_id, err)
        return None
    title_for_filename = bookmark.title or extracted_title or "Untitled"
    output_file = triage_output_path(cfg.paths.output_dir.expanduser(), title=title_for_filename)
    log.info("Writing analysis to: %s", output_file)

    stdin_prompt = build_triage_prompt(
        link=normalized_url,
        transcript=transcript_payload,
        metadata=metadata_payload,
        output_file=str(output_file),
        prompt_file=cfg.paths.triage_prompt_file,
    )

    try:
        if not cfg.codex.enabled:
            raise CodexError("Codex is disabled in config")
        result = run_codex(cfg.codex, stdin_prompt=stdin_prompt)
        markdown = result.markdown.strip()
        codex_status = "ok"
    except CodexError as e:
        codex_status = "unavailable"
        basis = "Transcript provided" if transcript_payload.strip() else "Link only"
        markdown = (
            f"# {title_for_filename}\n"
            f"Source: {normalized_url}\n"
            f"Input basis: {basis} (Codex unavailable)\n\n"
            f"## So… is it worth it?\n"
            f"**Recommendation:** Maybe\n"
            f"**Why (2–4 bullets):**\n"
            f"- Codex was unavailable, so this file contains only the link (and transcript if provided).\n"
            f"- Error: {e}\n\n"
        )
        if transcript_payload.strip():
            markdown += (
                "\n<details>\n"
                "<summary>Deeper: provided transcript</summary>\n\n"
                f"```\n{transcript_payload}\n```\n"
                "</details>\n"
            )

    atomic_write_text(output_file, markdown)
    for res in publish_all(cfg, markdown=markdown):
        if not res.ok:
            log.warning("Publish failed (%s): %s", res.publisher, res.error)
        else:
            log.info("Published (%s): %s", res.publisher, res.url or res.note_id or "ok")
    state.mark_processed(
        item_id,
        archive_path=None,
        topic_file=output_file,
        codex_status=codex_status,
        source_path=cfg.paths.bookmarks_file,
        source_mtime_ns=None,
        source_size=None,
    )
    return ProcessOutcome(
        item_id=item_id,
        url=normalized_url,
        output_file=output_file,
        codex_status=codex_status,
    )


def process_one_from_inbox(
    cfg: AppConfig,
    *,
    state: StateStore,
    force: bool = False,
) -> ProcessOutcome | None:
    try:
        bookmarks = load_brave_inbox_bookmarks(
            bookmarks_path=cfg.paths.bookmarks_file,
            inbox_folder_name=cfg.bookmarks.inbox_folder_name,
            root_name=cfg.bookmarks.root_name,
        )
    except BookmarksError as e:
        log.warning("Failed to read bookmarks: %s", e)
        return None

    def sort_key(b: BookmarkItem) -> tuple[int, str]:
        dt = b.date_added or datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (int(dt.timestamp()), b.url)

    bookmarks.sort(key=sort_key)
    if not bookmarks:
        log.info("Inbox folder has no URL bookmarks: %s", cfg.bookmarks.inbox_folder_name)
        return None

    processed = 0
    for b in bookmarks:
        if processed >= max(1, cfg.processing.max_items_per_run):
            break
        try:
            outcome = process_bookmark_item(cfg, bookmark=b, state=state, force=force)
            if outcome:
                processed += 1
                return outcome
        except Exception:
            log.exception("Failed processing bookmark: %s", b.url)
            try:
                normalized = normalize_url(b.url)
                item_id = b.identity_sha256(normalized_url=normalized)
                state.mark_failed(item_id, "Unhandled exception (see logs)")
            except Exception:
                pass

    log.info("No unprocessed bookmarks found in Inbox (nothing to do).")
    return None


def process_url(
    cfg: AppConfig,
    *,
    url: str,
    state: StateStore,
    transcript: str | None = None,
    title: str | None = None,
    force: bool = False,
) -> ProcessOutcome | None:
    normalized_url = normalize_url(url)
    if not is_probably_http_url(normalized_url):
        log.warning("Not an http(s) URL: %s", url)
        return None

    # Manual mode is idempotent per normalized URL by default.
    manual_item = BookmarkItem(
        url=normalized_url,
        title=title,
        guid=None,
        id=None,
        date_added_raw=None,
        date_added=None,
    )
    item_id = manual_item.identity_sha256(normalized_url=normalized_url)

    if _should_skip_due_to_state(state, item_id, force=force):
        log.info("Already processed (url): %s", normalized_url)
        return None

    if not state.allow_retry_in_progress(item_id, cfg.processing.in_progress_ttl_seconds) and not force:
        log.info("In-progress elsewhere (skipping for now): %s", normalized_url)
        return None

    state.mark_in_progress(
        item_id,
        cfg.paths.bookmarks_file,
        source_mtime_ns=None,
        source_size=None,
        force=True,
    )

    if transcript is not None and transcript.strip():
        payload = "TRANSCRIPT PROVIDED BY USER:\n\n" + transcript.strip()
        payload, _trunc = _truncate(payload, max_chars=cfg.fetch.max_transcript_chars)
        meta = (
            get_youtube_metadata(normalized_url, timeout_seconds=cfg.fetch.timeout_seconds)
            if is_youtube_url(normalized_url)
            else None
        )
        extracted_title = title or (meta.title if meta and meta.title else None)
        metadata_payload = _format_youtube_metadata(meta)
    else:
        payload, extracted_title, metadata_payload = _build_transcript_payload(
            cfg, url=normalized_url, title_hint=title
        )
        if is_youtube_url(normalized_url) and not payload.strip():
            err = "No YouTube transcript available (skipping)"
            log.warning("%s: %s", err, normalized_url)
            state.mark_failed(item_id, err)
            return None

    title_for_filename = title or extracted_title or "Untitled"
    output_file = triage_output_path(cfg.paths.output_dir.expanduser(), title=title_for_filename)
    log.info("Processing URL: %s", normalized_url)
    log.info("Writing analysis to: %s", output_file)

    stdin_prompt = build_triage_prompt(
        link=normalized_url,
        transcript=payload,
        metadata=metadata_payload,
        output_file=str(output_file),
        prompt_file=cfg.paths.triage_prompt_file,
    )

    try:
        if not cfg.codex.enabled:
            raise CodexError("Codex is disabled in config")
        result = run_codex(cfg.codex, stdin_prompt=stdin_prompt)
        markdown = result.markdown.strip()
        codex_status = "ok"
    except CodexError as e:
        codex_status = "unavailable"
        basis = "Transcript provided" if payload.strip() else "Link only"
        markdown = (
            f"# {title_for_filename}\n"
            f"Source: {normalized_url}\n"
            f"Input basis: {basis} (Codex unavailable)\n\n"
            f"## So… is it worth it?\n"
            f"**Recommendation:** Maybe\n"
            f"**Why (2–4 bullets):**\n"
            f"- Codex was unavailable, so this file contains only the link (and transcript if provided).\n"
            f"- Error: {e}\n\n"
        )
        if payload.strip():
            markdown += (
                "\n<details>\n"
                "<summary>Deeper: provided transcript</summary>\n\n"
                f"```\n{payload}\n```\n"
                "</details>\n"
            )

    atomic_write_text(output_file, markdown)
    for res in publish_all(cfg, markdown=markdown):
        if not res.ok:
            log.warning("Publish failed (%s): %s", res.publisher, res.error)
        else:
            log.info("Published (%s): %s", res.publisher, res.url or res.note_id or "ok")
    state.mark_processed(
        item_id,
        archive_path=None,
        topic_file=output_file,
        codex_status=codex_status,
        source_path=cfg.paths.bookmarks_file,
        source_mtime_ns=None,
        source_size=None,
    )
    return ProcessOutcome(item_id=item_id, url=normalized_url, output_file=output_file, codex_status=codex_status)
