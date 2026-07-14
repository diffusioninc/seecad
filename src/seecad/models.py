"""Strict semantic design, artifact, analysis, and transport models."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

SafeIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$"
    ),
]
ScadIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=96, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"
    ),
]
MIN_GEOMETRY_MM = 1e-6
ASSEMBLY_ENVELOPE_TOLERANCE_MM = 1e-6


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


class Vec2(StrictModel):
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)

    @model_validator(mode="after")
    def finite(self) -> Vec2:
        if not all(math.isfinite(v) for v in (self.x, self.y)):
            raise ValueError("coordinates must be finite")
        return self

    def values(self) -> tuple[float, float]:
        return self.x, self.y


class Vec3(StrictModel):
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)
    z: float = Field(ge=-1_000_000, le=1_000_000)

    @model_validator(mode="after")
    def finite(self) -> Vec3:
        if not all(math.isfinite(v) for v in (self.x, self.y, self.z)):
            raise ValueError("coordinates must be finite")
        return self

    def values(self) -> tuple[float, float, float]:
        return self.x, self.y, self.z


ZERO_VEC3 = Vec3(x=0, y=0, z=0)
ONE_VEC3 = Vec3(x=1, y=1, z=1)


class Transform(StrictModel):
    translate: Vec3 = ZERO_VEC3
    rotate_degrees: Vec3 = ZERO_VEC3
    scale: Vec3 = ONE_VEC3

    @model_validator(mode="after")
    def positive_scale(self) -> Transform:
        if any(value < MIN_GEOMETRY_MM for value in self.scale.values()):
            raise ValueError(f"scale components must be at least {MIN_GEOMETRY_MM:g}")
        return self


class Box(StrictModel):
    kind: Literal["box"] = "box"
    size: Vec3
    center: bool = False

    @model_validator(mode="after")
    def positive_size(self) -> Box:
        if any(value < MIN_GEOMETRY_MM for value in self.size.values()):
            raise ValueError(f"box dimensions must be at least {MIN_GEOMETRY_MM:g} mm")
        return self


class RoundedBox(StrictModel):
    kind: Literal["rounded_box"] = "rounded_box"
    size: Vec3
    radius: float = Field(ge=MIN_GEOMETRY_MM, le=100_000)
    center: bool = False
    facets: int = Field(default=48, ge=12, le=512)

    @model_validator(mode="after")
    def radius_fits(self) -> RoundedBox:
        if any(value <= 2 * self.radius for value in self.size.values()):
            raise ValueError("rounded-box dimensions must each exceed twice the radius")
        return self


class Cylinder(StrictModel):
    kind: Literal["cylinder"] = "cylinder"
    radius: float = Field(ge=MIN_GEOMETRY_MM, le=100_000)
    height: float = Field(ge=MIN_GEOMETRY_MM, le=1_000_000)
    center: bool = False
    facets: int = Field(default=64, ge=12, le=1024)


class Cone(StrictModel):
    kind: Literal["cone"] = "cone"
    radius_bottom: float = Field(ge=MIN_GEOMETRY_MM, le=100_000)
    radius_top: float = Field(ge=0, le=100_000)
    height: float = Field(ge=MIN_GEOMETRY_MM, le=1_000_000)
    center: bool = False
    facets: int = Field(default=64, ge=12, le=1024)


class Sphere(StrictModel):
    kind: Literal["sphere"] = "sphere"
    radius: float = Field(ge=MIN_GEOMETRY_MM, le=100_000)
    facets: int = Field(default=64, ge=12, le=1024)


class Torus(StrictModel):
    kind: Literal["torus"] = "torus"
    major_radius: float = Field(ge=MIN_GEOMETRY_MM, le=100_000)
    minor_radius: float = Field(ge=MIN_GEOMETRY_MM, le=100_000)
    major_facets: int = Field(default=96, ge=12, le=1024)
    minor_facets: int = Field(default=48, ge=12, le=512)

    @model_validator(mode="after")
    def valid_radii(self) -> Torus:
        if self.minor_radius >= self.major_radius:
            raise ValueError("torus minor_radius must be smaller than major_radius")
        return self


class ExtrudedPolygon(StrictModel):
    kind: Literal["extruded_polygon"] = "extruded_polygon"
    points: tuple[Vec2, ...] = Field(min_length=3, max_length=512)
    height: float = Field(ge=MIN_GEOMETRY_MM, le=1_000_000)
    center: bool = False
    twist_degrees: float = Field(default=0, ge=-36_000, le=36_000)
    slices: int = Field(default=32, ge=1, le=2048)
    convexity: int = Field(default=10, ge=1, le=100)

    @field_validator("points", mode="before")
    @classmethod
    def freeze_points(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def nondegenerate_polygon(self) -> ExtrudedPolygon:
        area2 = sum(
            a.x * b.y - b.x * a.y
            for a, b in zip(self.points, self.points[1:] + self.points[:1], strict=True)
        )
        if math.isclose(area2, 0.0, abs_tol=1e-9):
            raise ValueError("polygon points must enclose a non-zero area")
        return self


class NumberArgument(StrictModel):
    kind: Literal["number"] = "number"
    value: float = Field(ge=-1_000_000, le=1_000_000)

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("argument must be finite")
        return value


class BooleanArgument(StrictModel):
    kind: Literal["boolean"] = "boolean"
    value: bool


class VectorArgument(StrictModel):
    kind: Literal["vector"] = "vector"
    values: tuple[float, ...] = Field(min_length=1, max_length=16)

    @field_validator("values", mode="before")
    @classmethod
    def freeze_values(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("values")
    @classmethod
    def finite_values(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if not all(math.isfinite(value) and abs(value) <= 1_000_000 for value in values):
            raise ValueError("vector arguments must contain bounded finite numbers")
        return values


ScadArgument = Annotated[
    NumberArgument | BooleanArgument | VectorArgument,
    Field(discriminator="kind"),
]


class NamedScadArgument(StrictModel):
    name: ScadIdentifier
    value: ScadArgument


class LibraryCall(StrictModel):
    """A safe, typed call into a specifically allowlisted vendored library."""

    kind: Literal["library_call"] = "library_call"
    library: Literal["nopscadlib"] = "nopscadlib"
    source_path: str = Field(min_length=1, max_length=240)
    module: ScadIdentifier
    arguments: tuple[ScadArgument, ...] = Field(default_factory=tuple, max_length=32)
    named_arguments: tuple[NamedScadArgument, ...] = Field(default_factory=tuple, max_length=32)

    @field_validator("arguments", "named_arguments", mode="before")
    @classmethod
    def freeze_arguments(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_named_arguments(self) -> LibraryCall:
        names = [argument.name for argument in self.named_arguments]
        if len(names) != len(set(names)):
            raise ValueError("named library argument names must be unique")
        return self

    @field_validator("source_path")
    @classmethod
    def safe_source_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if (
            value != normalized
            or normalized.startswith("/")
            or not normalized.endswith(".scad")
            or ".." in normalized.split("/")
            or not re.fullmatch(r"[A-Za-z0-9_./-]+\.scad", normalized)
        ):
            raise ValueError("source_path must be a safe relative .scad path")
        return normalized


Primitive = Annotated[
    Box | RoundedBox | Cylinder | Cone | Sphere | Torus | ExtrudedPolygon | LibraryCall,
    Field(discriminator="kind"),
]


Bounds3 = tuple[tuple[float, float, float], tuple[float, float, float]]


def _primitive_local_bounds(shape: Primitive) -> Bounds3 | None:
    """Return a conservative local AABB for primitives understood by the core schema."""

    if isinstance(shape, (Box, RoundedBox)):
        size = shape.size.values()
        if shape.center:
            half = tuple(value / 2 for value in size)
            return tuple(-value for value in half), half  # type: ignore[return-value]
        return (0.0, 0.0, 0.0), size
    if isinstance(shape, (Cylinder, Cone)):
        radius = (
            shape.radius
            if isinstance(shape, Cylinder)
            else max(shape.radius_bottom, shape.radius_top)
        )
        z_min = -shape.height / 2 if shape.center else 0.0
        return (-radius, -radius, z_min), (radius, radius, z_min + shape.height)
    if isinstance(shape, Sphere):
        radius = shape.radius
        return (-radius, -radius, -radius), (radius, radius, radius)
    if isinstance(shape, Torus):
        radial = shape.major_radius + shape.minor_radius
        return (-radial, -radial, -shape.minor_radius), (
            radial,
            radial,
            shape.minor_radius,
        )
    if isinstance(shape, ExtrudedPolygon):
        z_min = -shape.height / 2 if shape.center else 0.0
        if shape.twist_degrees:
            radial = max(math.hypot(point.x, point.y) for point in shape.points)
            return (-radial, -radial, z_min), (radial, radial, z_min + shape.height)
        return (
            min(point.x for point in shape.points),
            min(point.y for point in shape.points),
            z_min,
        ), (
            max(point.x for point in shape.points),
            max(point.y for point in shape.points),
            z_min + shape.height,
        )
    # Library calls are safe to compile, but their bounds are not part of the
    # allowlist signature. Multi-component assemblies must use primitives whose
    # conservative placement envelopes can be proven here.
    return None


def _rotate_xyz(point: tuple[float, float, float], degrees: Vec3) -> tuple[float, float, float]:
    """Apply OpenSCAD's vector rotation order to one scaled point."""

    x, y, z = point
    rx, ry, rz = (math.radians(value) for value in degrees.values())
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    return x, y, z


