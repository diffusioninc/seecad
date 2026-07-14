"""OpenAI-compatible planner output and its strict domain conversion.

The public domain model intentionally uses discriminated unions because they are ideal
for human/API callers.  The Responses Structured Outputs boundary uses this separate,
flat shape model: every possible parameter is present, unused parameters are ``null``,
and no ``oneOf`` schema is generated.  Conversion is deterministic and rejects missing
or stray kind-specific parameters before constructing the authoritative domain model.

The model may select a small semantic NopSCADlib vocabulary.  Those selections map to
fixed, audited paths, modules, and signatures; the model never supplies source paths,
module names, arguments, or raw OpenSCAD.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from seecad.models import (
    BooleanArgument,
    Box,
    Cone,
    Cylinder,
    DesignSpec,
    ExtrudedPolygon,
    LibraryCall,
    NamedScadArgument,
    NegativeFeature,
    NegativeIntent,
    NumberArgument,
    PlannedDesign,
    PositiveSolid,
    PrintProfile,
    RoundedBox,
    Sphere,
    ToolAccessChannel,
    Torus,
    Transform,
    Vec2,
    Vec3,
    VectorArgument,
)

PlannerShapeKind = Literal[
    "box",
    "rounded_box",
    "cylinder",
    "cone",
    "sphere",
    "torus",
    "extruded_polygon",
    "nop_rounded_rectangle",
    "nop_rounded_cylinder",
    "nop_poly_cylinder",
    "nop_teardrop",
    "nop_teardrop_plus",
    "nop_tearslot",
]

_SHAPE_PARAMETER_FIELDS = (
    "size",
    "radius",
    "height",
    "center",
    "facets",
    "radius_bottom",
    "radius_top",
    "major_radius",
    "minor_radius",
    "major_facets",
    "minor_facets",
    "points",
    "twist_degrees",
    "slices",
    "convexity",
    "edge_radius",
    "slot_width",
)

_KIND_PARAMETERS: dict[str, frozenset[str]] = {
    "box": frozenset({"size", "center"}),
    "rounded_box": frozenset({"size", "radius", "center", "facets"}),
    "cylinder": frozenset({"radius", "height", "center", "facets"}),
    "cone": frozenset({"radius_bottom", "radius_top", "height", "center", "facets"}),
    "sphere": frozenset({"radius", "facets"}),
    "torus": frozenset({"major_radius", "minor_radius", "major_facets", "minor_facets"}),
    "extruded_polygon": frozenset(
        {"points", "height", "center", "twist_degrees", "slices", "convexity"}
    ),
    "nop_rounded_rectangle": frozenset({"size", "radius", "center"}),
    "nop_rounded_cylinder": frozenset({"radius", "height", "edge_radius"}),
    "nop_poly_cylinder": frozenset({"radius", "height", "center"}),
    "nop_teardrop": frozenset({"radius", "height", "center"}),
    "nop_teardrop_plus": frozenset({"radius", "height", "center"}),
    "nop_tearslot": frozenset({"radius", "height", "center", "slot_width"}),
}


class PlannerModel(BaseModel):
    """Strict transient model used only at the OpenAI trust boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


class PlannerVec2(PlannerModel):
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)

    def to_domain(self) -> Vec2:
        return Vec2(x=self.x, y=self.y)


class PlannerVec3(PlannerModel):
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)
    z: float = Field(ge=-1_000_000, le=1_000_000)

    def to_domain(self) -> Vec3:
        return Vec3(x=self.x, y=self.y, z=self.z)


class PlannerTransform(PlannerModel):
    translate: PlannerVec3
    rotate_degrees: PlannerVec3
    scale: PlannerVec3

    def to_domain(self) -> Transform:
        return Transform(
            translate=self.translate.to_domain(),
            rotate_degrees=self.rotate_degrees.to_domain(),
            scale=self.scale.to_domain(),
        )


def _required[T](value: T | None, *, field: str, kind: str) -> T:
    if value is None:
        raise ValueError(f"shape kind {kind!r} requires non-null {field!r}")
    return value


