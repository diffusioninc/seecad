from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import trimesh
from typer.testing import CliRunner

from seecad.cli import app
from seecad.mesh_lint import lint_mesh_bytes
from seecad.models import PrintProfile


def _profile() -> PrintProfile:
    return PrintProfile.model_validate_json(
        Path("examples/mesh_lint/fdm-profile.json").read_text(encoding="utf-8")
    )


def _export(mesh: trimesh.Trimesh | trimesh.Scene, file_type: str) -> bytes:
    exported = mesh.export(file_type=file_type)
    return exported if isinstance(exported, bytes) else exported.encode()


def _write_profile(tmp_path: Path) -> Path:
    path = tmp_path / "profile.json"
    path.write_text(_profile().model_dump_json(indent=2), encoding="utf-8")
    return path


def test_mesh_lint_reports_digest_topology_and_ranked_orientations() -> None:
    content = _export(trimesh.creation.box(extents=(10, 20, 30)), "stl")

    report = lint_mesh_bytes(
        content,
        filename="box.stl",
        mesh_format="stl",
        profile=_profile(),
    )

    measurements = {item.name: item for item in report.analysis.measurements}
    assert report.scope == "single_mesh"
    assert report.units == "mm"
    assert report.source.sha256 == hashlib.sha256(content).hexdigest()
    assert report.summary.status == "pass"
    assert report.summary.orientations_evaluated == 24
    assert len(report.orientation_candidates) == 6
    assert measurements["triangle_count"].value == 12
    assert measurements["watertight"].value is True
    assert measurements["downward_overhang_area_ratio"].value == pytest.approx(0.0)
    assert report.orientation_candidates[0].height_mm == pytest.approx(10.0)
    assert report.orientation_candidates[0].fits_build_volume is True
    assert report.orientation_candidates[0].fit_confidence == "bounded"
    assert report.orientation_candidates[0].overhang_confidence == "heuristic"


@pytest.mark.parametrize("file_type", ["stl", "obj", "ply", "off", "glb", "3mf"])
def test_mesh_lint_accepts_supported_single_mesh_formats(file_type: str) -> None:
    # glTF declares metres; other checked fixtures use millimetre coordinates.
    extents = (0.01, 0.02, 0.03) if file_type == "glb" else (10, 20, 30)
    mesh = trimesh.creation.box(extents=extents)
    content = _export(mesh, file_type)

    report = lint_mesh_bytes(
        content,
        filename=f"box.{file_type}",
        mesh_format=file_type,  # type: ignore[arg-type]
        profile=_profile(),
        orientation_limit=1,
    )

    assert report.source.format == file_type
    assert report.source.scale_factor_to_mm == (1000.0 if file_type == "glb" else 1.0)
    assert report.summary.status == "pass"
    assert report.summary.orientation_candidates_returned == 1


def test_mesh_lint_cli_emits_machine_readable_report(tmp_path: Path) -> None:
    mesh_path = tmp_path / "part.stl"
    content = _export(trimesh.creation.box(extents=(10, 20, 30)), "stl")
    mesh_path.write_bytes(content)

    result = CliRunner().invoke(
        app,
        [
            "mesh-lint",
            str(mesh_path),
            "--units",
            "mm",
            "--profile",
            str(_write_profile(tmp_path)),
            "--orientation-candidates",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["schema_version"] == "1.0"
    assert report["source"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert report["source"]["declared_units"] == "mm"
    assert report["summary"]["orientation_candidates_returned"] == 3


def test_mesh_lint_cli_requires_explicit_millimetres(tmp_path: Path) -> None:
    mesh_path = tmp_path / "part.stl"
    mesh_path.write_bytes(_export(trimesh.creation.box(), "stl"))

    result = CliRunner().invoke(
        app,
        [
            "mesh-lint",
            str(mesh_path),
            "--units",
            "inch",
            "--profile",
            str(_write_profile(tmp_path)),
        ],
    )

    assert result.exit_code == 2
    assert json.loads(result.output)["error"]["code"] == "invalid_mesh_units"


def test_mesh_lint_cli_can_fail_on_warning(tmp_path: Path) -> None:
    left = trimesh.creation.box(extents=(10, 10, 10))
    right = trimesh.creation.box(extents=(10, 10, 10))
    right.apply_translation((20, 0, 0))
    mesh_path = tmp_path / "disconnected.stl"
    mesh_path.write_bytes(_export(trimesh.util.concatenate((left, right)), "stl"))

    result = CliRunner().invoke(
        app,
        [
            "mesh-lint",
            str(mesh_path),
            "--units",
            "mm",
            "--profile",
            str(_write_profile(tmp_path)),
            "--fail-on",
            "warning",
        ],
    )

    assert result.exit_code == 1, result.output
    report = json.loads(result.output)
    assert report["summary"]["status"] == "pass"
    assert report["summary"]["warning_count"] >= 1
    assert any(item["code"] == "multiple_components" for item in report["analysis"]["findings"])


def test_mesh_lint_rejects_multi_instance_scene_and_routes_to_assembly_lint(
    tmp_path: Path,
) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(), node_name="left")
    scene.add_geometry(
        trimesh.creation.box(),
        node_name="right",
        transform=trimesh.transformations.translation_matrix((2, 0, 0)),
    )
    mesh_path = tmp_path / "assembly.glb"
    mesh_path.write_bytes(_export(scene, "glb"))

    result = CliRunner().invoke(
        app,
        [
            "mesh-lint",
            str(mesh_path),
            "--units",
            "mm",
            "--profile",
            str(_write_profile(tmp_path)),
        ],
    )

    assert result.exit_code == 2, result.output
    error = json.loads(result.output)["error"]
    assert error["code"] == "analysis_failed"
    assert error["details"]["required_workflow"] == "seecad lint"


def test_mesh_lint_profile_schema_is_agent_discoverable() -> None:
    result = CliRunner().invoke(app, ["mesh-lint-profile-schema"])

    assert result.exit_code == 0, result.output
    schema = json.loads(result.output)
    assert set(schema["properties"]) >= {"process", "build_volume", "minimum_wall"}
