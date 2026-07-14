"""Mesh topology and bounded DFM analysis with explicit evidence confidence."""

from __future__ import annotations

import hashlib
import io
import math
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import JsonValue

from seecad.errors import AnalysisError
from seecad.models import (
    Confidence,
    Finding,
    Measurement,
    MeshAnalysis,
    PrintProfile,
    Severity,
    print_profile_sha256,
)


def load_triangle_mesh(content: bytes, *, file_type: str) -> Any:
    """Parse one mesh instance without flattening an imported assembly scene."""

    if not content:
        raise AnalysisError("cannot analyze an empty mesh")
    try:
        import trimesh

        loaded = trimesh.load(io.BytesIO(content), file_type=file_type, process=True)
        if isinstance(loaded, trimesh.Scene):
            geometry_nodes = tuple(loaded.graph.nodes_geometry)
            if len(loaded.geometry) != 1 or len(geometry_nodes) != 1:
                raise AnalysisError(
                    "mesh lint accepts one mesh instance; use assembly lint for a multi-part scene",
                    details={
                        "geometry_count": len(loaded.geometry),
                        "instance_count": len(geometry_nodes),
                        "required_workflow": "seecad lint",
                    },
                )
            mesh = loaded.to_geometry()
        else:
            mesh = loaded
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            raise AnalysisError("artifact does not contain a non-empty triangle mesh")
        return mesh
    except AnalysisError:
        raise
    except Exception as exc:
        raise AnalysisError(
            f"failed to parse {file_type.upper()} mesh",
            details={"format": file_type, "reason": type(exc).__name__},
        ) from exc


def downward_overhang_area_ratio(
    mesh: Any,
    *,
    maximum_unsupported_overhang_degrees: float,
) -> float:
    """Return a face-normal support proxy while excluding build-plate contact faces."""

    import numpy as np

    face_areas = np.asarray(mesh.area_faces)
    if not len(face_areas) or not float(mesh.area):
        return 0.0
    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.faces)
    normals = np.asarray(mesh.face_normals)
    extents = np.asarray(mesh.extents)
    minimum_z = float(vertices[:, 2].min())
    build_plate_tolerance = max(float(extents.max()) * 1e-9, float(np.finfo(float).eps))
    face_z = vertices[faces][:, :, 2]
    on_build_plate = np.all(face_z <= minimum_z + build_plate_tolerance, axis=1)
    threshold = -math.cos(math.radians(90 - maximum_unsupported_overhang_degrees))
    downward_area = float(face_areas[(normals[:, 2] < threshold) & ~on_build_plate].sum())
    return downward_area / float(mesh.area)


