"""Deterministic, deliberately invoked visual proof-sheet generation."""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import math
import struct
import zipfile
import zlib
from dataclasses import dataclass
from typing import Any, cast

from seecad.analysis import load_triangle_mesh
from seecad.errors import AnalysisError

PROOF_SHEET_SCHEMA_VERSION = "1.0"
PROOF_SHEET_CONFIDENCE = "heuristic"
PROOF_SHEET_MAX_SURFACE_SAMPLES = 98_304
PROOF_SHEET_NAMED_VIEW_COUNT = 26


@dataclass(frozen=True, slots=True)
class ProofSheetArtifacts:
    """Reproducible visual and machine-readable derivatives of one STL."""

    manifest: bytes
    review_html: bytes
    archive: bytes


def _normalized(values: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in values))
    if length == 0:
        raise ValueError("proof-sheet direction cannot be zero")
    return tuple(value / length for value in values)  # type: ignore[return-value]


def _named_directions() -> tuple[tuple[str, tuple[float, float, float]], ...]:
    axes = (
        ("right", (1.0, 0.0, 0.0)),
        ("left", (-1.0, 0.0, 0.0)),
        ("rear", (0.0, 1.0, 0.0)),
        ("front", (0.0, -1.0, 0.0)),
        ("top", (0.0, 0.0, 1.0)),
        ("bottom", (0.0, 0.0, -1.0)),
    )
    corners = tuple(
        (
            f"corner_{'p' if x > 0 else 'n'}x_{'p' if y > 0 else 'n'}y_{'p' if z > 0 else 'n'}z",
            _normalized((x, y, z)),
        )
        for x in (-1.0, 1.0)
        for y in (-1.0, 1.0)
        for z in (-1.0, 1.0)
    )
    edges: list[tuple[str, tuple[float, float, float]]] = []
    for zero_axis in range(3):
        nonzero_axes = [axis for axis in range(3) if axis != zero_axis]
        for first in (-1.0, 1.0):
            for second in (-1.0, 1.0):
                values = [0.0, 0.0, 0.0]
                values[nonzero_axes[0]] = first
                values[nonzero_axes[1]] = second
                edges.append(
                    (
                        f"edge_{zero_axis}_{'p' if first > 0 else 'n'}_"
                        f"{'p' if second > 0 else 'n'}",
                        _normalized((values[0], values[1], values[2])),
                    )
                )
    return (*axes, *corners, *edges)


def proof_sheet_directions(
    view_count: int,
) -> tuple[tuple[str, str, tuple[float, float, float]], ...]:
    """Return named datum views followed by a deterministic Fibonacci-sphere catalog."""

    if view_count < PROOF_SHEET_NAMED_VIEW_COUNT:
        raise ValueError(f"proof sheets require at least {PROOF_SHEET_NAMED_VIEW_COUNT} viewpoints")
    directions: list[tuple[str, str, tuple[float, float, float]]] = [
        (f"view-{index:04d}", name, direction)
        for index, (name, direction) in enumerate(_named_directions())
    ]
    remaining = view_count - len(directions)
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    for offset in range(remaining):
        z = 1.0 - 2.0 * ((offset + 0.5) / remaining)
        radius = math.sqrt(max(0.0, 1.0 - z * z))
        azimuth = offset * golden_angle
        direction = (radius * math.cos(azimuth), radius * math.sin(azimuth), z)
        index = len(directions)
        directions.append((f"view-{index:04d}", "fibonacci", direction))
    return tuple(directions)


def _bounded_rows(values: Any, limit: int) -> Any:
    import numpy as np

    array = np.asarray(values, dtype=np.float64)
    if len(array) <= limit:
        return array
    indices = np.linspace(0, len(array) - 1, num=limit, dtype=np.int64)
    return array[indices]


def _surface_samples(mesh: Any, resolution_px: int) -> tuple[Any, int]:
    import numpy as np
    import trimesh

    random_count = min(
        PROOF_SHEET_MAX_SURFACE_SAMPLES * 2 // 3,
        max(16_384, resolution_px * resolution_px * 4),
    )
    sampled, _face_ids = trimesh.sample.sample_surface(mesh, random_count, seed=0)
    vertex_budget = (PROOF_SHEET_MAX_SURFACE_SAMPLES - random_count) // 2
    face_budget = PROOF_SHEET_MAX_SURFACE_SAMPLES - random_count - vertex_budget
    vertices = _bounded_rows(mesh.vertices, vertex_budget)
    triangles = np.asarray(mesh.vertices, dtype=np.float64)[np.asarray(mesh.faces, dtype=np.int64)]
    centroids = _bounded_rows(triangles.mean(axis=1), face_budget)
    points = np.vstack((np.asarray(sampled, dtype=np.float64), vertices, centroids))
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise AnalysisError("compiled mesh has invalid coordinates for proof-sheet rendering")
    return points, len(points)


