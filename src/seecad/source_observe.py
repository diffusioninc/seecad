"""Read-only observation of local 3D source bundles before semantic linting."""

from __future__ import annotations

import hashlib
import io
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import Field, StringConstraints

from seecad.errors import AnalysisError
from seecad.mesh_lint import MAX_MESH_BYTES, SUPPORTED_MESH_FORMATS, MeshFormat
from seecad.models import Confidence, StrictModel

MAX_OBSERVE_FILES = 64
MAX_OBSERVE_BYTES = MAX_MESH_BYTES

CoordinateTriple = tuple[float, float, float]
Matrix4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]
SourceFileStatus = Literal["observed", "unsupported_format", "too_large", "parse_error"]
SourceRouteHint = Literal[
    "mesh_lint_candidate",
    "assembly_evidence_review",
    "no_supported_geometry",
]


class SourceUnitEvidence(StrictModel):
    declared_units: Literal["mm"] | None = None
    embedded_units: str | None = Field(default=None, min_length=1, max_length=80)
    coordinate_unit_label: str = Field(min_length=1, max_length=80)
    confidence: Literal[Confidence.EXACT, Confidence.UNAVAILABLE]
    unit_conflict: bool = False
    basis: str = Field(min_length=1, max_length=500)


class SourceBounds(StrictModel):
    minimum: CoordinateTriple
    maximum: CoordinateTriple
    extents: CoordinateTriple
    coordinate_space: Literal["source_coordinates"] = "source_coordinates"
    confidence: Literal[Confidence.EXACT] = Confidence.EXACT
    basis: str = "transformed triangle vertices in the parsed source scene graph"


class SourceGeometryInstance(StrictModel):
    id: str = Field(min_length=1, max_length=240)
    node_name: str | None = Field(default=None, min_length=1, max_length=240)
    geometry_name: str | None = Field(default=None, min_length=1, max_length=240)
    transform: Matrix4
    triangle_count: int = Field(ge=0)
    vertex_count: int = Field(ge=0)
    bounds: SourceBounds