class MeshAnalyzer:
    def analyze_stl(
        self,
        content: bytes,
        *,
        profile: PrintProfile,
        mesh_sha256: str | None = None,
    ) -> MeshAnalysis:
        return self.analyze_mesh(
            content,
            file_type="stl",
            profile=profile,
            mesh_sha256=mesh_sha256,
        )

    def analyze_mesh(
        self,
        content: bytes,
        *,
        file_type: str,
        profile: PrintProfile,
        mesh_sha256: str | None = None,
    ) -> MeshAnalysis:
        mesh = load_triangle_mesh(content, file_type=file_type)
        digest = mesh_sha256 or hashlib.sha256(content).hexdigest()
        return self.analyze_loaded_mesh(mesh, profile=profile, mesh_sha256=digest)

    def analyze_loaded_mesh(
        self,
        mesh: Any,
        *,
        profile: PrintProfile,
        mesh_sha256: str,
    ) -> MeshAnalysis:
        import numpy as np

        extents = [float(value) for value in mesh.extents]
        watertight = bool(mesh.is_watertight)
        winding = bool(mesh.is_winding_consistent)
        face_areas = np.asarray(mesh.area_faces)
        characteristic_length = max(extents) if extents else 0.0
        degenerate_area_tolerance = max(
            characteristic_length * characteristic_length * 1e-12,
            float(np.finfo(float).eps),
        )
        degenerate_triangles = int(np.count_nonzero(face_areas <= degenerate_area_tolerance))
        try:
            components = len(mesh.split(only_watertight=False))
        except Exception:
            components = 1
        measurements = [
            Measurement(
                name="triangle_count",
                value=len(mesh.faces),
                confidence=Confidence.EXACT,
                basis="triangle records in the parsed compiled mesh",
            ),
            Measurement(
                name="vertex_count",
                value=len(mesh.vertices),
                confidence=Confidence.EXACT,
                basis="indexed vertices in the parsed compiled mesh",
            ),
            Measurement(
                name="degenerate_triangle_count",
                value=degenerate_triangles,
                confidence=Confidence.BOUNDED,
                basis=(
                    "triangle areas at or below the scale-relative numerical tolerance "
                    f"of {degenerate_area_tolerance:.17g} mm^2"
                ),
            ),
            Measurement(
                name="bounds_extents",
                value=extents,
                unit="mm",
                confidence=Confidence.EXACT,
                basis="triangle vertex bounds in the compiled mesh",
            ),
            Measurement(
                name="surface_area",
                value=float(mesh.area),
                unit="mm^2",
                confidence=Confidence.EXACT,
                basis="sum of triangle areas",
            ),
            Measurement(
                name="volume",
                value=abs(float(mesh.volume)) if watertight else None,
                unit="mm^3",
                confidence=Confidence.EXACT if watertight else Confidence.UNAVAILABLE,
                basis=(
                    "signed tetrahedral volume of a watertight mesh"
                    if watertight
                    else "volume is not valid for a non-watertight mesh"
                ),
            ),
            Measurement(
                name="watertight",
                value=watertight,
                confidence=Confidence.EXACT,
                basis="edge incidence topology",
            ),
            Measurement(
                name="winding_consistent",
                value=winding,
                confidence=Confidence.EXACT,
                basis="adjacent face winding topology",
            ),
            Measurement(
                name="connected_components",
                value=components,
                confidence=Confidence.EXACT,
                basis="face adjacency components",
            ),
        ]
        fits = all(
            extent <= limit
            for extent, limit in zip(extents, profile.build_volume.values(), strict=True)
        )
        measurements.append(
            Measurement(
                name="fits_configured_build_volume_current_orientation",
                value=fits,
                confidence=Confidence.BOUNDED,
                basis="compiled AABB compared with the configured printer profile",
            )
        )

        overhang_ratio = downward_overhang_area_ratio(
            mesh,
            maximum_unsupported_overhang_degrees=(profile.maximum_unsupported_overhang_degrees),
        )
        measurements.append(
            Measurement(
                name="downward_overhang_area_ratio",
                value=overhang_ratio,
                confidence=Confidence.HEURISTIC,
                basis=(
                    "downward face normals excluding faces on the current build plate; "
                    "no slicer or bridge solve was performed"
                ),
            )
        )
        measurements.append(
            Measurement(
                name="minimum_wall_thickness",
                value=None,
                unit="mm",
                confidence=Confidence.UNAVAILABLE,
                basis="a reliable volumetric thickness solve was not performed",
            )
        )

        findings: list[Finding] = []
        if not watertight:
            findings.append(
                Finding(
                    code="mesh_not_watertight",
                    severity=Severity.ERROR,
                    message="The compiled mesh has open or non-manifold boundary edges.",
                    confidence=Confidence.EXACT,
                )
            )
        if not winding:
            findings.append(
                Finding(
                    code="inconsistent_winding",
                    severity=Severity.ERROR,
                    message="Some adjacent triangles have inconsistent winding.",
                    confidence=Confidence.EXACT,
                )
            )
        if components > 1:
            findings.append(
                Finding(
                    code="multiple_components",
                    severity=Severity.WARNING,
                    message=f"The mesh contains {components} disconnected components.",
                    confidence=Confidence.EXACT,
                    evidence={"component_count": components},
                )
            )
        if degenerate_triangles:
            findings.append(
                Finding(
                    code="degenerate_triangles_detected",
                    severity=Severity.WARNING,
                    message=(
                        f"The parsed mesh contains {degenerate_triangles} triangles at or below "
                        "the reported scale-relative area tolerance."
                    ),
                    confidence=Confidence.BOUNDED,
                    evidence={
                        "count": degenerate_triangles,
                        "area_tolerance_mm2": degenerate_area_tolerance,
                    },
                )
            )
        if not fits:
            findings.append(
                Finding(
                    code="build_volume_exceeded",
                    severity=Severity.ERROR,
                    message="The current mesh orientation exceeds the configured build volume.",
                    confidence=Confidence.BOUNDED,
                    evidence={
                        "extents_mm": cast(JsonValue, extents),
                        "build_volume_mm": cast(JsonValue, list(profile.build_volume.values())),
                    },
                )
            )
        if overhang_ratio > 0.02:
            findings.append(
                Finding(
                    code="support_review_recommended",
                    severity=Severity.WARNING,
                    message=(
                        "Downward-facing area suggests supports or a different orientation "
                        "may be needed."
                    ),
                    confidence=Confidence.HEURISTIC,
                    evidence={"downward_area_ratio": overhang_ratio},
                )
            )
        findings.append(
            Finding(
                code="wall_thickness_unverified",
                severity=Severity.INFO,
                message=(
                    "Minimum wall thickness was not proven against the "
                    f"{profile.minimum_wall:g} mm profile target."
                ),
                confidence=Confidence.UNAVAILABLE,
            )
        )
        blocking = any(finding.severity == Severity.ERROR for finding in findings)
        summary = (
            "Blocking mesh or build-volume findings detected."
            if blocking
            else "No blocking topology finding detected; process fit remains bounded and heuristic."
        )
        return MeshAnalysis(
            mesh_sha256=mesh_sha256,
            print_profile=profile,
            print_profile_sha256=print_profile_sha256(profile),
            analyzed_at=datetime.now(UTC),
            measurements=measurements,
            findings=findings,
            printable=False if blocking else None,
            summary=summary,
        )