def _view_basis(direction: tuple[float, float, float]) -> tuple[Any, Any, Any]:
    import numpy as np

    forward = np.asarray(direction, dtype=np.float64)
    reference_up = (
        np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
        if abs(float(forward[2])) > 0.98
        else np.asarray((0.0, 0.0, 1.0), dtype=np.float64)
    )
    right = np.cross(reference_up, forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)
    up /= np.linalg.norm(up)
    return right, up, forward


def _close_depth_gaps(depth: Any) -> Any:
    import numpy as np

    visible = np.isfinite(depth)
    padded_visible = np.pad(visible, 1, constant_values=False)
    expanded = np.logical_or.reduce(
        [
            padded_visible[y : y + depth.shape[0], x : x + depth.shape[1]]
            for y in range(3)
            for x in range(3)
        ]
    )
    padded_expanded = np.pad(expanded, 1, constant_values=False)
    closed = np.logical_and.reduce(
        [
            padded_expanded[y : y + depth.shape[0], x : x + depth.shape[1]]
            for y in range(3)
            for x in range(3)
        ]
    )
    padded_depth = np.pad(depth, 1, constant_values=-np.inf)
    neighbor_depth = np.maximum.reduce(
        [
            padded_depth[y : y + depth.shape[0], x : x + depth.shape[1]]
            for y in range(3)
            for x in range(3)
        ]
    )
    return np.where(closed & ~visible, neighbor_depth, depth)


def _smooth_visible_depth(depth: Any) -> Any:
    import numpy as np

    visible = np.isfinite(depth)
    padded = np.pad(depth, 1, constant_values=-np.inf)
    closest_neighbor = np.maximum.reduce(
        [padded[y : y + depth.shape[0], x : x + depth.shape[1]] for y in range(3) for x in range(3)]
    )
    return np.where(visible, closest_neighbor, depth)


def _render_projection(
    points: Any,
    *,
    center: Any,
    radius: float,
    direction: tuple[float, float, float],
    resolution_px: int,
) -> bytes:
    import numpy as np

    right, up, forward = _view_basis(direction)
    relative = points - center
    scale = (resolution_px - 1) * 0.45 / radius
    x = np.rint(relative @ right * scale + (resolution_px - 1) / 2.0).astype(np.int64)
    y = np.rint((resolution_px - 1) / 2.0 - relative @ up * scale).astype(np.int64)
    depth_values = relative @ forward
    inside = (x >= 0) & (x < resolution_px) & (y >= 0) & (y < resolution_px)
    x = x[inside]
    y = y[inside]
    depth_values = depth_values[inside]
    depth = np.full((resolution_px, resolution_px), -np.inf, dtype=np.float64)
    np.maximum.at(depth.ravel(), y * resolution_px + x, depth_values)
    depth = _close_depth_gaps(_close_depth_gaps(depth))
    depth = _smooth_visible_depth(depth)

    visible = np.isfinite(depth)
    normalized_depth = np.zeros_like(depth)
    normalized_depth[visible] = np.clip((depth[visible] / radius + 1.0) / 2.0, 0.0, 1.0)
    image = np.empty((resolution_px, resolution_px, 3), dtype=np.uint8)
    image[:, :] = (245, 243, 237)
    shade = (44 + normalized_depth * 88).astype(np.uint8)
    image[..., 0][visible] = shade[visible] // 2
    image[..., 1][visible] = shade[visible]
    image[..., 2][visible] = np.minimum(255, shade[visible].astype(np.uint16) + 24).astype(np.uint8)
    return _encode_png(image)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _encode_png(image: Any) -> bytes:
    height, width, channels = image.shape
    if channels != 3:
        raise ValueError("proof-sheet PNG encoder requires RGB input")
    scanlines = b"".join(b"\x00" + image[row].tobytes() for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + _png_chunk(b"IEND", b"")
    )


