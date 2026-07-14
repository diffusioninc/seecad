"""Content-addressed blobs and append-only SQLite design revisions."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from seecad.errors import ArtifactError, ConflictError, NotFoundError
from seecad.models import ArtifactRef, DesignSpec, RevisionResponse


class ArtifactStore:
    def __init__(self, root: Path, *, max_bytes: int = 256 * 1024 * 1024) -> None:
        self.root = root.expanduser().resolve()
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.parent.chmod(0o700)
        self.root.chmod(0o700)

    def put(self, data: bytes, *, media_type: str, filename: str) -> ArtifactRef:
        if len(data) > self.max_bytes:
            raise ArtifactError(
                "artifact exceeds configured size limit",
                details={"size_bytes": len(data), "max_bytes": self.max_bytes},
            )
        digest = hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        if not path.exists():
            fd, temp_name = tempfile.mkstemp(prefix=".blob-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temp_name, 0o600)
                with suppress(FileExistsError):
                    os.link(temp_name, path)
            except OSError as exc:
                raise ArtifactError("failed to persist artifact") from exc
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temp_name)
        return ArtifactRef(
            sha256=digest,
            size_bytes=len(data),
            media_type=media_type,
            filename=Path(filename).name,
        )

    def get(self, sha256: str) -> bytes:
        path = self._path(sha256)
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise NotFoundError("artifact not found", details={"sha256": sha256}) from exc
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ArtifactError("artifact integrity check failed", details={"sha256": sha256})
        return data

    def exists(self, sha256: str) -> bool:
        return self._path(sha256).is_file()

    def writable(self) -> bool:
        return self.root.is_dir() and os.access(self.root, os.W_OK)

    def _path(self, sha256: str) -> Path:
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            raise NotFoundError("invalid artifact id")
        return self.root / sha256[:2] / sha256[2:]


class RevisionRepository:
    """SQLite index whose revision rows and links cannot be updated or deleted."""

    def __init__(self, path: Path, artifacts: ArtifactStore) -> None:
        self.path = path.expanduser().resolve()
        self.artifacts = artifacts
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        self.path.chmod(0o600)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                DROP TRIGGER IF EXISTS revisions_no_update;
                DROP TRIGGER IF EXISTS revisions_no_delete;
                DROP TRIGGER IF EXISTS revision_artifacts_no_insert_sealed;
                DROP TRIGGER IF EXISTS revision_artifacts_no_update;
                DROP TRIGGER IF EXISTS revision_artifacts_no_delete;
                CREATE TABLE IF NOT EXISTS designs (
                    design_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    revision_id TEXT PRIMARY KEY,
                    design_id TEXT NOT NULL REFERENCES designs(design_id),
                    parent_revision_id TEXT REFERENCES revisions(revision_id),
                    created_at TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    artifact_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS revision_artifacts (
                    revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
                    role TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    PRIMARY KEY (revision_id, role)
                );
                CREATE INDEX IF NOT EXISTS revisions_design_created
                    ON revisions(design_id, created_at);
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(revisions)").fetchall()
            }
            if "artifact_count" not in columns:
                connection.execute(
                    "ALTER TABLE revisions ADD COLUMN artifact_count INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                """UPDATE revisions SET artifact_count = (
                    SELECT COUNT(*) FROM revision_artifacts
                    WHERE revision_artifacts.revision_id = revisions.revision_id
                )"""
            )
            connection.executescript(
                """
                CREATE TRIGGER revisions_no_update
                    BEFORE UPDATE ON revisions
                    BEGIN SELECT RAISE(ABORT, 'revisions are immutable'); END;
                CREATE TRIGGER revisions_no_delete
                    BEFORE DELETE ON revisions
                    BEGIN SELECT RAISE(ABORT, 'revisions are immutable'); END;
                CREATE TRIGGER revision_artifacts_no_insert_sealed
                    BEFORE INSERT ON revision_artifacts
                    WHEN (SELECT COUNT(*) FROM revision_artifacts
                          WHERE revision_id = NEW.revision_id)
                         >= (SELECT artifact_count FROM revisions
                             WHERE revision_id = NEW.revision_id)
                    BEGIN SELECT RAISE(ABORT, 'revision artifact manifest is sealed'); END;
                CREATE TRIGGER revision_artifacts_no_update
                    BEFORE UPDATE ON revision_artifacts
                    BEGIN SELECT RAISE(ABORT, 'revision artifacts are immutable'); END;
                CREATE TRIGGER revision_artifacts_no_delete
                    BEFORE DELETE ON revision_artifacts
                    BEGIN SELECT RAISE(ABORT, 'revision artifacts are immutable'); END;
                """
            )
        self._secure_database_files()

    def _secure_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{self.path}{suffix}")
            if candidate.exists():
                candidate.chmod(0o600)

    def create_revision(
        self,
        *,
        spec: DesignSpec,
        artifacts: Mapping[str, ArtifactRef],
        design_id: str | None = None,
        parent_revision_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> RevisionResponse:
        now = datetime.now(UTC)
        design_id = design_id or f"dsgn_{secrets.token_hex(12)}"
        revision_id = f"rev_{secrets.token_hex(12)}"
        spec_json = json.dumps(spec.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
        metadata_json = json.dumps(dict(metadata or {}), separators=(",", ":"), sort_keys=True)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                design = connection.execute(
                    "SELECT design_id FROM designs WHERE design_id = ?", (design_id,)
                ).fetchone()
                if design is None:
                    if parent_revision_id is not None:
                        raise ConflictError("a new design cannot have a parent revision")
                    connection.execute(
                        "INSERT INTO designs(design_id, created_at) VALUES (?, ?)",
                        (design_id, now.isoformat()),
                    )
                elif parent_revision_id is None:
                    raise ConflictError("an existing design revision requires a parent")
                if parent_revision_id is not None:
                    parent = connection.execute(
                        "SELECT design_id FROM revisions WHERE revision_id = ?",
                        (parent_revision_id,),
                    ).fetchone()
                    if parent is None:
                        raise NotFoundError("parent revision not found")
                    if parent["design_id"] != design_id:
                        raise ConflictError("parent revision belongs to another design")
                connection.execute(
                    """INSERT INTO revisions(
                        revision_id, design_id, parent_revision_id, created_at, spec_json,
                        metadata_json, artifact_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        revision_id,
                        design_id,
                        parent_revision_id,
                        now.isoformat(),
                        spec_json,
                        metadata_json,
                        len(artifacts),
                    ),
                )
                for role, artifact in sorted(artifacts.items()):
                    if not role or len(role) > 64:
                        raise ConflictError("artifact role is invalid")
                    data = self.artifacts.get(artifact.sha256)
                    if len(data) != artifact.size_bytes:
                        raise ArtifactError(
                            "revision artifact metadata does not match stored bytes",
                            details={"role": role, "sha256": artifact.sha256},
                        )
                    connection.execute(
                        """INSERT INTO revision_artifacts(
                            revision_id, role, sha256, size_bytes, media_type, filename
                        ) VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            revision_id,
                            role,
                            artifact.sha256,
                            artifact.size_bytes,
                            artifact.media_type,
                            artifact.filename,
                        ),
                    )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        self._secure_database_files()
        return self.get_revision(revision_id, design_id=design_id)

    def get_revision(self, revision_id: str, *, design_id: str | None = None) -> RevisionResponse:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM revisions WHERE revision_id = ?", (revision_id,)
            ).fetchone()
            if row is None or (design_id is not None and row["design_id"] != design_id):
                raise NotFoundError("revision not found", details={"revision_id": revision_id})
            artifact_rows = connection.execute(
                "SELECT * FROM revision_artifacts WHERE revision_id = ? ORDER BY role",
                (revision_id,),
            ).fetchall()
        return self._to_response(row, artifact_rows)

    def list_revisions(self, design_id: str) -> list[RevisionResponse]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM revisions WHERE design_id = ? ORDER BY created_at, revision_id",
                (design_id,),
            ).fetchall()
            if not rows:
                raise NotFoundError("design not found", details={"design_id": design_id})
            result: list[RevisionResponse] = []
            for row in rows:
                artifact_rows = connection.execute(
                    "SELECT * FROM revision_artifacts WHERE revision_id = ? ORDER BY role",
                    (row["revision_id"],),
                ).fetchall()
                result.append(self._to_response(row, artifact_rows))
        return result

    @staticmethod
    def _to_response(row: sqlite3.Row, artifact_rows: list[sqlite3.Row]) -> RevisionResponse:
        artifacts = {
            artifact["role"]: ArtifactRef(
                sha256=artifact["sha256"],
                size_bytes=artifact["size_bytes"],
                media_type=artifact["media_type"],
                filename=artifact["filename"],
            )
            for artifact in artifact_rows
        }
        return RevisionResponse(
            design_id=row["design_id"],
            revision_id=row["revision_id"],
            parent_revision_id=row["parent_revision_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            spec=DesignSpec.model_validate_json(row["spec_json"]),
            artifacts=artifacts,
            metadata=json.loads(row["metadata_json"]),
        )
