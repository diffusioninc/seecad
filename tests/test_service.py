from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import trimesh

from seecad.config import Settings
from seecad.engine import CompilationProvenance, CompilationResult
from seecad.errors import ConflictError
from seecad.models import (
    ApprovalRequest,
    CompareRequest,
    CompileRequest,
    CreateDesignRequest,
    CreateRevisionRequest,
    DesignSpec,
    PlannedDesign,
    PrintProfile,
    Vec3,
    canonical_print_profile_bytes,
    print_profile_sha256,
)
from seecad.service import SeeCADService


class NeverPlanner:
    configured = False

    def plan(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("explicit DesignSpec path must not call OpenAI")


class FakeEngine:
    def __init__(self) -> None:
        exported = trimesh.creation.box(extents=(20, 12, 8)).export(file_type="stl")
        self.mesh = exported if isinstance(exported, bytes) else exported.encode()
        self.sources: list[str] = []

    def is_available(self) -> bool:
        return True

    def compile(self, source: str, *, output_format: str = "stl") -> CompilationResult:
        self.sources.append(source)
        return CompilationResult(
            content=self.mesh,
            format="stl",
            engine="local",
            duration_seconds=0.01,
            diagnostics="fixture",
        )


class FakeRemoteEngine(FakeEngine):
    def compile(self, source: str, *, output_format: str = "stl") -> CompilationResult:
        self.sources.append(source)
        source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return CompilationResult(
            content=self.mesh,
            format="stl",
            engine="remote",
            duration_seconds=0.01,
            diagnostics="fixture",
            provenance=CompilationProvenance(
                protocol="1",
                worker_build_id="test-worker",
                openscad_version="OpenSCAD 2021.01",
                nopscad_revision="a" * 40,
                nopscad_tree_sha256="b" * 64,
                source_sha256=source_sha256,
            ),
        )


def make_service(tmp_path: Path) -> tuple[SeeCADService, FakeEngine]:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "index.sqlite3",
        openscad_mode="docker",
        nopscad_root=Path("vendor/NopSCADlib"),
    )
    engine = FakeEngine()
    service = SeeCADService(settings, planner=NeverPlanner(), engine=engine)  # type: ignore[arg-type]
    return service, engine


def test_explicit_spec_create_compile_analyze_vertical_slice(
    tmp_path: Path, simple_spec: DesignSpec
) -> None:
    service, engine = make_service(tmp_path)
    created = service.create_design(CreateDesignRequest(spec=simple_spec))
    assert set(created.artifacts) >= {"spec", "scad", "manifest"}
    assert created.metadata["source"] == "explicit_spec"
    compiled = service.compile_revision(
        created.design_id, created.revision_id, CompileRequest(format="stl")
    )
    assert compiled.parent_revision_id == created.revision_id
    assert "stl" in compiled.artifacts
    assert isinstance(engine.sources[0], str)
    analyzed = service.analyze_revision(
        compiled.design_id, compiled.revision_id, auto_compile=False
    )
    assert analyzed.revision.parent_revision_id == compiled.revision_id
    assert analyzed.analysis.mesh_sha256 == compiled.artifacts["stl"].sha256
    assert any(metric.confidence == "exact" for metric in analyzed.analysis.measurements)
    measurements = {metric.name: metric for metric in analyzed.analysis.measurements}
    assert measurements["triangle_count"].value == 12
    assert measurements["triangle_count"].confidence == "exact"
    assert measurements["vertex_count"].value == 8
    assert measurements["vertex_count"].confidence == "exact"
    assert measurements["degenerate_triangle_count"].value == 0
    assert measurements["degenerate_triangle_count"].confidence == "bounded"
    assert "tolerance" in measurements["degenerate_triangle_count"].basis