def _projection_angles(direction: tuple[float, float, float]) -> tuple[float, float]:
    x, y, z = direction
    return math.degrees(math.atan2(y, x)), math.degrees(math.asin(max(-1.0, min(1.0, z))))


def _index_html(
    *,
    design_name: str,
    mesh_sha256: str,
    view_count: int,
    resolution_px: int,
    views_per_sheet: int,
    projections: list[dict[str, object]],
    images: list[bytes],
    embedded: bool,
) -> bytes:
    cards: list[str] = []
    for projection, png in zip(projections, images, strict=True):
        index = cast(int, projection["index"])
        source = (
            "data:image/png;base64," + base64.b64encode(png).decode("ascii")
            if embedded
            else f"projections/view-{index:04d}.png"
        )
        cards.append(
            '<figure class="projection">'
            f'<img src="{source}" width="{resolution_px}" height="{resolution_px}" '
            f'alt="Orthographic projection {index:04d}">'
            f"<figcaption><b>{index:04d}</b> {projection['label']}<br>"
            f"az {cast(float, projection['azimuth_degrees']):.2f}&deg; &middot; "
            f"el {cast(float, projection['elevation_degrees']):.2f}&deg;</figcaption>"
            "</figure>"
        )
    sections: list[str] = []
    for start in range(0, view_count, views_per_sheet):
        end = min(start + views_per_sheet, view_count)
        sections.append(
            f'<section class="sheet"><h2>Sheet {start // views_per_sheet + 1:02d} '
            f"<small>views {start:04d}&ndash;{end - 1:04d}</small></h2>"
            f'<div class="grid">{"".join(cards[start:end])}</div></section>'
        )
    escaped_name = html.escape(design_name, quote=True)
    warning = (
        "Heuristic visual-review aid. Clear-looking views do not prove collision clearance, "
        "fit, access, manufacturability, or structural integrity."
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SeeCAD proof sheets &mdash; {escaped_name}</title>
<style>
:root{{color-scheme:light;--ink:#172124;--muted:#667173;--paper:#f5f3ed;--line:#c7cdcb}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);
font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}}
header{{position:sticky;top:0;z-index:2;padding:16px 20px;
background:rgba(245,243,237,.96);border-bottom:1px solid var(--line)}}
h1,h2,p{{margin:0}}
h1{{font:600 20px/1.2 system-ui,sans-serif}}
header p{{margin-top:5px;color:var(--muted);font-size:11px}}
.warning{{margin-top:8px;color:#8b3f18}}
main{{padding:16px}}
.sheet{{margin:0 auto 24px;max-width:1280px;break-after:page}}
h2{{display:flex;justify-content:space-between;padding:8px 0;
border-bottom:1px solid var(--line);font:600 13px system-ui,sans-serif}}
h2 small{{color:var(--muted);font:10px ui-monospace,monospace}}
.grid{{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:8px;padding-top:8px}}
.projection{{margin:0;padding:5px;background:#fff;border:1px solid var(--line)}}
img{{display:block;width:100%;height:auto;image-rendering:auto;background:#f5f3ed}}
figcaption{{min-height:30px;padding-top:4px;color:var(--muted);font-size:8px}}
figcaption b{{color:var(--ink)}}
@media(max-width:700px){{
.grid{{grid-template-columns:repeat(4,minmax(0,1fr));gap:5px}}
main{{padding:8px}}header{{padding:12px}}
}}
@media print{{header{{position:static}}.sheet{{page-break-after:always}}}}
</style></head><body><header><h1>SeeCAD proof sheets &mdash; {escaped_name}</h1>
<p>{view_count:,} deterministic orthographic projections &middot;
{resolution_px}&times;{resolution_px}px &middot; units mm &middot;
mesh sha256:{mesh_sha256}</p>
<p class="warning">{warning}</p>
</header><main>{"".join(sections)}</main></body></html>"""
    return document.encode("utf-8")


def _zip_entry(archive: zipfile.ZipFile, filename: str, content: bytes) -> None:
    info = zipfile.ZipInfo(filename=filename, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content, compresslevel=9)


def build_proof_sheets(
    stl: bytes,
    *,
    design_name: str,
    mesh_sha256: str,
    view_count: int,
    resolution_px: int,
    views_per_sheet: int,
) -> ProofSheetArtifacts:
    """Render a reproducible visual catalog without mutating the source mesh."""

    mesh = load_triangle_mesh(stl, file_type="stl")
    import numpy as np

    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    center = bounds.mean(axis=0)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    radius = float(np.linalg.norm(vertices - center, axis=1).max())
    if not math.isfinite(radius) or radius <= 0:
        raise AnalysisError("compiled mesh has no finite extent for proof-sheet rendering")
    points, sample_count = _surface_samples(mesh, resolution_px)
    directions = proof_sheet_directions(view_count)
    images: list[bytes] = []
    projections: list[dict[str, object]] = []
    for index, (view_id, label, direction) in enumerate(directions):
        png = _render_projection(
            points,
            center=center,
            radius=radius,
            direction=direction,
            resolution_px=resolution_px,
        )
        azimuth, elevation = _projection_angles(direction)
        images.append(png)
        projections.append(
            {
                "index": index,
                "view_id": view_id,
                "label": label,
                "camera_direction_from_origin": [round(value, 12) for value in direction],
                "azimuth_degrees": round(azimuth, 9),
                "elevation_degrees": round(elevation, 9),
                "projection": "orthographic",
                "png_sha256": hashlib.sha256(png).hexdigest(),
                "sheet": index // views_per_sheet,
                "row": (index % views_per_sheet) // 8,
                "column": index % 8,
            }
        )

    sheet_count = math.ceil(view_count / views_per_sheet)
    manifest_document = {
        "schema_version": PROOF_SHEET_SCHEMA_VERSION,
        "kind": "seecad_proof_sheets",
        "scope": "compiled_single_mesh",
        "units": "mm",
        "confidence": PROOF_SHEET_CONFIDENCE,
        "mesh_sha256": mesh_sha256,
        "projection_count": view_count,
        "sheet_count": sheet_count,
        "views_per_sheet": views_per_sheet,
        "resolution_px": resolution_px,
        "viewpoint_strategy": {
            "named_datum_corner_edge_views": PROOF_SHEET_NAMED_VIEW_COUNT,
            "remaining_views": "deterministic_spherical_fibonacci_distribution",
            "camera": "orthographic_fixed_roll",
        },
        "rendering": {
            "method": (
                "deterministic_surface_sample_depth_projection_with_gap_closing_"
                "and_visible_depth_smoothing"
            ),
            "surface_sample_count": sample_count,
            "maximum_surface_samples": PROOF_SHEET_MAX_SURFACE_SAMPLES,
            "source_mesh_vertex_count": len(mesh.vertices),
            "source_mesh_triangle_count": len(mesh.faces),
        },
        "limitations": [
            "Proof sheets are heuristic visual-review aids, not exact geometric checks.",
            (
                "Spherical sampling is broad but does not prove that every useful point of view "
                "is represented."
            ),
            (
                "Low-resolution sampled projections can omit small, internal, occluded, or "
                "sub-pixel interactions."
            ),
            (
                "A clear-looking projection does not prove collision clearance, assembly fit, "
                "tool access, thread engagement, manufacturability, or structural integrity."
            ),
            (
                "The compiled STL does not preserve semantic part identity; use assembly lint "
                "for existing or multi-part assembly inspection."
            ),
        ],
        "projections": projections,
    }
    serialized_manifest = (
        json.dumps(manifest_document, indent=2, sort_keys=True, ensure_ascii=True).encode("utf-8")
        + b"\n"
    )
    embedded_html = _index_html(
        design_name=design_name,
        mesh_sha256=mesh_sha256,
        view_count=view_count,
        resolution_px=resolution_px,
        views_per_sheet=views_per_sheet,
        projections=projections,
        images=images,
        embedded=True,
    )
    archive_html = _index_html(
        design_name=design_name,
        mesh_sha256=mesh_sha256,
        view_count=view_count,
        resolution_px=resolution_px,
        views_per_sheet=views_per_sheet,
        projections=projections,
        images=images,
        embedded=False,
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        _zip_entry(archive, "index.html", archive_html)
        _zip_entry(archive, "proof-sheet-manifest.json", serialized_manifest)
        for index, png in enumerate(images):
            _zip_entry(archive, f"projections/view-{index:04d}.png", png)
    return ProofSheetArtifacts(
        manifest=serialized_manifest,
        review_html=embedded_html,
        archive=buffer.getvalue(),
    )
