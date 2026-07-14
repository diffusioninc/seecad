"""Standalone single-mesh linting and bounded build-orientation review."""

from __future__ import annotations

import hashlib
import itertools
import math
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import Field, StringConstraints

from seecad.analysis import MeshAnalyzer, load_triangle_mesh
from seecad.errors import AnalysisError
from seecad.models import Confidence, MeshAnalysis, PrintProfile, Severity, StrictModel

MAX_MESH_BYTES = 128 * 1024 * 1024
MeshFormat = Literal["stl", "obj", "ply", "off", "glb", "3mf"]
SUPPORTED_MESH_FORMATS: dict[str, MeshFormat] = {
    ".stl": "stl",
    ".obj": "obj",
    ".ply": "ply",
    ".off": "off",
    ".glb": "glb",
    ".3mf": "3mf",
}


class MeshSourceEvidence(StrictModel):
    filename: str = Field(min_length=1, max_length=240)
    format: MeshFormat
    sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    size_bytes: int = Field(ge=1, le=MAX_MESH_BYTES)
    declared_units: Literal["mm"] = "mm"
    embedded_units: str | None = None
    scale_factor_to_mm: float = Field(gt=0)
    normalization_confidence: Literal[Confidence.EXACT] = Confidence.EXACT


class OrientationCandidate(StrictModel):
    rank: int = Field(ge=1, le=24)
    rotation_degrees_xyz: tuple[int, int, int]
    is_current_orientation: bool
    bounds_extents_mm: tuple[float, float, float]
    height_mm: float = Field(ge=0)
    fits_build_volume: bool
    fit_confidence: Literal[Confidence.BOUNDED] = Confidence.BOUNDED
    downward_overhang_area_ratio: float = Field(ge=0, le=1)
    overhang_confidence: Literal[Confidence.HEURISTIC] = Confidence.HEURISTIC


class MeshLintSummary(StrictModel):
    status: Literal["pass", "fail"]
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)
    orientations_evaluated: Literal[24] = 24
    orientation_candidates_returned: int = Field(ge=1, le=24)


class MeshLintReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    scope: Literal["single_mesh"] = "single_mesh"
    units: Literal["mm"] = "mm"
    source: MeshSourceEvidence
    summary: MeshLintSummary
    analysis: MeshAnalysis
    orientation_candidates: tuple[OrientationCandidate, ...]
    limitations: tuple[str, ...]


def mesh_format_from_path(path: Path) -> MeshFormat:
    """Resolve a deliberately small, in-memory-safe mesh format allowlist."""

    mesh_format = SUPPORTED_MESH_FORMATS.get(path.suffix.lower())
    if mesh_format is None:
        raise AnalysisError(
            "unsupported mesh format",
            details={
                "filename": path.name,
                "supported_extensions": sorted(SUPPORTED_MESH_FORMATS),
            },
        )
    return mesh_format


def _embedded_units(mesh: Any) -> str | None:
    try:
        value = mesh.units
    except (AttributeError, TypeError, ValueError):
        return None
    return str(value) if value else None


def _normalize_mesh_to_millimetres(mesh: Any, embedded_units: str | None) -> float:
    """Apply a deterministic metadata-backed scale while leaving the source bytes untouched."""

    if embedded_units is None:
        return 1.0
    normalized = embedded_units.lower().strip()
    if normalized in {"mm", "millimeter", "millimeters", "millimetre", "millimetres"}:
        return 1.0
    try:
        import trimesh

        scale_factor = float(trimesh.units.unit_conversion(embedded_units, "millimeters"))
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalysisError(
            "embedded model units cannot be normalized to millimetres",
            details={"embedded_units": embedded_units, "required_units": "mm"},
        ) from exc
    mesh.apply_scale(scale_factor)
    mesh.units = "millimeters"
    return scale_factor