def test_evidence_bundle_is_bound_to_the_final_analyzed_revision(
    tmp_path: Path, simple_spec: DesignSpec
) -> None:
    service, _engine = make_service(tmp_path)
    created = service.create_design(CreateDesignRequest(spec=simple_spec))
    compiled = service.compile_revision(
        created.design_id, created.revision_id, CompileRequest(format="stl")
    )
    analyzed = service.analyze_revision(
        compiled.design_id, compiled.revision_id, auto_compile=False
    )

    bundle = service.export_evidence_bundle(
        analyzed.revision.design_id, analyzed.revision.revision_id
    )
    manifest = json.loads(bundle.manifest)
    expected_roles = {
        "spec",
        "scad",
        "manifest",
        "stl",
        "compile_stl",
        "analysis",
        "analysis_profile",
    }

    assert bundle.revision.revision_id == analyzed.revision.revision_id
    assert bundle.manifest_sha256 == hashlib.sha256(bundle.manifest).hexdigest()
    assert manifest["design_id"] == created.design_id
    assert manifest["revision_id"] == analyzed.revision.revision_id
    assert manifest["parent_revision_id"] == compiled.revision_id
    assert manifest["source_revision_id"] == created.revision_id
    assert [entry["revision_id"] for entry in manifest["revision_chain"]] == [
        created.revision_id,
        compiled.revision_id,
        analyzed.revision.revision_id,
    ]
    assert [entry["event"] for entry in manifest["revision_chain"]] == [
        "created",
        "compiled",
        "analyzed",
    ]

    entries = {entry["role"]: entry for entry in manifest["artifacts"]}
    assert set(entries) == expected_roles
    for role, entry in entries.items():
        artifact = analyzed.revision.artifacts[role]
        data = bundle.files[entry["filename"]]
        assert entry == {
            "role": role,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "media_type": artifact.media_type,
            "filename": artifact.filename,
            "revision_id": analyzed.revision.revision_id,
            "introduced_revision_id": (
                created.revision_id
                if role in {"spec", "scad", "manifest"}
                else compiled.revision_id
                if role in {"stl", "compile_stl"}
                else analyzed.revision.revision_id
            ),
        }
        assert len(data) == artifact.size_bytes
        assert hashlib.sha256(data).hexdigest() == artifact.sha256

    assert json.loads(bundle.files["compile-stl.json"])["output_sha256"] == entries["stl"]["sha256"]
    assert json.loads(bundle.files["analysis.json"])["mesh_sha256"] == entries["stl"]["sha256"]
    assert (
        json.loads(bundle.files["analysis.json"])["print_profile_sha256"]
        == entries["analysis_profile"]["sha256"]
    )


def test_evidence_bundle_rejects_non_analyzed_revision(
    tmp_path: Path, simple_spec: DesignSpec
) -> None:
    service, _engine = make_service(tmp_path)
    created = service.create_design(CreateDesignRequest(spec=simple_spec))

    with pytest.raises(ConflictError, match="requires an analyzed revision"):
        service.export_evidence_bundle(created.design_id, created.revision_id)


def test_child_revision_and_comparison(tmp_path: Path, simple_spec: DesignSpec) -> None:
    service, _engine = make_service(tmp_path)
    root = service.create_design(CreateDesignRequest(spec=simple_spec))
    child = service.create_revision(
        root.design_id,
        CreateRevisionRequest(parent_revision_id=root.revision_id, spec=simple_spec),
    )
    assert child.design_id == root.design_id
    assert child.parent_revision_id == root.revision_id
    comparison = service.compare(
        CompareRequest(left_revision_id=root.revision_id, right_revision_id=child.revision_id)
    )
    assert comparison.same_spec is True


def test_manifest_contains_nop_provenance_boundary(tmp_path: Path, simple_spec: DesignSpec) -> None:
    service, _engine = make_service(tmp_path)
    revision = service.create_design(CreateDesignRequest(spec=simple_spec))
    manifest = service.artifacts.get(revision.artifacts["manifest"].sha256)
    assert b'"boolean_strategy":"single_negative_difference_pass"' in manifest


