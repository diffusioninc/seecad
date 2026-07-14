from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from seecad.config import Settings, derive_worker_build_id
from seecad.errors import SeeCADError


def test_settings_accept_compose_aliases_and_plain_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEECAD_MODEL", "gpt-5.6")
    monkeypatch.setenv("SEECAD_REASONING_MODE", "pro")
    monkeypatch.setenv("SEECAD_REASONING_EFFORT", "max")
    monkeypatch.setenv("SEECAD_OPENSCAD_IMAGE", "seecad-openscad:local")
    monkeypatch.setenv("SEECAD_ALLOWED_ORIGINS", "http://localhost:5173")
    settings = Settings()
    assert settings.openai_model == "gpt-5.6"
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.openscad_mode == "docker"


def test_empty_compose_api_key_is_not_reported_as_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert Settings().openai_api_key is None


def test_settings_accept_field_names_and_bound_worker_resources() -> None:
    settings = Settings(openai_model="test-model", openscad_memory="512m")
    assert settings.openai_model == "test-model"
    assert settings.openai_timeout_seconds == 480.0
    with pytest.raises(ValidationError):
        Settings(openscad_memory="unlimited")
    with pytest.raises(ValidationError):
        Settings(max_artifact_bytes=3 * 1024 * 1024 * 1024)


def test_remote_mode_requires_an_absolute_worker_socket() -> None:
    settings = Settings(
        openscad_mode="remote",
        openscad_worker_socket="/run/seecad/worker.sock",
    )
    assert settings.openscad_mode == "remote"
    with pytest.raises(ValidationError):
        Settings(openscad_worker_socket="relative.sock")


def test_public_configuration_cannot_select_unsandboxed_local_execution() -> None:
    with pytest.raises(ValidationError):
        Settings(openscad_mode="local")  # type: ignore[arg-type]


def test_worker_build_identity_is_content_derived_and_file_backed(tmp_path: Path) -> None:
    first = derive_worker_build_id([("worker.py", b"first")], seed="test")
    second = derive_worker_build_id([("worker.py", b"second")], seed="test")
    assert first.startswith("sha256-")
    assert len(first) == 71
    assert first != second

    identity_file = tmp_path / "worker-build-id"
    identity_file.write_text(first)
    settings = Settings(openscad_worker_build_id_file=identity_file)
    assert settings.resolved_worker_build_id == first


def test_static_or_malformed_worker_build_identity_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(openscad_worker_build_id="seecad-worker-0.1.0")


def test_error_details_are_json_bounded_and_redacted() -> None:
    safe = SeeCADError("safe", details={"count": 1})
    assert safe.details == {"count": 1}
    unsafe = SeeCADError("unsafe", details={"object": object()})
    assert unsafe.details == {"details_redacted": True}
