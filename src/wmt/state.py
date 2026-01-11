from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class StateError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileRecord:
    sha256: str
    status: str
    started_at: float | None
    processed_at: float | None
    source_path: str | None
    source_mtime_ns: int | None
    source_size: int | None
    archive_path: str | None
    topic_file: str | None
    error: str | None
    codex_status: str | None


class StateStore:
    def close(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def get(self, sha256: str) -> FileRecord | None:  # pragma: no cover
        raise NotImplementedError

    def is_processed(self, sha256: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def is_source_processed(
        self,
        source_path: Path,
        *,
        source_mtime_ns: int | None = None,
        source_size: int | None = None,
    ) -> bool:  # pragma: no cover
        raise NotImplementedError

    def processed_source_snapshots(self) -> dict[str, tuple[int | None, int | None]]:  # pragma: no cover
        raise NotImplementedError

    def mark_in_progress(
        self,
        sha256: str,
        source_path: Path,
        *,
        source_mtime_ns: int | None,
        source_size: int | None,
        force: bool = False,
    ) -> None:  # pragma: no cover
        raise NotImplementedError

    def mark_processed(
        self,
        sha256: str,
        *,
        archive_path: Path | None,
        topic_file: Path | None,
        codex_status: str | None,
        source_path: Path | None = None,
        source_mtime_ns: int | None = None,
        source_size: int | None = None,
    ) -> None:  # pragma: no cover
        raise NotImplementedError

    def mark_failed(self, sha256: str, error: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def allow_retry_in_progress(self, sha256: str, ttl_seconds: int) -> bool:  # pragma: no cover
        raise NotImplementedError

    def stats(self) -> dict[str, int]:  # pragma: no cover
        raise NotImplementedError


def _infer_backend(backend: str, path: Path) -> str:
    backend = (backend or "").strip().lower()
    if backend and backend != "auto":
        return backend

    suffix = "".join(path.suffixes).lower()
    if suffix.endswith((".sqlite3", ".sqlite", ".db")):
        return "sqlite"
    if suffix.endswith(".json"):
        return "json"
    return "json"


def open_state_store(*, path: Path, backend: str) -> StateStore:
    path = path.expanduser()
    backend = _infer_backend(backend, path)
    if backend == "json":
        return JsonStateStore(path)
    if backend == "sqlite":
        return SqliteStateStore(path)
    raise StateError(f"Unknown state.backend: {backend}")


class JsonStateStore(StateStore):
    """
    JSON ledger format (v1):
      {
        "version": 1,
        "records": { "<sha256>": { ...FileRecord fields... } },
        "source_snapshots": { "<source_path>": {"mtime_ns": 123, "size": 456} }
      }
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load_or_init()

    def close(self) -> None:
        return

    def _load_or_init(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": 1, "records": {}, "source_snapshots": {}}
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            backup = self._path.with_suffix(self._path.suffix + f".corrupt.{int(time.time())}")
            try:
                self._path.replace(backup)
            except OSError:
                pass
            log.warning("State JSON was corrupt; moved aside to: %s", backup)
            return {"version": 1, "records": {}, "source_snapshots": {}}

        if not isinstance(data, dict):
            return {"version": 1, "records": {}, "source_snapshots": {}}
        data.setdefault("version", 1)
        data.setdefault("records", {})
        data.setdefault("source_snapshots", {})
        if not isinstance(data["records"], dict):
            data["records"] = {}
        if not isinstance(data["source_snapshots"], dict):
            data["source_snapshots"] = {}
        return data

    def _save(self) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        text = json.dumps(self._data, indent=2, sort_keys=True)
        tmp.write_text(text + "\n", encoding="utf-8")
        tmp.replace(self._path)

    def _records(self) -> dict[str, dict[str, Any]]:
        return self._data.setdefault("records", {})

    def _source_snapshots(self) -> dict[str, dict[str, Any]]:
        return self._data.setdefault("source_snapshots", {})

    def get(self, sha256: str) -> FileRecord | None:
        rec = self._records().get(sha256)
        if not isinstance(rec, dict):
            return None
        return FileRecord(
            sha256=sha256,
            status=str(rec.get("status", "")),
            started_at=rec.get("started_at"),
            processed_at=rec.get("processed_at"),
            source_path=rec.get("source_path"),
            source_mtime_ns=rec.get("source_mtime_ns"),
            source_size=rec.get("source_size"),
            archive_path=rec.get("archive_path"),
            topic_file=rec.get("topic_file"),
            codex_status=rec.get("codex_status"),
            error=rec.get("error"),
        )

    def is_processed(self, sha256: str) -> bool:
        rec = self.get(sha256)
        return rec is not None and rec.status == "processed"

    def is_source_processed(
        self,
        source_path: Path,
        *,
        source_mtime_ns: int | None = None,
        source_size: int | None = None,
    ) -> bool:
        snap = self._source_snapshots().get(str(source_path))
        if not isinstance(snap, dict):
            return False
        mtime_ns = snap.get("mtime_ns")
        size = snap.get("size")
        if mtime_ns is None or size is None:
            return True
        if source_mtime_ns is None or source_size is None:
            return True
        return int(mtime_ns) == int(source_mtime_ns) and int(size) == int(source_size)

    def processed_source_snapshots(self) -> dict[str, tuple[int | None, int | None]]:
        out: dict[str, tuple[int | None, int | None]] = {}
        for path, snap in self._source_snapshots().items():
            if not isinstance(snap, dict):
                continue
            out[path] = (snap.get("mtime_ns"), snap.get("size"))
        return out

    def mark_in_progress(
        self,
        sha256: str,
        source_path: Path,
        *,
        source_mtime_ns: int | None,
        source_size: int | None,
        force: bool = False,
    ) -> None:
        records = self._records()
        if sha256 in records and not force:
            return
        rec = records.get(sha256, {})
        if not isinstance(rec, dict):
            rec = {}
        rec.update(
            {
                "status": "in_progress",
                "started_at": time.time(),
                "processed_at": None,
                "source_path": str(source_path),
                "source_mtime_ns": source_mtime_ns,
                "source_size": source_size,
                "error": None,
            }
        )
        records[sha256] = rec
        self._save()

    def mark_processed(
        self,
        sha256: str,
        *,
        archive_path: Path | None,
        topic_file: Path | None,
        codex_status: str | None,
        source_path: Path | None = None,
        source_mtime_ns: int | None = None,
        source_size: int | None = None,
    ) -> None:
        records = self._records()
        rec = records.get(sha256, {})
        if not isinstance(rec, dict):
            rec = {}
        rec.update(
            {
                "status": "processed",
                "started_at": None,
                "processed_at": time.time(),
                "source_path": str(source_path) if source_path else rec.get("source_path"),
                "source_mtime_ns": source_mtime_ns if source_mtime_ns is not None else rec.get("source_mtime_ns"),
                "source_size": source_size if source_size is not None else rec.get("source_size"),
                "archive_path": str(archive_path) if archive_path else None,
                "topic_file": str(topic_file) if topic_file else None,
                "codex_status": codex_status,
                "error": None,
            }
        )
        records[sha256] = rec

        if source_path and source_mtime_ns is not None and source_size is not None:
            self._source_snapshots()[str(source_path)] = {
                "mtime_ns": int(source_mtime_ns),
                "size": int(source_size),
            }
        self._save()

    def mark_failed(self, sha256: str, error: str) -> None:
        records = self._records()
        rec = records.get(sha256, {})
        if not isinstance(rec, dict):
            rec = {}
        rec.update(
            {
                "status": "failed",
                "started_at": None,
                "processed_at": time.time(),
                "error": error,
            }
        )
        records[sha256] = rec
        self._save()

    def allow_retry_in_progress(self, sha256: str, ttl_seconds: int) -> bool:
        rec = self.get(sha256)
        if rec is None:
            return True
        if rec.status == "processed":
            return False
        if rec.status != "in_progress":
            return True
        if rec.started_at is None:
            return True
        return (time.time() - float(rec.started_at)) > ttl_seconds

    def stats(self) -> dict[str, int]:
        out = {"processed": 0, "failed": 0, "in_progress": 0}
        for rec in self._records().values():
            if not isinstance(rec, dict):
                continue
            status = str(rec.get("status", ""))
            if status in out:
                out[status] += 1
        return out


class SqliteStateStore(StateStore):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_files (
              sha256 TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              started_at REAL,
              processed_at REAL,
              source_path TEXT,
              source_mtime_ns INTEGER,
              source_size INTEGER,
              archive_path TEXT,
              topic_file TEXT,
              codex_status TEXT,
              error TEXT
            )
            """
        )
        self._ensure_columns(cur)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_processed_files_source ON processed_files (source_path)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_processed_files_source_stat ON processed_files (source_path, source_mtime_ns, source_size)"
        )
        self._conn.commit()

    def _ensure_columns(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(processed_files)")
        existing = {row[1] for row in cur.fetchall()}
        if "source_mtime_ns" not in existing:
            cur.execute("ALTER TABLE processed_files ADD COLUMN source_mtime_ns INTEGER")
        if "source_size" not in existing:
            cur.execute("ALTER TABLE processed_files ADD COLUMN source_size INTEGER")

    def get(self, sha256: str) -> FileRecord | None:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM processed_files WHERE sha256 = ?", (sha256,))
        row = cur.fetchone()
        if row is None:
            return None
        return FileRecord(
            sha256=row["sha256"],
            status=row["status"],
            started_at=row["started_at"],
            processed_at=row["processed_at"],
            source_path=row["source_path"],
            source_mtime_ns=row["source_mtime_ns"],
            source_size=row["source_size"],
            archive_path=row["archive_path"],
            topic_file=row["topic_file"],
            codex_status=row["codex_status"],
            error=row["error"],
        )

    def is_processed(self, sha256: str) -> bool:
        rec = self.get(sha256)
        return rec is not None and rec.status == "processed"

    def is_source_processed(
        self,
        source_path: Path,
        *,
        source_mtime_ns: int | None = None,
        source_size: int | None = None,
    ) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT status, source_mtime_ns, source_size
            FROM processed_files
            WHERE source_path = ? AND status = 'processed'
            ORDER BY processed_at DESC
            LIMIT 1
            """,
            (str(source_path),),
        )
        row = cur.fetchone()
        if row is None:
            return False
        mtime_ns = row["source_mtime_ns"]
        size = row["source_size"]
        if mtime_ns is None or size is None:
            return True
        if source_mtime_ns is None or source_size is None:
            return True
        return int(mtime_ns) == int(source_mtime_ns) and int(size) == int(source_size)

    def processed_source_snapshots(self) -> dict[str, tuple[int | None, int | None]]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT source_path, source_mtime_ns, source_size, processed_at
            FROM processed_files
            WHERE status='processed' AND source_path IS NOT NULL
            """
        )
        latest: dict[str, tuple[float, int | None, int | None]] = {}
        for row in cur.fetchall():
            p = row["source_path"]
            if not p:
                continue
            processed_at = float(row["processed_at"] or 0.0)
            mtime_ns = row["source_mtime_ns"]
            size = row["source_size"]
            prev = latest.get(p)
            if prev is None or processed_at >= prev[0]:
                latest[p] = (processed_at, mtime_ns, size)
        return {p: (mtime_ns, size) for p, (_t, mtime_ns, size) in latest.items()}

    def mark_in_progress(
        self,
        sha256: str,
        source_path: Path,
        *,
        source_mtime_ns: int | None,
        source_size: int | None,
        force: bool = False,
    ) -> None:
        now = time.time()
        cur = self._conn.cursor()
        if force:
            cur.execute(
                """
                INSERT INTO processed_files (sha256, status, started_at, source_path, source_mtime_ns, source_size)
                VALUES (?, 'in_progress', ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                  status='in_progress',
                  started_at=excluded.started_at,
                  source_path=excluded.source_path,
                  source_mtime_ns=excluded.source_mtime_ns,
                  source_size=excluded.source_size,
                  error=NULL
                """,
                (sha256, now, str(source_path), source_mtime_ns, source_size),
            )
        else:
            cur.execute(
                """
                INSERT INTO processed_files (sha256, status, started_at, source_path, source_mtime_ns, source_size)
                VALUES (?, 'in_progress', ?, ?, ?, ?)
                ON CONFLICT(sha256) DO NOTHING
                """,
                (sha256, now, str(source_path), source_mtime_ns, source_size),
            )
        self._conn.commit()

    def mark_processed(
        self,
        sha256: str,
        *,
        archive_path: Path | None,
        topic_file: Path | None,
        codex_status: str | None,
        source_path: Path | None = None,
        source_mtime_ns: int | None = None,
        source_size: int | None = None,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO processed_files (
              sha256, status, started_at, processed_at, source_path, source_mtime_ns, source_size, archive_path, topic_file, codex_status, error
            )
            VALUES (?, 'processed', NULL, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(sha256) DO UPDATE SET
              status='processed',
              processed_at=excluded.processed_at,
              source_path=COALESCE(excluded.source_path, source_path),
              source_mtime_ns=COALESCE(excluded.source_mtime_ns, source_mtime_ns),
              source_size=COALESCE(excluded.source_size, source_size),
              archive_path=excluded.archive_path,
              topic_file=excluded.topic_file,
              codex_status=excluded.codex_status,
              error=NULL
            """,
            (
                sha256,
                time.time(),
                str(source_path) if source_path else None,
                source_mtime_ns,
                source_size,
                str(archive_path) if archive_path else None,
                str(topic_file) if topic_file else None,
                codex_status,
            ),
        )
        self._conn.commit()

    def mark_failed(self, sha256: str, error: str) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO processed_files (sha256, status, started_at, processed_at, error)
            VALUES (?, 'failed', NULL, ?, ?)
            ON CONFLICT(sha256) DO UPDATE SET
              status='failed',
              processed_at=excluded.processed_at,
              error=excluded.error
            """,
            (sha256, time.time(), error),
        )
        self._conn.commit()

    def allow_retry_in_progress(self, sha256: str, ttl_seconds: int) -> bool:
        rec = self.get(sha256)
        if rec is None:
            return True
        if rec.status == "processed":
            return False
        if rec.status != "in_progress":
            return True
        if rec.started_at is None:
            return True
        return (time.time() - rec.started_at) > ttl_seconds

    def stats(self) -> dict[str, int]:
        cur = self._conn.cursor()
        cur.execute("SELECT status, COUNT(*) as n FROM processed_files GROUP BY status")
        out = {row["status"]: int(row["n"]) for row in cur.fetchall()}
        out.setdefault("processed", 0)
        out.setdefault("failed", 0)
        out.setdefault("in_progress", 0)
        return out
