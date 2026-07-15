from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import trimesh
from typer.testing import CliRunner

from seecad.cli import app
from seecad.mcp_server import observe_source_payloads as observe_source_payloads_mcp
from seecad.models import Confidence
from seecad.source_observe import observe_source_payloads, observe_sources


def _export(mesh: trimesh.Trimesh | trimesh.Scene, file_type: str) -> bytes:
    exported: Any = mesh.export(file_type=file_type)
    if isinstance(exported, bytes):
        return exported
    if isinstance(exported, str):
        return exported.encode()
    raise TypeError(f"unexpected export payload for {file_type}")


def test_observe_single_mesh_reports_digest_bounds_and_mesh_lint_route(tmp_path: Path) -> None:
    mesh_path = tmp_path / "box.stl"
    content = _export(trimesh.creation.box(extents=(10, 20, 30)), "stl")
    mesh_path.write_bytes(content)

    report = observe_sources([mesh_path], declared_units="mm")

    source = report.files[0]
    instance = source.geometry_instances[0]
    assert report.summary.route_hint == "mesh_lint_candidate"
    assert report.summary.geometry_instance_count == 1
    assert source.status == "observed"
    assert source.sha256 == hashlib.sha256(content).hexdigest()
    assert source.units is not None
    assert source.units.coordinate_unit_label == "mm"
    assert source.units.confidence == Confidence.EXACT
    assert source.units.unit_conflict is False
    assert instance.bounds.minimum == pytest.approx((-5, -10, -15))
    assert instance.bounds.maximum == pytest.approx((5, 10, 15))
    assert instance.bounds.extents == pytest.approx((10, 20, 30))


def test_observe_multi_instance_scene_preserves_transforms_and_routes_to_review(
    tmp_path: Path,
) -> None:
    scene = trimesh.Scene()
    scene.add_geometry(
        trimesh.creation.box(extents=(1, 2, 3)),
        geom_name="left_geom",
        node_name="left",
    )
    scene.add_geometry(
        trimesh.creation.box(extents=(2, 2, 2)),
        geom_name="right_geom",
        node_name="right",
        transform=np.array(
            (
                (1.0, 0.0, 0.0, 10.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0, 1.0),
            )
        ),
    )
    scene_path = tmp_path / "assembly.glb"
    scene_path.write_bytes(_export(scene, "glb"))

    report = observe_sources([scene_path])

    assert report.summary.route_hint == "assembly_evidence_review"
    assert report.summary.geometry_instance_count == 2
    source = report.files[0]
    assert source.status == "observed"
    assert source.units is not None
    assert source.units.coordinate_unit_label == "meters"
    instances = {instance.id: instance for instance in source.geometry_instances}
    assert set(instances) == {"left", "right"}
    assert instances["left"].bounds.extents == pytest.approx((1, 2, 3))
    assert instances["right"].bounds.minimum == pytest.approx((9, -1, -1))
    assert instances["right"].bounds.maximum == pytest.approx((11, 1, 1))


def test_observe_reports_unit_conflict_without_silently_normalizing(tmp_path: Path) -> None:
    scene_path = tmp_path / "meter_scene.glb"
    scene_path.write_bytes(_export(trimesh.creation.box(extents=(1, 1, 1)), "glb"))

    report = observe_sources([scene_path], declared_units="mm")

    source = report.files[0]
    assert report.summary.unit_conflict_count == 1
    assert source.units is not None
    assert source.units.unit_conflict is True
    assert source.units.confidence == Confidence.UNAVAILABLE
    assert source.units.coordinate_unit_label == "source coordinates"


def test_observe_reports_unsupported_files_without_failing_the_bundle(tmp_path: Path) -> None:
    step_path = tmp_path / "vendor_part.step"
    step_path.write_text("ISO-10303-21;", encoding="utf-8")

    report = observe_sources([step_path])

    source = report.files[0]
    assert report.summary.route_hint == "no_supported_geometry"
    assert source.status == "unsupported_format"
    assert source.format == "unsupported"
    assert source.sha256 == hashlib.sha256(step_path.read_bytes()).hexdigest()


def test_observe_source_payloads_matches_file_observation() -> None:
    content = _export(trimesh.creation.box(extents=(3, 4, 5)), "stl")

    report = observe_source_payloads([("payload.stl", content)], declared_units="mm")

    assert report.summary.route_hint == "mesh_lint_candidate"
    assert report.files[0].sha256 == hashlib.sha256(content).hexdigest()
    assert report.files[0].geometry_instances[0].bounds.extents == pytest.approx((3, 4, 5))


def test_mcp_observe_source_payloads_accepts_bounded_base64_payload() -> None:
    content = _export(trimesh.creation.box(extents=(3, 4, 5)), "stl")

    report = observe_source_payloads_mcp(
        [{"filename": "payload.stl", "content_base64": base64.b64encode(content).decode()}],
        declared_units="mm",
    )

    assert report["summary"]["route_hint"] == "mesh_lint_candidate"
    assert report["files"][0]["sha256"] == hashlib.sha256(content).hexdigest()


def test_observe_cli_emits_json_and_text(tmp_path: Path) -> None:
    mesh_path = tmp_path / "part.stl"
    mesh_path.write_bytes(_export(trimesh.creation.box(extents=(4, 5, 6)), "stl"))

    result = CliRunner().invoke(app, ["observe", str(mesh_path), "--units", "mm"])

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["schema_version"] == "1.0"
    assert report["summary"]["route_hint"] == "mesh_lint_candidate"
    assert report["files"][0]["units"]["coordinate_unit_label"] == "mm"

    text = CliRunner().invoke(app, ["observe", str(mesh_path), "--format", "text"])
    assert text.exit_code == 0, text.output
    assert "SOURCE OBSERVATION" in text.output
    assert "route=mesh_lint_candidate" in text.output


def test_source_observation_documentation_keeps_authority_boundary() -> None:
    doc = Path("docs/SOURCE-OBSERVATION.md").read_text(encoding="utf-8")

    assert "uv run seecad observe" in doc
    assert "not a physical-instance inventory" in doc
    assert "AssemblyLintSpec" in doc