def _number_argument(name: str, value: float) -> NamedScadArgument:
    return NamedScadArgument(name=name, value=NumberArgument(value=value))


def _boolean_argument(name: str, value: bool) -> NamedScadArgument:
    return NamedScadArgument(name=name, value=BooleanArgument(value=value))


def _vector_argument(name: str, value: PlannerVec3) -> NamedScadArgument:
    return NamedScadArgument(name=name, value=VectorArgument(values=value.to_domain().values()))


class PlannerShape(PlannerModel):
    """One flat shape record; every field is required and unused fields are null."""

    kind: PlannerShapeKind
    size: PlannerVec3 | None = Field(description="box size; null for other kinds")
    radius: float | None = Field(ge=1e-6, le=100_000)
    height: float | None = Field(ge=1e-6, le=1_000_000)
    center: bool | None
    facets: int | None = Field(ge=12, le=1024)
    radius_bottom: float | None = Field(ge=1e-6, le=100_000)
    radius_top: float | None = Field(ge=0, le=100_000)
    major_radius: float | None = Field(ge=1e-6, le=100_000)
    minor_radius: float | None = Field(ge=1e-6, le=100_000)
    major_facets: int | None = Field(ge=12, le=1024)
    minor_facets: int | None = Field(ge=12, le=512)
    points: list[PlannerVec2] | None = Field(min_length=3, max_length=512)
    twist_degrees: float | None = Field(ge=-36_000, le=36_000)
    slices: int | None = Field(ge=1, le=2048)
    convexity: int | None = Field(ge=1, le=100)
    edge_radius: float | None = Field(ge=1e-6, le=100_000)
    slot_width: float | None = Field(ge=1e-6, le=1_000_000)

    def _validate_parameters(self) -> None:
        required = _KIND_PARAMETERS[self.kind]
        missing = sorted(name for name in required if getattr(self, name) is None)
        unexpected = sorted(
            name
            for name in _SHAPE_PARAMETER_FIELDS
            if name not in required and getattr(self, name) is not None
        )
        if missing:
            raise ValueError(
                f"shape kind {self.kind!r} has null required parameters: {', '.join(missing)}"
            )
        if unexpected:
            raise ValueError(
                f"shape kind {self.kind!r} has non-null inapplicable parameters: "
                f"{', '.join(unexpected)}"
            )

    def _nop_library_call(self) -> LibraryCall:
        radius = self.radius
        height = self.height
        center = self.center
        if self.kind == "nop_rounded_rectangle":
            size = _required(self.size, field="size", kind=self.kind)
            radius = _required(radius, field="radius", kind=self.kind)
            center = _required(center, field="center", kind=self.kind)
            if min(size.x, size.y) <= 2 * radius or size.z <= 0:
                raise ValueError(
                    "nop_rounded_rectangle size must be positive and XY dimensions must "
                    "exceed twice radius"
                )
            return LibraryCall(
                source_path="utils/core/rounded_rectangle.scad",
                module="rounded_rectangle",
                named_arguments=(
                    _vector_argument("size", size),
                    _number_argument("r", radius),
                    _boolean_argument("center", center),
                    _boolean_argument("xy_center", center),
                ),
            )
        if self.kind == "nop_rounded_cylinder":
            radius = _required(radius, field="radius", kind=self.kind)
            height = _required(height, field="height", kind=self.kind)
            edge_radius = _required(self.edge_radius, field="edge_radius", kind=self.kind)
            if edge_radius > min(radius, height):
                raise ValueError("nop_rounded_cylinder edge_radius cannot exceed radius or height")
            return LibraryCall(
                source_path="utils/rounded_cylinder.scad",
                module="rounded_cylinder",
                named_arguments=(
                    _number_argument("r", radius),
                    _number_argument("h", height),
                    _number_argument("r2", edge_radius),
                ),
            )
        radius = _required(radius, field="radius", kind=self.kind)
        height = _required(height, field="height", kind=self.kind)
        center = _required(center, field="center", kind=self.kind)
        common = (
            _number_argument("h", height),
            _number_argument("r", radius),
            _boolean_argument("center", center),
        )
        if self.kind == "nop_poly_cylinder":
            return LibraryCall(
                source_path="utils/core/polyholes.scad",
                module="poly_cylinder",
                named_arguments=(
                    _number_argument("r", radius),
                    _number_argument("h", height),
                    _boolean_argument("center", center),
                ),
            )
        if self.kind == "nop_teardrop":
            return LibraryCall(
                source_path="utils/core/teardrops.scad",
                module="teardrop",
                named_arguments=common,
            )
        if self.kind == "nop_teardrop_plus":
            return LibraryCall(
                source_path="utils/core/teardrops.scad",
                module="teardrop_plus",
                named_arguments=common,
            )
        if self.kind == "nop_tearslot":
            slot_width = _required(self.slot_width, field="slot_width", kind=self.kind)
            return LibraryCall(
                source_path="utils/core/teardrops.scad",
                module="tearslot",
                named_arguments=(*common, _number_argument("w", slot_width)),
            )
        raise ValueError(f"unsupported NopSCADlib planner shape kind {self.kind!r}")

    def to_domain(
        self,
    ) -> Box | RoundedBox | Cylinder | Cone | Sphere | Torus | ExtrudedPolygon | LibraryCall:
        self._validate_parameters()
        if self.kind == "box":
            return Box(
                size=_required(self.size, field="size", kind=self.kind).to_domain(),
                center=_required(self.center, field="center", kind=self.kind),
            )
        if self.kind == "rounded_box":
            return RoundedBox(
                size=_required(self.size, field="size", kind=self.kind).to_domain(),
                radius=_required(self.radius, field="radius", kind=self.kind),
                center=_required(self.center, field="center", kind=self.kind),
                facets=_required(self.facets, field="facets", kind=self.kind),
            )
        if self.kind == "cylinder":
            return Cylinder(
                radius=_required(self.radius, field="radius", kind=self.kind),
                height=_required(self.height, field="height", kind=self.kind),
                center=_required(self.center, field="center", kind=self.kind),
                facets=_required(self.facets, field="facets", kind=self.kind),
            )
        if self.kind == "cone":
            return Cone(
                radius_bottom=_required(self.radius_bottom, field="radius_bottom", kind=self.kind),
                radius_top=_required(self.radius_top, field="radius_top", kind=self.kind),
                height=_required(self.height, field="height", kind=self.kind),
                center=_required(self.center, field="center", kind=self.kind),
                facets=_required(self.facets, field="facets", kind=self.kind),
            )
        if self.kind == "sphere":
            return Sphere(
                radius=_required(self.radius, field="radius", kind=self.kind),
                facets=_required(self.facets, field="facets", kind=self.kind),
            )
        if self.kind == "torus":
            return Torus(
                major_radius=_required(self.major_radius, field="major_radius", kind=self.kind),
                minor_radius=_required(self.minor_radius, field="minor_radius", kind=self.kind),
                major_facets=_required(self.major_facets, field="major_facets", kind=self.kind),
                minor_facets=_required(self.minor_facets, field="minor_facets", kind=self.kind),
            )
        if self.kind == "extruded_polygon":
            points = _required(self.points, field="points", kind=self.kind)
            return ExtrudedPolygon(
                points=tuple(point.to_domain() for point in points),
                height=_required(self.height, field="height", kind=self.kind),
                center=_required(self.center, field="center", kind=self.kind),
                twist_degrees=_required(self.twist_degrees, field="twist_degrees", kind=self.kind),
                slices=_required(self.slices, field="slices", kind=self.kind),
                convexity=_required(self.convexity, field="convexity", kind=self.kind),
            )
        return self._nop_library_call()


