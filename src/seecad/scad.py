"""Deterministic OpenSCAD generation from the semantic design graph."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seecad.errors import InvalidDesignError
from seecad.models import (
    ASSEMBLY_ENVELOPE_TOLERANCE_MM,
    BooleanArgument,
    Box,
    Cone,
    Cylinder,
    DesignSpec,
    ExtrudedPolygon,
    LibraryCall,
    NumberArgument,
    Primitive,
    RoundedBox,
    ScadArgument,
    Sphere,
    ToolAccessChannel,
    Torus,
    Transform,
    VectorArgument,
)

_LIBRARY_SIGNATURES: dict[tuple[str, str], tuple[tuple[str, str, bool], ...]] = {
    ("utils/core/rounded_rectangle.scad", "rounded_rectangle"): (
        ("size", "vec3", True),
        ("r", "number", True),
        ("center", "boolean", False),
        ("xy_center", "boolean", False),
    ),
    ("utils/rounded_cylinder.scad", "rounded_cylinder"): (
        ("r", "number", True),
        ("h", "number", True),
        ("r2", "number", True),
        ("ir", "number", False),
        ("angle", "number", False),
    ),
    ("utils/core/polyholes.scad", "poly_cylinder"): (
        ("r", "number", True),
        ("h", "number", True),
        ("center", "boolean", False),
        ("sides", "number", False),
        ("chamfer", "boolean", False),
        ("twist", "number", False),
    ),
    ("utils/core/teardrops.scad", "teardrop"): (
        ("h", "number", True),
        ("r", "number", True),
        ("center", "boolean", False),
        ("truncate", "boolean", False),
        ("chamfer", "number", False),
        ("chamfer_both_ends", "boolean", False),
        ("plus", "boolean", False),
    ),
    ("utils/core/teardrops.scad", "teardrop_plus"): (
        ("h", "number", True),
        ("r", "number", True),
        ("center", "boolean", False),
        ("truncate", "boolean", False),
        ("chamfer", "number", False),
        ("chamfer_both_ends", "boolean", False),
    ),
    ("utils/core/teardrops.scad", "tearslot"): (
        ("h", "number", True),
        ("r", "number", True),
        ("w", "number", True),
        ("center", "boolean", False),
        ("chamfer", "number", False),
        ("chamfer_both_ends", "boolean", False),
        ("plus", "boolean", False),
    ),
}


@dataclass(frozen=True, slots=True)
class GeneratedScad:
    source: str
    manifest: dict[str, Any]


def canonical_spec_bytes(spec: DesignSpec) -> bytes:
    return json.dumps(spec.model_dump(mode="json"), separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _number(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise InvalidDesignError("SCAD values must be finite")
    if value == 0:
        return "0"
    return format(value, ".17g")


def _vector(values: tuple[float, ...] | list[float]) -> str:
    return "[" + ", ".join(_number(value) for value in values) + "]"


def _module_id(entity_id: str) -> str:
    encoded = "".join("_u" if char == "_" else "_h" if char == "-" else char for char in entity_id)
    return f"id_{encoded}"


def _indent(lines: list[str], spaces: int = 2) -> list[str]:
    prefix = " " * spaces
    return [prefix + line if line else line for line in lines]


def _argument(argument: ScadArgument) -> str:
    if isinstance(argument, NumberArgument):
        return _number(argument.value)
    if isinstance(argument, BooleanArgument):
        return "true" if argument.value else "false"
    if isinstance(argument, VectorArgument):
        return _vector(argument.values)
    raise InvalidDesignError("unsupported library argument")


def _primitive_lines(shape: Primitive) -> list[str]:
    if isinstance(shape, Box):
        return [
            f"cube({_vector(shape.size.values())}, center={'true' if shape.center else 'false'});"
        ]
    if isinstance(shape, RoundedBox):
        core = tuple(value - 2 * shape.radius for value in shape.size.values())
        lines: list[str] = []
        if not shape.center:
            lines.append(f"translate({_vector((shape.radius,) * 3)}) {{")
        lines.extend(
            [
                "minkowski() {",
                f"  cube({_vector(core)}, center={'true' if shape.center else 'false'});",
                f"  sphere(r={_number(shape.radius)}, $fn={shape.facets});",
                "}",
            ]
        )
        if not shape.center:
            lines.append("}")
        return lines
    if isinstance(shape, Cylinder):
        return [
            "cylinder("
            f"h={_number(shape.height)}, r={_number(shape.radius)}, "
            f"center={'true' if shape.center else 'false'}, $fn={shape.facets});"
        ]
    if isinstance(shape, Cone):
        return [
            "cylinder("
            f"h={_number(shape.height)}, r1={_number(shape.radius_bottom)}, "
            f"r2={_number(shape.radius_top)}, center={'true' if shape.center else 'false'}, "
            f"$fn={shape.facets});"
        ]
    if isinstance(shape, Sphere):
        return [f"sphere(r={_number(shape.radius)}, $fn={shape.facets});"]
    if isinstance(shape, Torus):
        return [
            f"rotate_extrude(convexity=10, $fn={shape.major_facets}) {{",
            f"  translate([{_number(shape.major_radius)}, 0, 0])",
            f"    circle(r={_number(shape.minor_radius)}, $fn={shape.minor_facets});",
            "}",
        ]
    if isinstance(shape, ExtrudedPolygon):
        points = "[" + ", ".join(_vector(point.values()) for point in shape.points) + "]"
        return [
            "linear_extrude("
            f"height={_number(shape.height)}, center={'true' if shape.center else 'false'}, "
            f"twist={_number(shape.twist_degrees)}, slices={shape.slices}, "
            f"convexity={shape.convexity}) {{",
            f"  polygon(points={points});",
            "}",
        ]
    if isinstance(shape, LibraryCall):
        positional = [_argument(argument) for argument in shape.arguments]
        named = [
            f"{argument.name}={_argument(argument.value)}"
            for argument in sorted(shape.named_arguments, key=lambda item: item.name)
        ]
        return [f"{shape.module}({', '.join([*positional, *named])});"]
    raise InvalidDesignError("unsupported primitive", details={"type": type(shape).__name__})


def _transformed(shape: Primitive, transform: Transform) -> list[str]:
    wrappers = [
        f"translate({_vector(transform.translate.values())})",
        f"rotate({_vector(transform.rotate_degrees.values())})",
        f"scale({_vector(transform.scale.values())})",
    ]
    lines: list[str] = []
    for index, wrapper in enumerate(wrappers):
        lines.append("  " * index + wrapper + " {")
    lines.extend(_indent(_primitive_lines(shape), 2 * len(wrappers)))
    for index in reversed(range(len(wrappers))):
        lines.append("  " * index + "}")
    return lines


def _channel_lines(channel: ToolAccessChannel) -> list[str]:
    start = channel.start.values()
    end = channel.end.values()
    vector = tuple(b - a for a, b in zip(start, end, strict=True))
    base_length = math.sqrt(sum(component * component for component in vector))
    unit = tuple(component / base_length for component in vector)
    origin = tuple(
        coordinate - direction * channel.endpoint_overtravel
        for coordinate, direction in zip(start, unit, strict=True)
    )
    length = base_length + 2 * channel.endpoint_overtravel
    angle = math.degrees(math.acos(max(-1.0, min(1.0, unit[2]))))
    axis = (-unit[1], unit[0], 0.0)
    if math.sqrt(axis[0] ** 2 + axis[1] ** 2) < 1e-12:
        axis = (1.0, 0.0, 0.0)
    radius = channel.tool_diameter / 2 + channel.radial_clearance
    return [
        f"translate({_vector(origin)}) {{",
        f"  rotate(a={_number(angle)}, v={_vector(axis)}) {{",
        "    cylinder("
        f"h={_number(length)}, r={_number(radius)}, center=false, "
        f"$fn={channel.facets});",
        "  }",
        "}",
    ]


def _library_provenance(root: Path | None) -> dict[str, str | None]:
    unresolved: dict[str, str | None] = {
        "upstream": "https://github.com/nophead/NopSCADlib",
        "revision": None,
        "tree_sha256": None,
        "license": None,
    }
    if root is None:
        return unresolved
    manifest_path = root.parent / "NopSCADlib.UPSTREAM.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return unresolved
    revision = payload.get("revision")
    tree_sha256 = payload.get("tree_sha256")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}", revision):
        return unresolved
    if not isinstance(tree_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", tree_sha256):
        return unresolved
    digest_input = bytearray()
    try:
        files = sorted(
            (path for path in root.rglob("*") if path.is_file() and not path.is_symlink()),
            key=lambda path: f"vendor/NopSCADlib/{path.relative_to(root).as_posix()}",
        )
        for path in files:
            relative = path.relative_to(root).as_posix()
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            digest_input.extend(f"{file_hash}  vendor/NopSCADlib/{relative}\n".encode())
    except OSError:
        return unresolved
    if hashlib.sha256(digest_input).hexdigest() != tree_sha256:
        return unresolved
    return {
        "upstream": payload.get("upstream") if isinstance(payload.get("upstream"), str) else None,
        "revision": revision,
        "tree_sha256": tree_sha256,
        "license": payload.get("license") if isinstance(payload.get("license"), str) else None,
    }


class ScadGenerator:
    """Render a design without accepting any arbitrary source fragments."""

    def __init__(self, *, nopscad_root: Path | None = None) -> None:
        self.nopscad_root = nopscad_root.expanduser().resolve() if nopscad_root else None
        self._provenance: dict[str, str | None] | None = None

    def _verified_provenance(self) -> dict[str, str | None]:
        if self._provenance is None:
            self._provenance = _library_provenance(self.nopscad_root)
        return self._provenance

    def generate(self, spec: DesignSpec) -> GeneratedScad:
        if spec.schema_version != "1.1":
            raise InvalidDesignError(
                "legacy schema 1.0 designs are read-only; revise the design to component-scoped "
                "schema 1.1 before generating or compiling new artifacts"
            )
        library_calls: list[LibraryCall] = []
        library_calls.extend(
            solid.shape for solid in spec.positive_solids if isinstance(solid.shape, LibraryCall)
        )
        library_calls.extend(
            feature.shape
            for feature in spec.negative_features
            if isinstance(feature.shape, LibraryCall)
        )
        for call in library_calls:
            self._validate_library_source(call)

        extra_include_paths = sorted(
            {
                f"NopSCADlib/{call.source_path}"
                for call in library_calls
                if call.source_path == "utils/rounded_cylinder.scad"
            }
        )
        lines = [
            "// Generated by SeeCAD. Edit the semantic DesignSpec, not this file.",
            'seecad_units = "mm";',
            f"extrusion_width = {_number(spec.print_profile.nozzle_diameter)};",
            f"layer_height = {_number(spec.print_profile.layer_height)};",
            "$fa = 6;",
            "$fs = 0.4;",
        ]
        if library_calls:
            lines.append("include <NopSCADlib/core.scad>;")
        lines.extend(f"include <{path}>;" for path in extra_include_paths)
        lines.append("")

        positive_modules: list[str] = []
        positive_modules_by_component: dict[str, list[str]] = {
            component.id: [] for component in spec.components
        }
        for solid in spec.positive_solids:
            module = f"positive_{_module_id(solid.id)}"
            positive_modules.append(module)
            if solid.component_id is None:  # guarded by DesignSpec 1.1 validation
                raise InvalidDesignError(
                    "positive solid has no assembly component", details={"solid_id": solid.id}
                )
            positive_modules_by_component[solid.component_id].append(module)
            lines.extend(
                [
                    f"module {module}() {{",
                    *_indent(_transformed(solid.shape, solid.transform)),
                    "}",
                    "",
                ]
            )

        negative_modules: list[str] = []
        for feature in spec.negative_features:
            module = f"negative_{_module_id(feature.id)}"
            negative_modules.append(module)
            lines.extend(
                [
                    f"module {module}() {{",
                    *_indent(_transformed(feature.shape, feature.transform)),
                    "}",
                    "",
                ]
            )

        channel_modules: list[str] = []
        for channel in spec.tool_access_channels:
            module = f"tool_access_{_module_id(channel.id)}"
            channel_modules.append(module)
            lines.extend([f"module {module}() {{", *_indent(_channel_lines(channel)), "}", ""])

        component_modules: dict[str, str] = {}
        for component in spec.components:
            module = f"component_positive_{_module_id(component.id)}"
            component_modules[component.id] = module
            lines.extend([f"module {module}() {{", "  union() {"])
            lines.extend(
                f"    {positive_module}();"
                for positive_module in positive_modules_by_component[component.id]
            )
            lines.extend(["  }", "}", ""])

        scoped_negative_modules: list[str] = []
        negative_scopes: dict[str, list[str]] = {}
        for feature, raw_module in zip(spec.negative_features, negative_modules, strict=True):
            scoped_module = f"scoped_negative_{_module_id(feature.id)}"
            scoped_negative_modules.append(scoped_module)
            negative_scopes[feature.id] = list(feature.target_component_ids)
            lines.extend([f"module {scoped_module}() {{", "  intersection() {"])
            lines.extend([f"    {raw_module}();", "    union() {"])
            lines.extend(
                f"      {component_modules[component_id]}();"
                for component_id in feature.target_component_ids
            )
            lines.extend(["    }", "  }", "}", ""])

        scoped_channel_modules: list[str] = []
        channel_scopes: dict[str, list[str]] = {}
        for channel, raw_module in zip(spec.tool_access_channels, channel_modules, strict=True):
            scoped_module = f"scoped_tool_access_{_module_id(channel.id)}"
            scoped_channel_modules.append(scoped_module)
            channel_scopes[channel.id] = list(channel.target_component_ids)
            lines.extend([f"module {scoped_module}() {{", "  intersection() {"])
            lines.extend([f"    {raw_module}();", "    union() {"])
            lines.extend(
                f"      {component_modules[component_id]}();"
                for component_id in channel.target_component_ids
            )
            lines.extend(["    }", "  }", "}", ""])

        lines.extend(["module positive_volume() {", "  union() {"])
        lines.extend(f"    {module}();" for module in component_modules.values())
        lines.extend(["  }", "}", "", "module negative_volume() {", "  union() {"])
        lines.extend(
            f"    {module}();" for module in [*scoped_negative_modules, *scoped_channel_modules]
        )
        lines.extend(
            [
                "  }",
                "}",
                "",
                "module seecad_model() {",
                "  difference() {",
                "    positive_volume();",
                "    negative_volume();",
                "  }",
                "}",
                "",
                "seecad_model();",
                "",
            ]
        )
        source = "\n".join(lines)
        spec_bytes = canonical_spec_bytes(spec)
        provenance = self._verified_provenance() if library_calls else {}
        manifest: dict[str, Any] = {
            "schema_version": "1.1",
            "generator": "seecad.scad/2",
            "units": spec.units,
            "spec_sha256": _sha256(spec_bytes),
            "scad_sha256": _sha256(source.encode("utf-8")),
            "boolean_strategy": "single_component_scoped_negative_difference_pass",
            "boolean_scope": (
                "design_level_csg_with_component_intersection_masks; audited library "
                "primitives may contain internal CSG"
            ),
            "assembly_validation": {
                "status": "passed",
                "component_non_interference": "bounded_transformed_aabb",
                "required_contacts": "bounded_transformed_aabb_face_contact",
                "negative_scope_ownership": "exact_by_construction",
                "tolerance_mm": ASSEMBLY_ENVELOPE_TOLERANCE_MM,
            },
            "modules": {
                "positive": positive_modules,
                "components": component_modules,
                "negative": negative_modules,
                "tool_access": channel_modules,
                "scoped_negative": scoped_negative_modules,
                "scoped_tool_access": scoped_channel_modules,
            },
            "negative_targets": negative_scopes,
            "tool_access_targets": channel_scopes,
            "libraries": [
                {
                    "library": call.library,
                    "source_path": call.source_path,
                    "module": call.module,
                    "vendored_root": "vendor/NopSCADlib",
                    **provenance,
                    "provenance_status": "pinned" if provenance["revision"] else "unresolved",
                    "phase_safety": "audited_geometry_primitive",
                }
                for call in library_calls
            ],
        }
        return GeneratedScad(source=source, manifest=manifest)

    def _validate_library_source(self, call: LibraryCall) -> None:
        if call.library != "nopscadlib":
            raise InvalidDesignError(
                "library is not allowlisted", details={"library": call.library}
            )
        signature = _LIBRARY_SIGNATURES.get((call.source_path, call.module))
        if signature is None:
            raise InvalidDesignError(
                "NopSCADlib module is not in the audited model-call registry",
                details={"source_path": call.source_path, "module": call.module},
            )
        if self.nopscad_root is None or not self.nopscad_root.is_dir():
            raise InvalidDesignError("the pinned NopSCADlib root is unavailable")
        if self._verified_provenance()["revision"] is None:
            raise InvalidDesignError("NopSCADlib provenance is missing or invalid")
        candidate = (self.nopscad_root / call.source_path).resolve()
        if self.nopscad_root not in candidate.parents or not candidate.is_file():
            raise InvalidDesignError(
                "NopSCADlib source file is not present in the vendored library",
                details={"source_path": call.source_path},
            )
        self._validate_library_signature(call, signature)

    @staticmethod
    def _validate_library_signature(
        call: LibraryCall, signature: tuple[tuple[str, str, bool], ...]
    ) -> None:
        if len(call.arguments) > len(signature):
            raise InvalidDesignError("too many positional library arguments")
        bound = {name for name, _kind, _required in signature[: len(call.arguments)]}
        parameter_map = {name: (kind, required) for name, kind, required in signature}
        for positional_argument, (_name, kind, _required) in zip(
            call.arguments, signature, strict=False
        ):
            ScadGenerator._require_argument_kind(positional_argument, kind)
        for named_argument in call.named_arguments:
            if named_argument.name not in parameter_map:
                raise InvalidDesignError(
                    "unknown named library argument",
                    details={"name": named_argument.name},
                )
            if named_argument.name in bound:
                raise InvalidDesignError(
                    "library argument is bound both positionally and by name",
                    details={"name": named_argument.name},
                )
            ScadGenerator._require_argument_kind(
                named_argument.value, parameter_map[named_argument.name][0]
            )
            bound.add(named_argument.name)
        missing = [name for name, _kind, required in signature if required and name not in bound]
        if missing:
            raise InvalidDesignError(
                "required library arguments are missing", details={"missing": missing}
            )

    @staticmethod
    def _require_argument_kind(argument: ScadArgument, kind: str) -> None:
        if kind == "number":
            valid = isinstance(argument, NumberArgument)
        elif kind == "boolean":
            valid = isinstance(argument, BooleanArgument)
        else:
            valid = isinstance(argument, VectorArgument) and len(argument.values) == 3
        if not valid:
            raise InvalidDesignError(
                "library argument has the wrong semantic type",
                details={"expected": kind},
            )
