from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

import pytest

from seecad.errors import ArtifactError, ConflictError
from seecad.models import ArtifactRef, DesignSpec
from seecad.store import ArtifactStore, RevisionRepository


def test_content_addressing_integrity_and_private_permissions(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "private" / "blobs")
    first = store.put(b"same", media_type="text/plain", filename="a.txt")
    second = store.put(b"same", media_type="text/plain", filename="b.txt")
    assert first.sha256 == second.sha256
    assert store.get(first.sha256) == b"same"
    assert stat.S_IMODE((tmp_path / "private").stat().st_mode) == 0o700


def test_revisions_are_append_only_and_artifact_manifest_is_sealed(
    tmp_path: Path, simple_spec: DesignSpec
) -> None:
    artifacts = ArtifactStore(tmp_path / "data" / "blobs")
    repository = RevisionRepository(tmp_path / "data" / "index.sqlite3", artifacts)
    artifact = artifacts.put(b"{}", media_type="application/json", filename="design.json")
    root = repository.create_revision(spec=simple_spec, artifacts={"spec": artifact})
    child = repository.create_revision(
        spec=simple_spec,
        artifacts={"spec": artifact},
        design_id=root.design_id,
        parent_revision_id=root.revision_id,
    )
    assert child.parent_revision_id == root.revision_id
    with pytest.raises(ConflictError):
        repository.create_revision(
            spec=simple_spec, artifacts={"spec": artifact}, design_id=root.design_id
        )
    with sqlite3.connect(repository.path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO revision_artifacts
            (revision_id, role, sha256, size_bytes, media_type, filename)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (root.revision_id, "late", artifact.sha256, 2, "application/json", "late.json"),
        )
    with sqlite3.connect(repository.path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE revisions SET metadata_json = '{}' WHERE revision_id = ?",
            (root.revision_id,),
        )
    assert stat.S_IMODE(repository.path.stat().st_mode) == 0o600


def test_repository_rejects_forged_artifact_size(tmp_path: Path, simple_spec: DesignSpec) -> None:
    artifacts = ArtifactStore(tmp_path / "data" / "blobs")
    repository = RevisionRepository(tmp_path / "data" / "index.sqlite3", artifacts)
    genuine = artifacts.put(b"abc", media_type="text/plain", filename="a.txt")
    forged = ArtifactRef(
        sha256=genuine.sha256,
        size_bytes=999,
        media_type=genuine.media_type,
        filename=genuine.filename,
    )
    with pytest.raises(ArtifactError):
        repository.create_revision(spec=simple_spec, artifacts={"spec": forged})