def _rotation_matrix_xyz(rotation: tuple[int, int, int]) -> Any:
    import numpy as np

    rx, ry, rz = (math.radians(value) for value in rotation)
    rotate_x = np.array(
        ((1.0, 0.0, 0.0), (0.0, math.cos(rx), -math.sin(rx)), (0.0, math.sin(rx), math.cos(rx)))
    )
    rotate_y = np.array(
        ((math.cos(ry), 0.0, math.sin(ry)), (0.0, 1.0, 0.0), (-math.sin(ry), 0.0, math.cos(ry)))
    )
    rotate_z = np.array(
        ((math.cos(rz), -math.sin(rz), 0.0), (math.sin(rz), math.cos(rz), 0.0), (0.0, 0.0, 1.0))
    )
    return rotate_z @ rotate_y @ rotate_x


def _axis_aligned_rotations() -> tuple[tuple[tuple[int, int, int], Any], ...]:
    rotations: list[tuple[tuple[int, int, int], Any]] = []
    seen: set[tuple[int, ...]] = set()
    for rotation in itertools.product((0, 90, 180, 270), repeat=3):
        rotation_xyz = cast(tuple[int, int, int], rotation)
        matrix = _rotation_matrix_xyz(rotation_xyz)
        key = tuple(round(value) for value in matrix.reshape(-1))
        if key not in seen:
            seen.add(key)
            rotations.append((rotation_xyz, matrix))
    if len(rotations) != 24:
        raise RuntimeError("axis-aligned rotation enumeration must contain 24 orientations")
    return tuple(rotations)


def _orientation_metrics(
    mesh: Any,
    matrix: Any,
    *,
    profile: PrintProfile,
) -> tuple[tuple[float, float, float], bool, float]:
    import numpy as np

    vertices = np.asarray(mesh.vertices) @ matrix.T
    normals = np.asarray(mesh.face_normals) @ matrix.T
    face_areas = np.asarray(mesh.area_faces)
    faces = np.asarray(mesh.faces)
    extents_array = np.ptp(vertices, axis=0)
    extents = cast(tuple[float, float, float], tuple(float(value) for value in extents_array))
    fits = all(
        extent <= limit
        for extent, limit in zip(extents, profile.build_volume.values(), strict=True)
    )

    minimum_z = float(vertices[:, 2].min())
    build_plate_tolerance = max(
        float(extents_array.max()) * 1e-9,
        float(np.finfo(float).eps),
    )
    face_z = vertices[faces][:, :, 2]
    on_build_plate = np.all(face_z <= minimum_z + build_plate_tolerance, axis=1)
    threshold = -math.cos(math.radians(90 - profile.maximum_unsupported_overhang_degrees))
    downward_area = float(face_areas[(normals[:, 2] < threshold) & ~on_build_plate].sum())
    overhang_ratio = downward_area / float(mesh.area) if mesh.area else 0.0
    return extents, fits, overhang_ratio


def rank_axis_aligned_orientations(
    mesh: Any,
    *,
    profile: PrintProfile,
    limit: int,
) -> tuple[OrientationCandidate, ...]:
    """Rank the 24 rigid axis-aligned rotations without changing the source mesh."""

    candidates: list[tuple[tuple[int, int, int], tuple[float, float, float], bool, float]] = []
    for rotation, matrix in _axis_aligned_rotations():
        extents, fits, overhang_ratio = _orientation_metrics(mesh, matrix, profile=profile)
        candidates.append((rotation, extents, fits, overhang_ratio))
    candidates.sort(key=lambda item: (not item[2], item[3], item[1][2], item[0]))
    return tuple(
        OrientationCandidate(
            rank=rank,
            rotation_degrees_xyz=rotation,
            is_current_orientation=rotation == (0, 0, 0),
            bounds_extents_mm=extents,
            height_mm=extents[2],
            fits_build_volume=fits,
            downward_overhang_area_ratio=overhang_ratio,
        )
        for rank, (rotation, extents, fits, overhang_ratio) in enumerate(
            candidates[:limit], start=1
        )
    )


