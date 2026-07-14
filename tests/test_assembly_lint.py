from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seecad.assembly_lint import AssemblyLintSpec, lint_assembly
from seecad.cli import app


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "name": "Accessible plate fastener",
        "intent": "Check one explicitly enumerated fastener and its driver approach.",
        "units": "mm",
        "parts": [
            {
                "id": "plate",
                "name": "Plate",
                "kind": "part",
                "purpose": "Fastener support",
                "source_file": "plate.stl",
                "envelope": {
                    "minimum": {"x": -10, "y": -10, "z": -5},
                    "maximum": {"x": 10, "y": 10, "z": 0},
                },
            },
            {
                "id": "plate_screw",
                "name": "Plate screw",
                "kind": "fastener",
                "purpose": "Retain the plate",
                "part_number": "M3x10",
                "envelope": {
                    "minimum": {"x": -1, "y": -1, "z": 0},
                    "maximum": {"x": 1, "y": 1, "z": 5},
                },
                "fastener": {
                    "designation": "M3x10 socket-head cap screw",
                    "drive": "2.5 mm hex key",
                    "confidence": "exact",
                    "basis": "Declared by the assembly author.",
                },
            },
        ],
        "tool_access_cones": [
            {
                "id": "plate_screw_driver",
                "name": "Plate screw hex-key approach",
                "fastener_id": "plate_screw",
                "tip": {"x": 0, "y": 0, "z": 5},
                "axis": {"x": 0, "y": 0, "z": 1},
                "reach_mm": 50,
                "tool_diameter_mm": 4,
                "clearance_mm": 0.5,
                "approach_half_angle_degrees": 2,
                "tool": "2.5 mm hex key",
                "rationale": "Driver approaches from above the plate.",
            }
        ],
        "assumptions": ["Envelopes are conservative millimetre AABBs."],
    }


def test_lint_enumerates_parts_fasteners_and_clear_tool_cones() -> None:
    report = lint_assembly(AssemblyLintSpec.model_validate(_manifest()))

    assert report.summary.status == "pass"
    assert report.summary.part_count == 2
    assert report.summary.part_family_count == 2
    assert report.summary.fastener_count == 1
    assert report.summary.accessible_fastener_count == 1
    assert [part.id for part in report.parts] == ["plate", "plate_screw"]
    assert report.fasteners[0].tool_cone_ids == ("plate_screw_driver",)
    assert report.tool_access_cones[0].status == "clear"
    assert report.tool_access_cones[0].tool == "2.5 mm hex key"
    assert report.tool_access_cones[0].reach_mm == 50


def test_lint_reports_bounded_obstruction_and_fails_fastener() -> None:
    manifest = _manifest()
    parts = manifest["parts"]
    assert isinstance(parts, list)
    parts.append(
        {
            "id": "cross_brace",
            "name": "Cross brace",
            "kind": "part",
            "purpose": "Deliberate driver obstruction",
            "envelope": {
                "minimum": {"x": -2, "y": -2, "z": 20},
                "maximum": {"x": 2, "y": 2, "z": 25},
            },
        }
    )

    report = lint_assembly(AssemblyLintSpec.model_validate(manifest))

    assert report.summary.status == "fail"
    assert report.summary.blocked_fastener_count == 1
    assert report.tool_access_cones[0].blocker_part_ids == ("cross_brace",)
    assert {diagnostic.code for diagnostic in report.diagnostics} == {
        "tool_cone_possible_obstruction",
        "fastener_not_tool_accessible",
    }


def test_alternative_clear_cone_keeps_fastener_accessible() -> None:
    manifest = _manifest()
    parts = manifest["parts"]
    cones = manifest["tool_access_cones"]
    assert isinstance(parts, list)
    assert isinstance(cones, list)
    parts.append(
        {
            "id": "cross_brace",
            "name": "Cross brace",
            "kind": "part",
            "purpose": "Block only the vertical approach",
            "envelope": {
                "minimum": {"x": -2, "y": -2, "z": 20},
                "maximum": {"x": 2, "y": 2, "z": 25},
            },
        }
    )
    side_cone = deepcopy(cones[0])
    assert isinstance(side_cone, dict)
    side_cone.update(
        {
            "id": "plate_screw_side_driver",
            "axis": {"x": 1, "y": 0, "z": 0},
            "rationale": "Alternative side approach.",
        }
    )
    cones.append(side_cone)

    report = lint_assembly(AssemblyLintSpec.model_validate(manifest))

    assert report.summary.status == "pass"
    assert report.summary.warning_count == 1
    assert report.fasteners[0].accessibility == "clear"
    assert [cone.status for cone in report.tool_access_cones] == ["blocked", "clear"]