def test_remote_compile_report_persists_verified_worker_provenance(
    tmp_path: Path, simple_spec: DesignSpec
) -> None:
    service, _engine = make_service(tmp_path)
    service.engine = FakeRemoteEngine()  # type: ignore[assignment]
    created = service.create_design(CreateDesignRequest(spec=simple_spec))
    compiled = service.compile_revision(
        created.design_id, created.revision_id, CompileRequest(format="stl")
    )
    report = json.loads(service.artifacts.get(compiled.artifacts["compile_stl"].sha256))

    assert report["source_sha256"] == created.artifacts["scad"].sha256
    assert report["provenance"] == {
        "protocol": "1",
        "worker_build_id": "test-worker",
        "openscad_version": "OpenSCAD 2021.01",
        "nopscad_revision": "a" * 40,
        "nopscad_tree_sha256": "b" * 64,
        "source_sha256": created.artifacts["scad"].sha256,
    }


def test_analysis_profile_is_canonical_evidence_and_cache_key(
    tmp_path: Path, simple_spec: DesignSpec
) -> None:
    service, _engine = make_service(tmp_path)
    created = service.create_design(CreateDesignRequest(spec=simple_spec))
    compiled = service.compile_revision(
        created.design_id, created.revision_id, CompileRequest(format="stl")
    )
    first_profile = PrintProfile(
        process="fdm",
        material="PETG",
        nozzle_diameter=0.6,
        layer_height=0.3,
        minimum_wall=1.8,
        minimum_clearance=0.35,
        maximum_unsupported_overhang_degrees=50,
        build_volume=Vec3(x=300, y=250, z=200),
    )
    first = service.analyze_revision(
        compiled.design_id,
        compiled.revision_id,
        auto_compile=False,
        profile=first_profile,
    )
    first_digest = print_profile_sha256(first_profile)
    assert first.analysis.print_profile == first_profile
    assert first.analysis.print_profile_sha256 == first_digest
    assert first.revision.artifacts["analysis_profile"].sha256 == first_digest
    assert service.artifacts.get(
        first.revision.artifacts["analysis_profile"].sha256
    ) == canonical_print_profile_bytes(first_profile)

    cached = service.analyze_revision(
        first.revision.design_id,
        first.revision.revision_id,
        auto_compile=False,
        profile=first_profile,
    )
    assert cached.revision.revision_id == first.revision.revision_id

    cached_from_parent = service.analyze_revision(
        compiled.design_id,
        compiled.revision_id,
        auto_compile=False,
        profile=first_profile,
    )
    assert cached_from_parent.revision.revision_id == first.revision.revision_id

    changed_profile = first_profile.model_copy(update={"minimum_wall": 2.4})
    changed = service.analyze_revision(
        first.revision.design_id,
        first.revision.revision_id,
        auto_compile=False,
        profile=changed_profile,
    )
    assert changed.revision.revision_id != first.revision.revision_id
    assert changed.revision.parent_revision_id == first.revision.revision_id
    assert changed.analysis.print_profile == changed_profile
    assert changed.analysis.print_profile_sha256 == print_profile_sha256(changed_profile)
    assert changed.revision.metadata["analysis_profile_sha256"] == print_profile_sha256(
        changed_profile
    )