def lint_mesh_bytes(
    content: bytes,
    *,
    filename: str,
    mesh_format: MeshFormat,
    profile: PrintProfile,
    orientation_limit: int = 6,
) -> MeshLintReport:
    """Lint one caller-declared millimetre mesh and retain its source digest."""

    if len(content) > MAX_MESH_BYTES:
        raise AnalysisError(
            "mesh exceeds the standalone lint input limit",
            details={"size_bytes": len(content), "limit_bytes": MAX_MESH_BYTES},
        )
    if not 1 <= orientation_limit <= 24:
        raise AnalysisError(
            "orientation candidate limit must be between 1 and 24",
            details={"orientation_limit": orientation_limit},
        )
    digest = hashlib.sha256(content).hexdigest()
    mesh = load_triangle_mesh(content, file_type=mesh_format)
    embedded_units = _embedded_units(mesh)
    scale_factor_to_mm = _normalize_mesh_to_millimetres(mesh, embedded_units)
    analysis = MeshAnalyzer().analyze_loaded_mesh(
        mesh,
        profile=profile,
        mesh_sha256=digest,
    )
    candidates = rank_axis_aligned_orientations(
        mesh,
        profile=profile,
        limit=orientation_limit,
    )
    error_count = sum(finding.severity == Severity.ERROR for finding in analysis.findings)
    warning_count = sum(finding.severity == Severity.WARNING for finding in analysis.findings)
    info_count = sum(finding.severity == Severity.INFO for finding in analysis.findings)
    return MeshLintReport(
        source=MeshSourceEvidence(
            filename=filename,
            format=mesh_format,
            sha256=digest,
            size_bytes=len(content),
            embedded_units=embedded_units,
            scale_factor_to_mm=scale_factor_to_mm,
        ),
        summary=MeshLintSummary(
            status="fail" if error_count else "pass",
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            orientation_candidates_returned=len(candidates),
        ),
        analysis=analysis,
        orientation_candidates=candidates,
        limitations=(
            "Unitless coordinates use the caller's explicit millimetre declaration. Explicit "
            "embedded units are deterministically normalized to millimetres and reported.",
            "Topology measurements are exact only for the parsed triangle representation; "
            "they do not recover CAD feature or tolerance semantics.",
            "Build-volume fit is bounded by the supplied profile and each reported rigid "
            "axis-aligned orientation.",
            "Overhang ranking is a face-normal heuristic that excludes build-plate contact; "
            "it does not run a slicer or model bridges, supports, cooling, or adhesion.",
            "Disconnected mesh components do not enumerate physical assembly instances; use "
            "the assembly-lint workflow for any assembly inspection request.",
            "Minimum wall thickness, fit, manufacturability, and structural integrity remain "
            "unverified.",
        ),
    )


def render_mesh_lint_text(report: MeshLintReport) -> str:
    """Render a compact review without dropping evidence confidence or orientation data."""

    lines = [
        f"{report.summary.status.upper()} {report.source.filename} ({report.units})",
        (
            f"Source: {report.source.format}; {report.source.size_bytes} bytes; "
            f"sha256={report.source.sha256}"
        ),
        "",
        "Measurements:",
    ]
    for measurement in report.analysis.measurements:
        unit = f" {measurement.unit}" if measurement.unit else ""
        lines.append(
            f"- {measurement.name}: {measurement.value}{unit} [{measurement.confidence.value}]"
        )
    lines.extend(["", "Findings:"])
    if report.analysis.findings:
        for finding in report.analysis.findings:
            lines.append(
                f"- {finding.severity.value} {finding.code} "
                f"[{finding.confidence.value}]: {finding.message}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "Best axis-aligned orientation candidates:"])
    for candidate in report.orientation_candidates:
        rotation = ",".join(str(value) for value in candidate.rotation_degrees_xyz)
        extents = " x ".join(f"{value:g}" for value in candidate.bounds_extents_mm)
        lines.append(
            f"- #{candidate.rank} rotate_xyz=({rotation}) deg; extents={extents} mm; "
            f"fits={str(candidate.fits_build_volume).lower()} [bounded]; "
            f"overhang_ratio={candidate.downward_overhang_area_ratio:.6f} [heuristic]"
        )
    lines.extend(
        [
            "",
            (
                f"Summary: {report.summary.error_count} errors, "
                f"{report.summary.warning_count} warnings, {report.summary.info_count} info; "
                "24 orientations evaluated."
            ),
        ]
    )
    return "\n".join(lines)