def test_lint_cli_returns_json_and_stable_exit_codes(tmp_path: Path) -> None:
    valid_path = tmp_path / "assembly.json"
    valid_path.write_text(json.dumps(_manifest()))

    valid = CliRunner().invoke(app, ["lint", str(valid_path)])
    assert valid.exit_code == 0, valid.output
    assert json.loads(valid.output)["summary"]["status"] == "pass"

    missing_cone = _manifest()
    missing_cone["tool_access_cones"] = []
    invalid_path = tmp_path / "missing-cone.json"
    invalid_path.write_text(json.dumps(missing_cone))
    failed = CliRunner().invoke(app, ["lint", str(invalid_path), "--format", "text"])
    assert failed.exit_code == 1
    assert "fastener_missing_tool_cone" in failed.output

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("not json")
    malformed = CliRunner().invoke(app, ["lint", str(malformed_path)])
    assert malformed.exit_code == 2
    assert json.loads(malformed.output)["error"]["code"] == "invalid_assembly_manifest"


def test_lint_schema_is_machine_readable() -> None:
    result = CliRunner().invoke(app, ["lint-schema"])

    assert result.exit_code == 0, result.output
    schema = json.loads(result.output)
    assert schema["title"] == "AssemblyLintSpec"
    assert "parts" in schema["properties"]
    assert "tool_access_cones" in schema["properties"]


def test_robot_arm_reference_manifest_is_a_passing_instance_register() -> None:
    path = Path("examples/6dof_robot_arm/assembly.json")
    spec = AssemblyLintSpec.model_validate_json(path.read_text())

    report = lint_assembly(spec)

    assert report.summary.status == "pass"
    assert report.summary.part_count == 26
    assert report.summary.fastener_count == 10
    assert report.summary.tool_cone_count == 10
    assert report.summary.accessible_fastener_count == 10
    assert {part.source_file for part in report.parts if part.source_file} >= {
        "base.stp",
        "driveSmall.stp",
        "driveBig.stp",
        "connector_straight.stp",
        "connector_corner.stp",
    }


@pytest.mark.parametrize(
    (
        "fixture",
        "expected_part_count",
        "expected_accessibility",
        "expected_cone_blockers",
        "expected_diagnostic_codes",
    ),
    [
        (
            "blocked_top_cover_fastener",
            3,
            {"rear_mount_screw": "blocked"},
            {"rear_mount_screw_driver": ("cable_bridge",)},
            ["tool_cone_possible_obstruction", "fastener_not_tool_accessible"],
        ),
        (
            "blocked_alternative_approaches",
            4,
            {"clamp_bolt": "blocked"},
            {
                "clamp_bolt_straight_driver": ("fixed_splash_guard",),
                "clamp_bolt_angled_driver": ("vise_column",),
            },
            [
                "tool_cone_possible_obstruction",
                "tool_cone_possible_obstruction",
                "fastener_not_tool_accessible",
            ],
        ),
        (
            "mixed_service_panel_access",
            4,
            {"panel_screw_left": "blocked", "panel_screw_right": "clear"},
            {
                "panel_screw_left_driver": ("installed_cable_tray",),
                "panel_screw_right_driver": (),
            },
            ["tool_cone_possible_obstruction", "fastener_not_tool_accessible"],
        ),
    ],
)
def test_problem_assembly_fixtures_surface_expected_access_failures(
    fixture: str,
    expected_part_count: int,
    expected_accessibility: dict[str, str],
    expected_cone_blockers: dict[str, tuple[str, ...]],
    expected_diagnostic_codes: list[str],
) -> None:
    path = Path("examples") / fixture / "assembly.json"
    spec = AssemblyLintSpec.model_validate_json(path.read_text())

    report = lint_assembly(spec)

    assert report.summary.status == "fail"
    assert report.summary.part_count == expected_part_count
    assert report.summary.unchecked_fastener_count == 0
    assert {item.part_id: item.accessibility for item in report.fasteners} == (
        expected_accessibility
    )
    assert all(item.tool_cone_ids for item in report.fasteners)
    assert {item.cone_id: item.blocker_part_ids for item in report.tool_access_cones} == (
        expected_cone_blockers
    )
    assert [item.code for item in report.diagnostics] == expected_diagnostic_codes


def test_agent_contract_mandates_the_assembly_lint_route() -> None:
    agent_contract = Path("AGENTS.md").read_text()
    lint_contract = Path("docs/ASSEMBLY-LINT.md").read_text()

    assert "Assembly inspection routing (mandatory)" in agent_contract
    assert "docs/ASSEMBLY-LINT.md" in agent_contract
    assert "uv run seecad lint-schema" in agent_contract
    assert "DesignSpec.tool_access_channels" in agent_contract
    assert "AssemblyLintSpec.tool_access_cones" in agent_contract
    assert "Agent definition of done" in lint_contract
    assert "uv run seecad lint MANIFEST.json" in agent_contract