def _transformed_bounds(shape: Primitive, transform: Transform) -> Bounds3 | None:
    local = _primitive_local_bounds(shape)
    if local is None:
        return None
    low, high = local
    corners = []
    for x in (low[0], high[0]):
        for y in (low[1], high[1]):
            for z in (low[2], high[2]):
                scale = transform.scale.values()
                scaled = (
                    x * scale[0],
                    y * scale[1],
                    z * scale[2],
                )
                rotated = _rotate_xyz(scaled, transform.rotate_degrees)
                corners.append(
                    tuple(
                        value + offset
                        for value, offset in zip(rotated, transform.translate.values(), strict=True)
                    )
                )
    return (
        tuple(min(point[axis] for point in corners) for axis in range(3)),
        tuple(max(point[axis] for point in corners) for axis in range(3)),
    )  # type: ignore[return-value]


def _bounds_depths(left: Bounds3, right: Bounds3) -> tuple[float, float, float]:
    return tuple(
        min(left[1][axis], right[1][axis]) - max(left[0][axis], right[0][axis]) for axis in range(3)
    )  # type: ignore[return-value]


def _bounds_have_face_contact(left: Bounds3, right: Bounds3) -> bool:
    depths = _bounds_depths(left, right)
    return (
        all(depth >= -ASSEMBLY_ENVELOPE_TOLERANCE_MM for depth in depths)
        and sum(depth > ASSEMBLY_ENVELOPE_TOLERANCE_MM for depth in depths) >= 2
        and any(abs(depth) <= ASSEMBLY_ENVELOPE_TOLERANCE_MM for depth in depths)
    )


