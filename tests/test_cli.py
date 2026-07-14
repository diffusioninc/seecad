from __future__ import annotations

import hashlib
import json
from pathlib import Path

import trimesh
from typer.testing import CliRunner

from seecad import cli as cli_module
from seecad.cli import _demo_spec, app
from seecad.config import Settings, get_settings
from seecad.engine import CompilationResult
from seecad.service import SeeCADService


class DemoEngine:
    def __init__(self) -> None:
        exported = trimesh.creation.box(extents=(86, 62, 24)).export(file_type="stl")
        self.mesh = exported if isinstance(exported, bytes) else exported.encode()

    def is_available(self) -> bool:
        return True

    def compile(self, _source: str, *, output_format: str = "stl") -> CompilationResult:
        return CompilationResult(
            content=self.mesh,
            format=output_format,
            engine="local",
            duration_seconds=0.01,
            diagnostics="test fixture",
        )


def test_demo_spec_preserves_positive_negative_channel_phases() -> None:
    spec = _demo_spec()
    assert spec.units == "mm"
    assert spec.positive_solids
    assert spec.negative_features
    assert spec.tool_access_channels


def test_demo_writes_source_artifacts_without_openscad(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv("SEECAD_DATA_DIR", str(tmp_path / "data"))  # type: ignore[attr-defined]
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "SEECAD_DATABASE_PATH", str(tmp_path / "data" / "index.sqlite3")
    )
    monkeypatch.setenv("SEECAD_OPENSCAD_MODE", "docker")  # type: ignore[attr-defined]
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "SEECAD_OPENSCAD_DOCKER_BINARY", "definitely-not-installed-docker"
    )
    get_settings.cache_clear()
    output = tmp_path / "demo"
    output.mkdir()
    (output / "model.stl").write_bytes(b"stale mesh")
    (output / "analysis.json").write_text("stale analysis")
    result = CliRunner().invoke(app, ["demo", "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert (output / "design.json").is_file()
    assert (output / "model.scad").read_text().count("difference()") == 1
    assert not (output / "model.stl").exists()
    assert not (output / "analysis.json").exists()
    assert not (output / "evidence-manifest.json").exists()


def test_demo_exports_a_digest_verified_final_analysis_bundle(
    tmp_path: Path, monkeypatch: object
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "index.sqlite3",
        openscad_mode="docker",
        nopscad_root=Path("vendor/NopSCADlib"),
    )
    service = SeeCADService(settings)
    service.engine = DemoEngine()  # type: ignore[assignment]
    monkeypatch.setattr(cli_module, "_service", lambda: service)  # type: ignore[attr-defined]
    output = tmp_path / "demo"

    result = CliRunner().invoke(app, ["demo", "--output", str(output)])

    assert result.exit_code == 0, result.output
    command_result = json.loads(result.output)
    manifest_bytes = (output / "evidence-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    entries = {entry["role"]: entry for entry in manifest["artifacts"]}
    assert set(entries) == {
        "spec",
        "scad",
        "manifest",
        "stl",
        "compile_stl",
        "analysis",
        "analysis_profile",
    }
    assert command_result["revision_id"] == manifest["revision_id"]
    assert command_result["evidence_manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    for entry in entries.values():
        artifact = output / entry["filename"]
        data = artifact.read_bytes()
        assert len(data) == entry["size_bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]

    history = service.get_design(command_result["design_id"])
    final_revision = history.revisions[-1]
    assert final_revision.revision_id == manifest["revision_id"]
    assert final_revision.metadata["event"] == "analyzed"
    assert {role: artifact.sha256 for role, artifact in final_revision.artifacts.items()} == {
        role: entry["sha256"] for role, entry in entries.items()
    }
