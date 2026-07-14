"""Model Context Protocol tools backed by the same immutable SeeCAD service."""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from seecad.config import get_settings
from seecad.models import (
    CompareRequest,
    CompileRequest,
    CreateDesignRequest,
    CreateRevisionRequest,
    DesignSpec,
    ImageEvidence,
    ProofSheetRequest,
)
from seecad.service import SeeCADService

mcp = FastMCP("SeeCAD")


@lru_cache(maxsize=1)
def _service() -> SeeCADService:
    return SeeCADService(get_settings())


@mcp.tool()
def create_design(
    prompt: str | None = None,
    spec: dict[str, Any] | None = None,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Create a design from exactly one natural-language prompt or semantic DesignSpec."""

    parsed = DesignSpec.model_validate(spec) if spec is not None else None
    request = CreateDesignRequest(
        prompt=prompt,
        spec=parsed,
        images=[ImageEvidence(url=url, detail="original") for url in image_urls or []],
    )
    return _service().create_design(request).model_dump(mode="json")


@mcp.tool()
def revise_design(
    design_id: str,
    parent_revision_id: str,
    prompt: str | None = None,
    spec: dict[str, Any] | None = None,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Append a child revision from exactly one instruction prompt or complete DesignSpec."""

    parsed = DesignSpec.model_validate(spec) if spec is not None else None
    request = CreateRevisionRequest(
        parent_revision_id=parent_revision_id,
        prompt=prompt,
        spec=parsed,
        images=[ImageEvidence(url=url, detail="original") for url in image_urls or []],
    )
    return _service().create_revision(design_id, request).model_dump(mode="json")


@mcp.tool()
def compile_design(
    design_id: str,
    revision_id: str,
    output_format: Literal["stl", "3mf"] = "stl",
) -> dict[str, Any]:
    """Compile a semantic revision in the bounded OpenSCAD worker."""

    return (
        _service()
        .compile_revision(design_id, revision_id, CompileRequest(format=output_format))
        .model_dump(mode="json")
    )


@mcp.tool()
def analyze_design(design_id: str, revision_id: str, auto_compile: bool = True) -> dict[str, Any]:
    """Return exact, bounded, heuristic, and unavailable DFM evidence."""

    return (
        _service()
        .analyze_revision(design_id, revision_id, auto_compile=auto_compile)
        .model_dump(mode="json")
    )


@mcp.tool()
def generate_proof_sheets(
    design_id: str,
    revision_id: str,
    view_count: int = 2048,
    resolution_px: int = 96,
    views_per_sheet: int = 64,
    auto_compile: bool = True,
) -> dict[str, Any]:
    """Explicitly render heuristic 2D proof sheets; this never runs automatically."""

    request = ProofSheetRequest(
        auto_compile=auto_compile,
        view_count=view_count,
        resolution_px=resolution_px,
        views_per_sheet=views_per_sheet,
    )
    return _service().generate_proof_sheets(design_id, revision_id, request).model_dump(mode="json")


@mcp.tool()
def get_design(design_id: str, revision_id: str | None = None) -> dict[str, Any]:
    """Read one immutable revision or the full design history."""

    service = _service()
    result = (
        service.get_revision(design_id, revision_id)
        if revision_id
        else service.get_design(design_id)
    )
    return result.model_dump(mode="json")


@mcp.tool()
def compare_designs(left_revision_id: str, right_revision_id: str) -> dict[str, Any]:
    """Compare semantic fields and artifact hashes for two revisions."""

    return (
        _service()
        .compare(
            CompareRequest(
                left_revision_id=left_revision_id,
                right_revision_id=right_revision_id,
            )
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def export_design(
    design_id: str,
    revision_id: str,
    artifact_format: Literal[
        "spec",
        "scad",
        "stl",
        "3mf",
        "analysis",
        "proof_sheet_manifest",
        "proof_sheets",
        "proof_sheet_archive",
    ] = "scad",
) -> dict[str, Any]:
    """Export metadata and inline only small artifacts; use HTTP for large derivatives."""

    data, artifact = _service().export_revision(design_id, revision_id, artifact_format)
    return {
        "artifact": artifact.model_dump(mode="json"),
        "encoding": "base64" if len(data) <= 256 * 1024 else None,
        "content": base64.b64encode(data).decode("ascii") if len(data) <= 256 * 1024 else None,
        "retrieval_path": f"/v1/artifacts/{artifact.sha256}",
    }


@mcp.tool()
def inspect_artifact(sha256: str, include_small_content: bool = False) -> dict[str, Any]:
    """Verify an artifact hash and return compact metadata, optionally inlining up to 256 KiB."""

    data, artifact = _service().get_artifact(sha256)
    include = include_small_content and len(data) <= 256 * 1024
    return {
        "sha256": artifact.sha256,
        "size_bytes": len(data),
        "integrity_verified": True,
        "encoding": "base64" if include else None,
        "content": base64.b64encode(data).decode("ascii") if include else None,
        "retrieval_path": f"/v1/artifacts/{artifact.sha256}",
    }


def run() -> None:
    mcp.run(transport="stdio")