class SourceFileObservation(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    filename: str = Field(min_length=1, max_length=240)
    status: SourceFileStatus
    format: MeshFormat | Literal["unsupported"]
    sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")] | None = None
    size_bytes: int = Field(ge=0)
    units: SourceUnitEvidence | None = None
    geometry_instances: tuple[SourceGeometryInstance, ...] = Field(default_factory=tuple)
    triangle_count: int = Field(ge=0)
    vertex_count: int = Field(ge=0)
    error: str | None = Field(default=None, min_length=1, max_length=500)


class SourceObservationSummary(StrictModel):
    total_files: int = Field(ge=0)
    observed_files: int = Field(ge=0)
    unsupported_files: int = Field(ge=0)
    too_large_files: int = Field(ge=0)
    parse_error_files: int = Field(ge=0)
    geometry_instance_count: int = Field(ge=0)
    triangle_count: int = Field(ge=0)
    vertex_count: int = Field(ge=0)
    unit_conflict_count: int = Field(ge=0)
    route_hint: SourceRouteHint


class SourceObservationReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    scope: Literal["source_observation"] = "source_observation"
    summary: SourceObservationSummary
    files: tuple[SourceFileObservation, ...]
    limitations: tuple[str, ...]


def observe_sources(
    paths: Sequence[Path],
    *,
    recursive: bool = False,
    declared_units: Literal["mm"] | None = None,
    file_limit: int = MAX_OBSERVE_FILES,
) -> SourceObservationReport:
    """Observe local 3D source records without creating design authority."""

    if declared_units not in {None, "mm"}:
        raise AnalysisError(
            "source observation only accepts an explicit millimetre declaration",
            details={"declared_units": declared_units},
        )
    if not 1 <= file_limit <= 256:
        raise AnalysisError(
            "source observation file limit must be between 1 and 256",
            details={"file_limit": file_limit},
        )
    source_files = _collect_files(paths, recursive=recursive, file_limit=file_limit)
    observations = tuple(
        _observe_file(path, declared_units=declared_units) for path in source_files
    )
    return _source_observation_report(observations)


def observe_source_payloads(
    payloads: Sequence[tuple[str, bytes]],
    *,
    declared_units: Literal["mm"] | None = None,
    file_limit: int = MAX_OBSERVE_FILES,
) -> SourceObservationReport:
    """Observe caller-provided source bytes without reading server-side paths."""

    if declared_units not in {None, "mm"}:
        raise AnalysisError(
            "source observation only accepts an explicit millimetre declaration",
            details={"declared_units": declared_units},
        )
    if not 1 <= file_limit <= 256:
        raise AnalysisError(
            "source observation file limit must be between 1 and 256",
            details={"file_limit": file_limit},
        )
    if not payloads:
        raise AnalysisError("at least one source payload is required")
    if len(payloads) > file_limit:
        raise AnalysisError(
            "source observation file limit exceeded",
            details={"file_limit": file_limit},
        )
    observations = tuple(
        _observe_payload(filename, content, declared_units=declared_units)
        for filename, content in payloads
    )
    return _source_observation_report(observations)


def render_source_observation_text(report: SourceObservationReport) -> str:
    """Render a compact source-observation report for agent review."""

    lines = [
        "SOURCE OBSERVATION",
        (
            f"Summary: {report.summary.observed_files}/{report.summary.total_files} observed; "
            f"{report.summary.geometry_instance_count} geometry instances; "
            f"{report.summary.triangle_count} triangles; route={report.summary.route_hint}"
        ),
    ]
    if report.summary.unit_conflict_count:
        lines.append(f"Unit conflicts: {report.summary.unit_conflict_count}")
    lines.extend(["", "Files:"])
    for source in report.files:
        digest = f"; sha256={source.sha256}" if source.sha256 else ""
        lines.append(
            f"- {source.path}: {source.status}; format={source.format}; "
            f"{source.size_bytes} bytes{digest}"
        )
        if source.units:
            conflict = "; conflict=true" if source.units.unit_conflict else ""
            lines.append(
                f"  units: {source.units.coordinate_unit_label} "
                f"[{source.units.confidence.value}]{conflict}"
            )
        if source.error:
            lines.append(f"  error: {source.error}")
        for instance in source.geometry_instances:
            bounds = instance.bounds
            low = _format_triple(bounds.minimum)
            high = _format_triple(bounds.maximum)
            extents = _format_triple(bounds.extents)
            lines.append(
                f"  - {instance.id}: triangles={instance.triangle_count}; "
                f"vertices={instance.vertex_count}; bounds=[{low}] to [{high}]; "
                f"extents=[{extents}] [{bounds.confidence.value}]"
            )
    lines.extend(["", "Limitations:"])
    for limitation in report.limitations:
        lines.append(f"- {limitation}")
    return "\n".join(lines)


def _source_observation_report(
    observations: tuple[SourceFileObservation, ...],
) -> SourceObservationReport:
    observed_files = sum(item.status == "observed" for item in observations)
    unsupported_files = sum(item.status == "unsupported_format" for item in observations)
    too_large_files = sum(item.status == "too_large" for item in observations)
    parse_error_files = sum(item.status == "parse_error" for item in observations)
    instance_count = sum(len(item.geometry_instances) for item in observations)
    route_hint: SourceRouteHint
    if observed_files == 1 and instance_count == 1 and len(observations) == 1:
        route_hint = "mesh_lint_candidate"
    elif instance_count > 0:
        route_hint = "assembly_evidence_review"
    else:
        route_hint = "no_supported_geometry"
    return SourceObservationReport(
        summary=SourceObservationSummary(
            total_files=len(observations),
            observed_files=observed_files,
            unsupported_files=unsupported_files,
            too_large_files=too_large_files,
            parse_error_files=parse_error_files,
            geometry_instance_count=instance_count,
            triangle_count=sum(item.triangle_count for item in observations),
            vertex_count=sum(item.vertex_count for item in observations),
            unit_conflict_count=sum(
                bool(item.units and item.units.unit_conflict) for item in observations
            ),
            route_hint=route_hint,
        ),
        files=observations,
        limitations=(
            "This report observes local source records only; it does not create a DesignSpec, "
            "compile CAD, repair meshes, or write derived geometry.",
            "OBJ objects, scene nodes, materials, geometry records, and disconnected shells are "
            "exact only with respect to parser output and are not a physical-instance inventory.",
            "Bounds are exact for transformed parsed triangle vertices in source coordinates. "
            "They become millimetre bounds only when units are explicitly declared or embedded.",
            "The report does not identify fasteners, infer interfaces, check tool access, prove "
            "assembly fit, or claim manufacturability or structural integrity.",
        ),
    )


def _collect_files(paths: Sequence[Path], *, recursive: bool, file_limit: int) -> tuple[Path, ...]:
    if not paths:
        raise AnalysisError("at least one source path is required")
    files: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            if path.is_dir():
                iterator = path.rglob("*") if recursive else path.iterdir()
                candidates = sorted(item for item in iterator if item.is_file())
            elif path.is_file():
                candidates = [path]
            else:
                raise AnalysisError(
                    "source observation path does not exist or is not a regular file/directory",
                    details={"path": str(path)},
                )
        except OSError as exc:
            raise AnalysisError(
                "could not enumerate source observation path",
                details={"path": str(path), "reason": type(exc).__name__},
            ) from exc
        for candidate in candidates:
            key = candidate.resolve(strict=False)
            if key in seen:
                continue
            seen.add(key)
            files.append(candidate)
            if len(files) > file_limit:
                raise AnalysisError(
                    "source observation file limit exceeded",
                    details={"file_limit": file_limit},
                )
    return tuple(sorted(files, key=lambda item: str(item)))


def _observe_file(
    path: Path,
    *,
    declared_units: Literal["mm"] | None,
) -> SourceFileObservation:
    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        raise AnalysisError(
            "could not stat source observation file",
            details={"path": str(path), "reason": type(exc).__name__},
        ) from exc
    mesh_format = SUPPORTED_MESH_FORMATS.get(path.suffix.lower())
    if size_bytes > MAX_OBSERVE_BYTES:
        return SourceFileObservation(
            path=str(path),
            filename=path.name,
            status="too_large",
            format=mesh_format or "unsupported",
            size_bytes=size_bytes,
            triangle_count=0,
            vertex_count=0,
            error=f"file exceeds {MAX_OBSERVE_BYTES} byte observation limit",
        )
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise AnalysisError(
            "could not read source observation file",
            details={"path": str(path), "reason": type(exc).__name__},
        ) from exc
    digest = hashlib.sha256(content).hexdigest()
    if mesh_format is None:
        return SourceFileObservation(
            path=str(path),
            filename=path.name,
            status="unsupported_format",
            format="unsupported",
            sha256=digest,
            size_bytes=size_bytes,
            triangle_count=0,
            vertex_count=0,
            error="unsupported source format for geometry observation",
        )
    return _observe_mesh_content(
        content,
        path=path,
        mesh_format=mesh_format,
        sha256=digest,
        size_bytes=size_bytes,
        declared_units=declared_units,
    )


def _observe_payload(
    filename: str,
    content: bytes,
    *,
    declared_units: Literal["mm"] | None,
) -> SourceFileObservation:
    path = Path(filename)
    mesh_format = SUPPORTED_MESH_FORMATS.get(path.suffix.lower())
    size_bytes = len(content)
    if size_bytes > MAX_OBSERVE_BYTES:
        return SourceFileObservation(
            path=filename,
            filename=path.name,
            status="too_large",
            format=mesh_format or "unsupported",
            size_bytes=size_bytes,
            triangle_count=0,
            vertex_count=0,
            error=f"file exceeds {MAX_OBSERVE_BYTES} byte observation limit",
        )
    digest = hashlib.sha256(content).hexdigest()
    if mesh_format is None:
        return SourceFileObservation(
            path=filename,
            filename=path.name,
            status="unsupported_format",
            format="unsupported",
            sha256=digest,
            size_bytes=size_bytes,
            triangle_count=0,
            vertex_count=0,
            error="unsupported source format for geometry observation",
        )
    return _observe_mesh_content(
        content,
        path=path,
        mesh_format=mesh_format,
        sha256=digest,
        size_bytes=size_bytes,
        declared_units=declared_units,
    )


def _observe_mesh_content(
    content: bytes,
    *,
    path: Path,
    mesh_format: MeshFormat,
    sha256: str,
    size_bytes: int,
    declared_units: Literal["mm"] | None,
) -> SourceFileObservation:
    try:
        import trimesh

        loaded = trimesh.load(io.BytesIO(content), file_type=mesh_format, process=False)
        embedded_units = _embedded_units(loaded)
        instances: tuple[SourceGeometryInstance, ...]
        if isinstance(loaded, trimesh.Scene):
            instances = _observe_scene_instances(loaded)
        elif isinstance(loaded, trimesh.Trimesh):
            instances = (
                _observe_instance(
                    loaded,
                    transform=_identity_matrix(),
                    instance_id="mesh",
                    node_name=None,
                    geometry_name=path.stem,
                ),
            )
        else:
            raise AnalysisError("source does not contain a triangle mesh or scene")
        if not instances:
            raise AnalysisError("source does not contain non-empty triangle geometry")
        return SourceFileObservation(
            path=str(path),
            filename=path.name,
            status="observed",
            format=mesh_format,
            sha256=sha256,
            size_bytes=size_bytes,
            units=_unit_evidence(declared_units, embedded_units),
            geometry_instances=instances,
            triangle_count=sum(instance.triangle_count for instance in instances),
            vertex_count=sum(instance.vertex_count for instance in instances),
        )
    except AnalysisError as exc:
        return SourceFileObservation(
            path=str(path),
            filename=path.name,
            status="parse_error",
            format=mesh_format,
            sha256=sha256,
            size_bytes=size_bytes,
            triangle_count=0,
            vertex_count=0,
            error=exc.message,
        )
    except Exception as exc:
        return SourceFileObservation(
            path=str(path),
            filename=path.name,
            status="parse_error",
            format=mesh_format,
            sha256=sha256,
            size_bytes=size_bytes,
            triangle_count=0,
            vertex_count=0,
            error=f"failed to parse source geometry: {type(exc).__name__}",
        )


def _observe_scene_instances(scene: Any) -> tuple[SourceGeometryInstance, ...]:
    instances: list[SourceGeometryInstance] = []
    for node_name in sorted(str(node) for node in scene.graph.nodes_geometry):
        transform, geometry_name = scene.graph.get(node_name)
        mesh = scene.geometry.get(geometry_name)
        if mesh is None:
            continue
        instances.append(
            _observe_instance(
                mesh,
                transform=transform,
                instance_id=node_name,
                node_name=node_name,
                geometry_name=str(geometry_name),
            )
        )
    return tuple(instances)


def _observe_instance(
    mesh: Any,
    *,
    transform: Any,
    instance_id: str,
    node_name: str | None,
    geometry_name: str | None,
) -> SourceGeometryInstance:
    import numpy as np
    import trimesh

    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0 or len(mesh.vertices) == 0:
        raise AnalysisError("source scene instance does not contain non-empty triangle geometry")
    transform_array = np.asarray(transform, dtype=float)
    if transform_array.shape != (4, 4) or not np.isfinite(transform_array).all():
        raise AnalysisError("source scene instance has an invalid transform")
    vertices = np.asarray(mesh.vertices, dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise AnalysisError("source scene instance has invalid vertices")
    homogeneous = np.column_stack((vertices, np.ones(len(vertices))))
    transformed = (transform_array @ homogeneous.T).T[:, :3]
    minimum = _triple(transformed.min(axis=0))
    maximum = _triple(transformed.max(axis=0))
    extents: CoordinateTriple = (
        maximum[0] - minimum[0],
        maximum[1] - minimum[1],
        maximum[2] - minimum[2],
    )
    return SourceGeometryInstance(
        id=_clean_name(instance_id),
        node_name=_clean_name(node_name) if node_name else None,
        geometry_name=_clean_name(geometry_name) if geometry_name else None,
        transform=_matrix4(transform_array),
        triangle_count=len(mesh.faces),
        vertex_count=len(mesh.vertices),
        bounds=SourceBounds(minimum=minimum, maximum=maximum, extents=extents),
    )


def _unit_evidence(
    declared_units: Literal["mm"] | None,
    embedded_units: str | None,
) -> SourceUnitEvidence:
    normalized_embedded = embedded_units.strip() if embedded_units else None
    if declared_units == "mm" and normalized_embedded and not _is_millimetre(normalized_embedded):
        return SourceUnitEvidence(
            declared_units=declared_units,
            embedded_units=normalized_embedded,
            coordinate_unit_label="source coordinates",
            confidence=Confidence.UNAVAILABLE,
            unit_conflict=True,
            basis=(
                "caller declared millimetres, but embedded source metadata reports "
                f"{normalized_embedded!r}; resolve the conflict before treating bounds as mm"
            ),
        )
    if declared_units == "mm":
        return SourceUnitEvidence(
            declared_units=declared_units,
            embedded_units=normalized_embedded,
            coordinate_unit_label="mm",
            confidence=Confidence.EXACT,
            basis="caller explicitly declared source coordinate values as millimetres",
        )
    if normalized_embedded:
        return SourceUnitEvidence(
            embedded_units=normalized_embedded,
            coordinate_unit_label=normalized_embedded,
            confidence=Confidence.EXACT,
            basis="unit label came from parsed source metadata; coordinates are not normalized",
        )
    return SourceUnitEvidence(
        coordinate_unit_label="source coordinates",
        confidence=Confidence.UNAVAILABLE,
        basis="no caller unit declaration or embedded unit metadata was available",
    )


def _embedded_units(loaded: Any) -> str | None:
    try:
        value = loaded.units
    except (AttributeError, TypeError, ValueError):
        return None
    return str(value) if value else None


def _is_millimetre(value: str) -> bool:
    return value.lower().strip() in {
        "mm",
        "millimeter",
        "millimeters",
        "millimetre",
        "millimetres",
    }


def _identity_matrix() -> Matrix4:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def _matrix4(matrix: Any) -> Matrix4:
    rows = []
    for row in matrix:
        values = tuple(float(value) for value in row)
        if len(values) != 4 or not all(math.isfinite(value) for value in values):
            raise AnalysisError("source scene instance has an invalid transform")
        rows.append(values)
    if len(rows) != 4:
        raise AnalysisError("source scene instance has an invalid transform")
    return cast(Matrix4, tuple(rows))


def _triple(values: Any) -> CoordinateTriple:
    triple = tuple(float(value) for value in values)
    if len(triple) != 3 or not all(math.isfinite(value) for value in triple):
        raise AnalysisError("source scene instance has invalid bounds")
    return triple


def _clean_name(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = value.strip() or "unnamed"
    return cleaned[:240]


def _format_triple(values: CoordinateTriple) -> str:
    return ", ".join(f"{value:g}" for value in values)