class ComponentKind(StrEnum):
    PART = "part"
    STOCK = "stock"
    CONNECTOR = "connector"
    FASTENER = "fastener"


class AssemblyComponent(StrictModel):
    id: SafeIdentifier
    name: str = Field(min_length=1, max_length=120)
    kind: ComponentKind
    purpose: str = Field(min_length=1, max_length=500)
    must_contact: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=16)

    @field_validator("kind", mode="before")
    @classmethod
    def parse_kind(cls, value: object) -> object:
        return ComponentKind(value) if isinstance(value, str) else value

    @field_validator("must_contact", mode="before")
    @classmethod
    def freeze_contacts(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def contact_contract(self) -> AssemblyComponent:
        if len(self.must_contact) != len(set(self.must_contact)):
            raise ValueError("must_contact component ids must be unique")
        minimum = 2 if self.kind == ComponentKind.CONNECTOR else 1
        if (
            self.kind in {ComponentKind.CONNECTOR, ComponentKind.FASTENER}
            and len(self.must_contact) < minimum
        ):
            raise ValueError(f"{self.kind.value} components require at least {minimum} contact(s)")
        return self


class PositiveSolid(StrictModel):
    id: SafeIdentifier
    name: str = Field(min_length=1, max_length=120)
    component_id: SafeIdentifier | None = None
    shape: Primitive
    transform: Transform = Transform()
    purpose: str = Field(default="primary volume", min_length=1, max_length=500)


class NegativeIntent(StrEnum):
    THROUGH_HOLE = "through_hole"
    BLIND_HOLE = "blind_hole"
    POCKET = "pocket"
    CLEARANCE = "clearance"
    RELIEF = "relief"
    OTHER = "other"


class NegativeFeature(StrictModel):
    id: SafeIdentifier
    name: str = Field(min_length=1, max_length=120)
    shape: Primitive
    transform: Transform = Transform()
    intent: NegativeIntent
    rationale: str = Field(min_length=1, max_length=1000)
    target_component_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=32)

    @field_validator("intent", mode="before")
    @classmethod
    def parse_intent(cls, value: object) -> object:
        return NegativeIntent(value) if isinstance(value, str) else value

    @field_validator("target_component_ids", mode="before")
    @classmethod
    def freeze_targets(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ToolAccessChannel(StrictModel):
    id: SafeIdentifier
    name: str = Field(min_length=1, max_length=120)
    start: Vec3
    end: Vec3
    tool_diameter: float = Field(ge=MIN_GEOMETRY_MM, le=100_000)
    radial_clearance: float = Field(default=0.5, ge=0, le=10_000)
    endpoint_overtravel: float = Field(default=1.0, ge=0, le=10_000)
    tool: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=1000)
    target_component_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple, max_length=32)
    facets: int = Field(default=64, ge=12, le=1024)

    @field_validator("target_component_ids", mode="before")
    @classmethod
    def freeze_targets(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def nonzero_path(self) -> ToolAccessChannel:
        squared = sum(
            (b - a) ** 2 for a, b in zip(self.start.values(), self.end.values(), strict=True)
        )
        if squared <= 1e-12:
            raise ValueError("tool access channel start and end must differ")
        return self


class PrintProfile(StrictModel):
    process: Literal["fdm", "sla", "sls", "unknown"] = "fdm"
    material: str = Field(default="PLA", min_length=1, max_length=64)
    nozzle_diameter: float = Field(default=0.4, gt=0, le=10)
    layer_height: float = Field(default=0.2, gt=0, le=10)
    minimum_wall: float = Field(default=0.8, gt=0, le=100)
    minimum_clearance: float = Field(default=0.2, ge=0, le=100)
    maximum_unsupported_overhang_degrees: float = Field(default=45, ge=0, le=90)
    build_volume: Vec3 = Vec3(x=220, y=220, z=250)

    @model_validator(mode="after")
    def plausible_profile(self) -> PrintProfile:
        if self.process == "fdm" and self.layer_height > self.nozzle_diameter:
            raise ValueError("FDM layer height should not exceed nozzle diameter")
        if any(value <= 0 for value in self.build_volume.values()):
            raise ValueError("build volume dimensions must be positive")
        return self


def canonical_print_profile_bytes(profile: PrintProfile) -> bytes:
    """Return the stable byte representation used to identify analysis inputs."""

    return json.dumps(
        profile.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def print_profile_sha256(profile: PrintProfile) -> str:
    return hashlib.sha256(canonical_print_profile_bytes(profile)).hexdigest()


class DesignSpec(StrictModel):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    name: str = Field(min_length=1, max_length=120)
    intent: str = Field(min_length=1, max_length=2000)
    units: Literal["mm"]
    components: tuple[AssemblyComponent, ...] = Field(default_factory=tuple, max_length=128)
    positive_solids: tuple[PositiveSolid, ...] = Field(min_length=1, max_length=128)
    negative_features: tuple[NegativeFeature, ...] = Field(default_factory=tuple, max_length=128)
    tool_access_channels: tuple[ToolAccessChannel, ...] = Field(
        default_factory=tuple, max_length=128
    )
    print_profile: PrintProfile = PrintProfile()
    assumptions: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    notes: tuple[str, ...] = Field(default_factory=tuple, max_length=64)

    @field_validator(
        "positive_solids",
        "negative_features",
        "tool_access_channels",
        "components",
        "assumptions",
        "notes",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def semantic_assembly_contract(self) -> DesignSpec:
        ids = [
            *(solid.id for solid in self.positive_solids),
            *(feature.id for feature in self.negative_features),
            *(channel.id for channel in self.tool_access_channels),
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("all solid, feature, and channel ids must be globally unique")
        if self.schema_version == "1.0":
            if (
                self.components
                or any(solid.component_id for solid in self.positive_solids)
                or any(feature.target_component_ids for feature in self.negative_features)
                or any(channel.target_component_ids for channel in self.tool_access_channels)
            ):
                raise ValueError("schema 1.0 cannot contain component-scoped assembly fields")
            return self

        if not self.components:
            raise ValueError("schema 1.1 requires explicit assembly components")
        component_ids = [component.id for component in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("assembly component ids must be unique")
        known_components = set(component_ids)
        for component in self.components:
            if component.id in component.must_contact:
                raise ValueError(f"component {component.id!r} cannot contact itself")
            unknown = set(component.must_contact) - known_components
            if unknown:
                raise ValueError(
                    f"component {component.id!r} references unknown contacts: {sorted(unknown)}"
                )

        solids_by_component: dict[str, list[tuple[PositiveSolid, Bounds3]]] = {
            component_id: [] for component_id in component_ids
        }
        owned_components: set[str] = set()
        multi_component = len(component_ids) > 1
        for solid in self.positive_solids:
            if solid.component_id not in known_components:
                raise ValueError(
                    f"positive solid {solid.id!r} must name a declared assembly component"
                )
            owned_components.add(solid.component_id)
            bounds = _transformed_bounds(solid.shape, solid.transform)
            if multi_component and bounds is None:
                raise ValueError(
                    f"positive solid {solid.id!r} has no bounded assembly envelope; "
                    "multi-component assemblies require core primitives"
                )
            if bounds is not None:
                solids_by_component[solid.component_id].append((solid, bounds))
        unused = [
            component_id for component_id in component_ids if component_id not in owned_components
        ]
        if unused:
            raise ValueError(f"assembly components must own positive solids: {unused}")

        negative_entities: tuple[NegativeFeature | ToolAccessChannel, ...] = (
            *self.negative_features,
            *self.tool_access_channels,
        )
        for feature in negative_entities:
            targets = feature.target_component_ids
            if not targets:
                raise ValueError(f"negative feature {feature.id!r} requires component targets")
            if len(targets) != len(set(targets)):
                raise ValueError(f"negative feature {feature.id!r} has duplicate component targets")
            unknown = set(targets) - known_components
            if unknown:
                raise ValueError(
                    f"negative feature {feature.id!r} targets unknown components: {sorted(unknown)}"
                )

        for left_index, left_id in enumerate(component_ids):
            for right_id in component_ids[left_index + 1 :]:
                for left_solid, left_bounds in solids_by_component[left_id]:
                    for right_solid, right_bounds in solids_by_component[right_id]:
                        depths = _bounds_depths(left_bounds, right_bounds)
                        if all(depth > ASSEMBLY_ENVELOPE_TOLERANCE_MM for depth in depths):
                            raise ValueError(
                                "assembly component envelopes overlap: "
                                f"{left_id!r}/{left_solid.id!r} and "
                                f"{right_id!r}/{right_solid.id!r}"
                            )

        for component in self.components:
            for contact_id in component.must_contact:
                has_bounded_contact = any(
                    _bounds_have_face_contact(left_bounds, right_bounds)
                    for _, left_bounds in solids_by_component[component.id]
                    for _, right_bounds in solids_by_component[contact_id]
                )
                if not has_bounded_contact:
                    raise ValueError(
                        f"component {component.id!r} does not contact required component "
                        f"{contact_id!r} across a bounded envelope face"
                    )
        return self

    @model_serializer(mode="wrap")
    def serialize_versioned(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = cast(dict[str, Any], handler(self))
        if self.schema_version == "1.0":
            data.pop("components", None)
            for solid in data.get("positive_solids", []):
                solid.pop("component_id", None)
            for feature in data.get("negative_features", []):
                feature.pop("target_component_ids", None)
            for channel in data.get("tool_access_channels", []):
                channel.pop("target_component_ids", None)
        return data


class ImageEvidence(StrictModel):
    url: str = Field(min_length=1, max_length=12_000_000)
    detail: Literal["auto", "low", "high", "original"] = "original"

    @field_validator("url")
    @classmethod
    def safe_image_url(cls, value: str) -> str:
        if value.startswith("https://"):
            if len(value.encode("utf-8")) > 8 * 1024:
                raise ValueError("HTTPS image URLs cannot exceed 8 KiB")
            return value
        match = re.fullmatch(r"data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/=]+)", value)
        if match is None:
            raise ValueError("image must be an HTTPS URL or supported base64 data URL")
        try:
            decoded = base64.b64decode(match.group(2), validate=True)
        except ValueError as exc:
            raise ValueError("image data URL contains invalid base64") from exc
        if len(decoded) > 8 * 1024 * 1024:
            raise ValueError("image evidence cannot exceed 8 MiB")
        return value


class ArtifactRef(StrictModel):
    sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    size_bytes: int = Field(ge=0)
    media_type: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+(?:; charset=utf-8)?$",
    )
    filename: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9_.-]+$")


class RevisionResponse(StrictModel):
    design_id: Annotated[str, StringConstraints(pattern=r"^dsgn_[a-f0-9]{24}$")]
    revision_id: Annotated[str, StringConstraints(pattern=r"^rev_[a-f0-9]{24}$")]
    parent_revision_id: str | None = None
    created_at: datetime
    spec: DesignSpec
    artifacts: dict[str, ArtifactRef]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class DesignHistoryResponse(StrictModel):
    design_id: str
    revisions: list[RevisionResponse]


class Confidence(StrEnum):
    EXACT = "exact"
    BOUNDED = "bounded"
    HEURISTIC = "heuristic"
    UNAVAILABLE = "unavailable"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Measurement(StrictModel):
    name: str
    value: float | bool | int | list[float] | None
    unit: str | None = None
    confidence: Confidence
    basis: str


class Finding(StrictModel):
    code: str
    severity: Severity
    message: str
    confidence: Confidence
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class MeshAnalysis(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    mesh_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    print_profile: PrintProfile
    print_profile_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    analyzed_at: datetime
    measurements: list[Measurement]
    findings: list[Finding]
    printable: bool | None
    summary: str

    @model_validator(mode="after")
    def profile_digest_matches(self) -> MeshAnalysis:
        expected = print_profile_sha256(self.print_profile)
        if self.print_profile_sha256 != expected:
            raise ValueError("print_profile_sha256 does not match the canonical print profile")
        return self


class AnalysisResponse(StrictModel):
    revision: RevisionResponse
    analysis: MeshAnalysis


class DifferenceEntry(StrictModel):
    path: str
    left: JsonValue | None = None
    right: JsonValue | None = None


class ComparisonResponse(StrictModel):
    left_revision_id: str
    right_revision_id: str
    same_spec: bool
    differences: list[DifferenceEntry]
    artifact_changes: dict[str, JsonValue]


class CreateDesignRequest(StrictModel):
    prompt: str | None = Field(default=None, min_length=1, max_length=20_000)
    spec: DesignSpec | None = None
    images: list[ImageEvidence] = Field(default_factory=list, max_length=4)
    requested_profile: PrintProfile | None = None
    load_case: str | None = Field(default=None, min_length=1, max_length=1000)
    dimensional_tolerance: float | None = Field(default=None, ge=0, le=100)
    infill_percent: float | None = Field(default=None, ge=0, le=100)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def has_input(self) -> CreateDesignRequest:
        if (self.spec is None) == (self.prompt is None):
            raise ValueError("provide exactly one of prompt or spec")
        if self.images and self.prompt is None:
            raise ValueError("image evidence requires a planning prompt")
        planning_constraints = (
            self.requested_profile,
            self.load_case,
            self.dimensional_tolerance,
            self.infill_percent,
        )
        if any(value is not None for value in planning_constraints) and self.prompt is None:
            raise ValueError("manufacturing and load constraints require a planning prompt")
        encoded = json.dumps(self.metadata, separators=(",", ":")).encode("utf-8")
        if len(self.metadata) > 64 or len(encoded) > 64 * 1024:
            raise ValueError("metadata exceeds the 64-key or 64-KiB limit")
        if any(not key or len(key) > 64 for key in self.metadata):
            raise ValueError("metadata keys must be between 1 and 64 characters")
        return self


class CreateRevisionRequest(CreateDesignRequest):
    parent_revision_id: Annotated[str, StringConstraints(pattern=r"^rev_[a-f0-9]{24}$")]


class CompileRequest(StrictModel):
    format: Literal["stl", "3mf"] = "stl"


class AnalyzeRequest(StrictModel):
    auto_compile: bool = True
    profile: PrintProfile | None = None


class ApprovalRequest(StrictModel):
    attestor: str = Field(default="Human reviewer", min_length=1, max_length=120)
    statement: str = Field(
        default="Reviewed the exact compiled mesh and analysis evidence for this revision.",
        min_length=1,
        max_length=2000,
    )


class CompareRequest(StrictModel):
    left_revision_id: str
    right_revision_id: str


class PlannedDesign(StrictModel):
    spec: DesignSpec
    rationale: str = Field(min_length=1, max_length=4000)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=32)


class HealthResponse(StrictModel):
    status: Literal["ok", "degraded"]
    version: str
    planner_configured: bool
    openscad_available: bool
    storage_writable: bool