class PlannerPositiveSolid(PlannerModel):
    id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")]
    name: str = Field(min_length=1, max_length=120)
    shape: PlannerShape
    transform: PlannerTransform
    purpose: str = Field(min_length=1, max_length=500)

    def to_domain(self) -> PositiveSolid:
        return PositiveSolid(
            id=self.id,
            name=self.name,
            shape=self.shape.to_domain(),
            transform=self.transform.to_domain(),
            purpose=self.purpose,
        )


class PlannerNegativeFeature(PlannerModel):
    id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")]
    name: str = Field(min_length=1, max_length=120)
    shape: PlannerShape
    transform: PlannerTransform
    intent: Literal["through_hole", "blind_hole", "pocket", "clearance", "relief", "other"]
    rationale: str = Field(min_length=1, max_length=1000)

    def to_domain(self) -> NegativeFeature:
        return NegativeFeature(
            id=self.id,
            name=self.name,
            shape=self.shape.to_domain(),
            transform=self.transform.to_domain(),
            intent=NegativeIntent(self.intent),
            rationale=self.rationale,
        )


class PlannerToolAccessChannel(PlannerModel):
    id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")]
    name: str = Field(min_length=1, max_length=120)
    start: PlannerVec3
    end: PlannerVec3
    tool_diameter: float = Field(ge=1e-6, le=100_000)
    radial_clearance: float = Field(ge=0, le=10_000)
    endpoint_overtravel: float = Field(ge=0, le=10_000)
    tool: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=1000)
    facets: int = Field(ge=12, le=1024)

    def to_domain(self) -> ToolAccessChannel:
        return ToolAccessChannel(
            id=self.id,
            name=self.name,
            start=self.start.to_domain(),
            end=self.end.to_domain(),
            tool_diameter=self.tool_diameter,
            radial_clearance=self.radial_clearance,
            endpoint_overtravel=self.endpoint_overtravel,
            tool=self.tool,
            rationale=self.rationale,
            facets=self.facets,
        )


