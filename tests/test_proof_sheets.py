from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import trimesh
from test_service import make_service

from seecad.models import (
    ApprovalRequest,
    CompileRequest,
    CreateDesignRequest,
    DesignSpec,
    ProofSheetRequest,
)
from seecad.proof_sheets import build_proof_sheets, proof_sheet_directions


def _box_stl() -> bytes:
    exported = trimesh.creation.box(extents=(20, 12, 8)).export(file_type="stl")
    return exported if isinstance(exported, bytes) else exported.encode()


def test_proof_sheet_artifacts_are_deterministic_and_cover_thousands_of_views() -> None:
    stl = _box_stl()
    digest = hashlib.sha256(stl).hexdigest()
    arguments = {
        "design_name": "Proof box",
        "mesh_sha256": digest,
        "view_count": 1024,
        "resolution_px": 64,
        "views_per_sheet": 64,
    }

    first = build_proof_sheets(stl, **arguments)
    second = build_proof_sheets(stl, **arguments)
    manifest = json.loads(first.manifest)

    assert first == second
    assert manifest["units"] == "mm"
    assert manifest["confidence"] == "heuristic"
    assert manifest["projection_count"] == 1024
    assert manifest["sheet_count"] == 16
    assert manifest["projections"][0]["label"] == "right"
    assert manifest["projections"][25]["label"].startswith("edge_")
    assert manifest["projections"][26]["label"] == "fibonacci"
    assert b"do not prove collision clearance" in first.review_html
    assert b"1,024 deterministic orthographic projections" in first.review_html

    with zipfile.ZipFile(io.BytesIO(first.archive)) as archive:
        names = archive.namelist()
        assert names[:2] == ["index.html", "proof-sheet-manifest.json"]
        assert len(names) == 1026
        assert archive.read("proof-sheet-manifest.json") == first.manifest
        sample_png = archive.read("projections/view-0026.png")
    assert hashlib.sha256(sample_png).hexdigest() == manifest["projections"][26]["png_sha256"]

    directions = proof_sheet_directions(1024)
    assert len(directions) == 1024
    for _view_id, _label, direction in directions:
        magnitude = sum(value * value for value in direction) ** 0.5
        assert abs(magnitude - 1.0) < 1e-12


def test_proof_sheets_create_an_immutable_review_revision_and_remain_approvable(
    tmp_path: Path, simple_spec: DesignSpec
) -> None:
    service, _engine = make_service(tmp_path)
    created = service.create_design(CreateDesignRequest(spec=simple_spec))
    compiled = service.compile_revision(
        created.design_id, created.revision_id, CompileRequest(format="stl")
    )
    analyzed = service.analyze_revision(
        compiled.design_id, compiled.revision_id, auto_compile=False
    ).revision

    proof_revision = service.generate_proof_sheets(
        analyzed.design_id,
        analyzed.revision_id,
        ProofSheetRequest(view_count=1024, resolution_px=64, views_per_sheet=64),
    )

    assert proof_revision.parent_revision_id == analyzed.revision_id
    assert proof_revision.metadata["event"] == "proof_sheets_generated"
    assert proof_revision.metadata["proof_sheet_confidence"] == "heuristic"
    assert proof_revision.metadata["proof_sheet_projection_count"] == 1024
    assert set(proof_revision.artifacts) >= {
        "proof_sheet_manifest",
        "proof_sheets",
        "proof_sheet_archive",
    }
    assert proof_revision.artifacts["proof_sheets"].media_type == "text/html; charset=utf-8"

    cached = service.generate_proof_sheets(
        analyzed.design_id,
        analyzed.revision_id,
        ProofSheetRequest(view_count=1024, resolution_px=64, views_per_sheet=64),
    )
    assert cached.revision_id == proof_revision.revision_id

    approved = service.approve_revision(
        proof_revision.design_id,
        proof_revision.revision_id,
        ApprovalRequest(attestor="Reviewer", statement="Reviewed compiled and visual evidence."),
    )
    assert approved.parent_revision_id == proof_revision.revision_id
    assert "approval" in approved.artifacts

    bundle = service.export_evidence_bundle(proof_revision.design_id, proof_revision.revision_id)
    bundle_roles = {entry["role"] for entry in json.loads(bundle.manifest)["artifacts"]}
    assert {
        "proof_sheet_manifest",
        "proof_sheets",
        "proof_sheet_archive",
    }.issubset(bundle_roles)