def test_planner_receives_and_records_typed_workbench_constraints(
    tmp_path: Path, simple_spec: DesignSpec
) -> None:
    class CapturePlanner:
        configured = True

        def __init__(self) -> None:
            self.prompt = ""

        def plan(self, prompt: str, **_kwargs: object) -> PlannedDesign:
            self.prompt = prompt
            return PlannedDesign(spec=simple_spec, rationale="Captured constraints.")

    planner = CapturePlanner()
    service, _engine = make_service(tmp_path)
    service.planner = planner  # type: ignore[assignment]
    profile = PrintProfile(
        process="fdm",
        material="PA-CF",
        nozzle_diameter=0.6,
        layer_height=0.25,
        minimum_wall=2.2,
        minimum_clearance=0.4,
        maximum_unsupported_overhang_degrees=42,
        build_volume=Vec3(x=350, y=350, z=400),
    )
    created = service.create_design(
        CreateDesignRequest(
            prompt="Make a load-bearing service bracket.",
            requested_profile=profile,
            load_case="18 kg static vertical load, 3x design factor",
            dimensional_tolerance=0.2,
            infill_percent=45,
        )
    )

    assert created.spec.print_profile == profile
    assert "REQUESTED_MANUFACTURING_CONSTRAINTS:" in planner.prompt
    assert '"material":"PA-CF"' in planner.prompt
    assert '"nozzle_diameter":0.6' in planner.prompt
    assert '"layer_height":0.25' in planner.prompt
    assert '"minimum_wall":2.2' in planner.prompt
    assert '"minimum_clearance":0.4' in planner.prompt
    assert '"maximum_unsupported_overhang_degrees":42.0' in planner.prompt
    assert '"build_volume":{"x":350.0,"y":350.0,"z":400.0}' in planner.prompt
    assert "LOAD_CASE: 18 kg static vertical load, 3x design factor" in planner.prompt
    assert "DIMENSIONAL_TOLERANCE_MM: 0.20000000000000001" in planner.prompt
    assert "INFILL_PERCENT: 45" in planner.prompt
    assert service.artifacts.get(created.artifacts["prompt"].sha256).decode() == planner.prompt
    assert created.metadata["requested_profile_sha256"] == print_profile_sha256(profile)


def test_approval_attests_to_and_preserves_complete_parent_evidence(
    tmp_path: Path, simple_spec: DesignSpec
) -> None:
    service, _engine = make_service(tmp_path)
    created = service.create_design(CreateDesignRequest(spec=simple_spec))
    compiled = service.compile_revision(
        created.design_id, created.revision_id, CompileRequest(format="stl")
    )
    with pytest.raises(ConflictError, match="only available"):
        service.approve_revision(
            compiled.design_id,
            compiled.revision_id,
            ApprovalRequest(attestor="Reviewer", statement="Reviewed."),
        )

    analyzed = service.analyze_revision(
        compiled.design_id, compiled.revision_id, auto_compile=False
    )
    approved = service.approve_revision(
        analyzed.revision.design_id,
        analyzed.revision.revision_id,
        ApprovalRequest(attestor="Reviewer", statement="Reviewed exact evidence."),
    )
    assert approved.parent_revision_id == analyzed.revision.revision_id
    assert approved.spec == analyzed.revision.spec
    assert approved.metadata["event"] == "approved"
    assert set(approved.artifacts) == {*analyzed.revision.artifacts, "approval"}
    for role, artifact in analyzed.revision.artifacts.items():
        assert approved.artifacts[role] == artifact

    attestation = json.loads(service.artifacts.get(approved.artifacts["approval"].sha256))
    assert attestation["parent_revision_id"] == analyzed.revision.revision_id
    assert attestation["parent_spec_sha256"] == analyzed.revision.artifacts["spec"].sha256
    assert attestation["mesh_sha256"] == analyzed.revision.artifacts["stl"].sha256
    assert attestation["compile_report_sha256"] == analyzed.revision.artifacts["compile_stl"].sha256
    assert attestation["analysis_sha256"] == analyzed.revision.artifacts["analysis"].sha256
    assert attestation["parent_artifact_sha256"] == {
        role: artifact.sha256 for role, artifact in sorted(analyzed.revision.artifacts.items())
    }

    compiled_again = service.compile_revision(
        approved.design_id,
        approved.revision_id,
        CompileRequest(format="stl"),
    )
    assert compiled_again.revision_id == approved.revision_id
    assert compiled_again.metadata["event"] == "approved"
    assert compiled_again.artifacts == approved.artifacts

    analyzed_again = service.analyze_revision(
        approved.design_id,
        approved.revision_id,
        auto_compile=False,
        profile=analyzed.analysis.print_profile,
    )
    assert analyzed_again.revision.revision_id == approved.revision_id
    assert analyzed_again.revision.metadata["event"] == "approved"
    assert analyzed_again.revision.artifacts == approved.artifacts