class PlannerPrintProfile(PlannerModel):
    process: Literal["fdm", "sla", "sls", "unknown"]
    material: str = Field(min_length=1, max_length=64)
    nozzle_diameter: float = Field(gt=0, le=10)
    layer_height: float = Field(gt=0, le=10)
    minimum_wall: float = Field(gt=0, le=100)
    minimum_clearance: float = Field(ge=0, le=100)
    maximum_unsupported_overhang_degrees: float = Field(ge=0, le=90)
    build_volume: PlannerVec3

    def to_domain(self) -> PrintProfile:
        return PrintProfile(
            process=self.process,
            material=self.material,
            nozzle_diameter=self.nozzle_diameter,
            layer_height=self.layer_height,
            minimum_wall=self.minimum_wall,
            minimum_clearance=self.minimum_clearance,
            maximum_unsupported_overhang_degrees=self.maximum_unsupported_overhang_degrees,
            build_volume=self.build_volume.to_domain(),
        )


class PlannerDesignSpec(PlannerModel):
    schema_version: Literal["1.0"]
    name: str = Field(min_length=1, max_length=120)
    intent: str = Field(min_length=1, max_length=2000)
    units: Literal["mm"]
    positive_solids: list[PlannerPositiveSolid] = Field(min_length=1, max_length=128)
    negative_features: list[PlannerNegativeFeature] = Field(max_length=128)
    tool_access_channels: list[PlannerToolAccessChannel] = Field(max_length=128)
    print_profile: PlannerPrintProfile
    assumptions: list[str] = Field(max_length=64)
    notes: list[str] = Field(max_length=64)

    def to_domain(self) -> DesignSpec:
        return DesignSpec(
            schema_version=self.schema_version,
            name=self.name,
            intent=self.intent,
            units=self.units,
            positive_solids=tuple(solid.to_domain() for solid in self.positive_solids),
            negative_features=tuple(feature.to_domain() for feature in self.negative_features),
            tool_access_channels=tuple(
                channel.to_domain() for channel in self.tool_access_channels
            ),
            print_profile=self.print_profile.to_domain(),
            assumptions=tuple(self.assumptions),
            notes=tuple(self.notes),
        )


class PlannerOutput(PlannerModel):
    """The only Pydantic type passed to ``responses.parse``."""

    spec: PlannerDesignSpec
    rationale: str = Field(min_length=1, max_length=4000)
    unresolved_questions: list[str] = Field(max_length=32)

    def to_domain(self) -> PlannedDesign:
        return PlannedDesign(
            spec=self.spec.to_domain(),
            rationale=self.rationale,
            unresolved_questions=list(self.unresolved_questions),
        )
