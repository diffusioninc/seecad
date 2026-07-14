"""Semantic assembly inventory and bounded tool-access linting."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from seecad.models import (
    ComponentKind,
    Confidence,
    SafeIdentifier,
    Severity,
    StrictModel,
    Vec3,
)

ACCESS_TOLERANCE_MM = 1e-6


class AssemblyEnvelope(StrictModel):
    """A conservative axis-aligned part envelope in assembly coordinates."""

    minimum: Vec3
    maximum: Vec3

    @model_validator(mode="after")
    def positive_extents(self) -> AssemblyEnvelope:
        if any(
            high - low < ACCESS_TOLERANCE_MM
            for low, high in zip(self.minimum.values(), self.maximum.values(), strict=True)
        ):
            raise ValueError("assembly envelope maximums must exceed minimums in every axis")
        return self


class FastenerDefinition(StrictModel):
    """Declared identity and drive interface for one physical fastener."""

    designation: str = Field(min_length=1, max_length=120)
    drive: str = Field(min_length=1, max_length=120)
    confidence: Confidence
    basis: str = Field(min_length=1, max_length=1000)

    @field_validator("confidence", mode="before")
    @classmethod
    def parse_confidence(cls, value: object) -> object:
        return Confidence(value) if isinstance(value, str) else value


class AssemblyPart(StrictModel):
    """One physical instance; repeated hardware receives repeated records."""

    id: SafeIdentifier
    name: str = Field(min_length=1, max_length=120)
    kind: ComponentKind
    purpose: str = Field(min_length=1, max_length=500)
    envelope: AssemblyEnvelope
    part_number: str | None = Field(default=None, min_length=1, max_length=120)
    source_file: str | None = Field(
        default=None,
        min_length=1,
        max_length=240,
        pattern=r"^[A-Za-z0-9_.+ -]+$",
    )
    fastener: FastenerDefinition | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def parse_kind(cls, value: object) -> object:
        return ComponentKind(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def fastener_metadata_matches_kind(self) -> AssemblyPart:
        if self.kind == ComponentKind.FASTENER and self.fastener is None:
            raise ValueError("fastener parts require fastener metadata")
        if self.kind != ComponentKind.FASTENER and self.fastener is not None:
            raise ValueError("only fastener parts may declare fastener metadata")
        return self


class ToolAccessCone(StrictModel):
    """A finite driver envelope extending out from a fastener drive interface."""

    id: SafeIdentifier
    name: str = Field(min_length=1, max_length=120)
    fastener_id: SafeIdentifier
    tip: Vec3
    axis: Vec3
    reach_mm: float = Field(ge=ACCESS_TOLERANCE_MM, le=1_000_000)
    tool_diameter_mm: float = Field(ge=ACCESS_TOLERANCE_MM, le=100_000)
    clearance_mm: float = Field(default=0.5, ge=0, le=10_000)
    approach_half_angle_degrees: float = Field(default=0, ge=0, le=45)
    tool: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def nonzero_axis(self) -> ToolAccessCone:
        if sum(value * value for value in self.axis.values()) <= 1e-12:
            raise ValueError("tool access cone axis must be non-zero")
        return self


class AssemblyLintSpec(StrictModel):
    """Semantic authority for checking an existing or externally sourced assembly."""

    schema_version: Literal["1.0"] = "1.0"
    name: str = Field(min_length=1, max_length=120)
    intent: str = Field(min_length=1, max_length=2000)
    units: Literal["mm"]
    source_url: str | None = Field(default=None, min_length=1, max_length=2000)
    source_license: str | None = Field(default=None, min_length=1, max_length=120)
    parts: tuple[AssemblyPart, ...] = Field(min_length=1, max_length=2048)
    tool_access_cones: tuple[ToolAccessCone, ...] = Field(default_factory=tuple, max_length=2048)
    assumptions: tuple[str, ...] = Field(default_factory=tuple, max_length=128)

    @field_validator("parts", "tool_access_cones", "assumptions", mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_semantic_ids(self) -> AssemblyLintSpec:
        part_ids = [part.id for part in self.parts]
        if len(part_ids) != len(set(part_ids)):
            raise ValueError("assembly part ids must be unique")
        cone_ids = [cone.id for cone in self.tool_access_cones]
        if len(cone_ids) != len(set(cone_ids)):
            raise ValueError("tool access cone ids must be unique")
        return self


class PartFamily(StrictModel):
    key: str
    instance_ids: tuple[SafeIdentifier, ...]
    count: int = Field(ge=1)


class ToolConeInspection(StrictModel):
    cone_id: SafeIdentifier
    name: str
    fastener_id: SafeIdentifier
    tool: str
    tip: Vec3
    axis: Vec3
    reach_mm: float
    tool_diameter_mm: float
    clearance_mm: float
    approach_half_angle_degrees: float
    rationale: str
    status: Literal["clear", "blocked", "invalid"]
    confidence: Confidence
    blocker_part_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple)
    basis: str


class FastenerInspection(StrictModel):
    part_id: SafeIdentifier
    name: str
    designation: str
    drive: str
    identity_confidence: Confidence
    identity_basis: str
    tool_cone_ids: tuple[SafeIdentifier, ...] = Field(default_factory=tuple)
    accessibility: Literal["clear", "blocked", "unchecked"]


class AssemblyLintDiagnostic(StrictModel):
    code: str
    severity: Severity
    confidence: Confidence
    message: str
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class AssemblyLintSummary(StrictModel):
    status: Literal["pass", "fail"]
    part_count: int = Field(ge=0)
    part_family_count: int = Field(ge=0)
    fastener_count: int = Field(ge=0)
    tool_cone_count: int = Field(ge=0)
    accessible_fastener_count: int = Field(ge=0)
    blocked_fastener_count: int = Field(ge=0)
    unchecked_fastener_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class AssemblyLintReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    assembly_name: str
    units: Literal["mm"] = "mm"
    source_url: str | None = None
    source_license: str | None = None
    assumptions: tuple[str, ...]
    summary: AssemblyLintSummary
    parts: tuple[AssemblyPart, ...]
    part_families: tuple[PartFamily, ...]
    fasteners: tuple[FastenerInspection, ...]
    tool_access_cones: tuple[ToolConeInspection, ...]
    diagnostics: tuple[AssemblyLintDiagnostic, ...]
    limitations: tuple[str, ...]


def _normalize(vector: Vec3) -> tuple[float, float, float]:
    magnitude = math.sqrt(sum(value * value for value in vector.values()))
    return tuple(value / magnitude for value in vector.values())  # type: ignore[return-value]


def _corners(envelope: AssemblyEnvelope) -> Iterable[tuple[float, float, float]]:
    low = envelope.minimum.values()
    high = envelope.maximum.values()
    for x in (low[0], high[0]):
        for y in (low[1], high[1]):
            for z in (low[2], high[2]):
                yield x, y, z


def _segment_intersects_aabb(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
) -> bool:
    """Return whether a finite segment intersects an axis-aligned box."""

    interval_min = 0.0
    interval_max = 1.0
    for origin, destination, low, high in zip(start, end, minimum, maximum, strict=True):
        delta = destination - origin
        if abs(delta) <= ACCESS_TOLERANCE_MM:
            if origin < low or origin > high:
                return False
            continue
        near = (low - origin) / delta
        far = (high - origin) / delta
        if near > far:
            near, far = far, near
        interval_min = max(interval_min, near)
        interval_max = min(interval_max, far)
        if interval_min > interval_max:
            return False
    return True


def _cone_may_intersect_part(cone: ToolAccessCone, part: AssemblyPart) -> bool:
    """Conservatively test a cone against one semantic AABB proxy."""

    axis = _normalize(cone.axis)
    tip = cone.tip.values()
    projections = [
        sum((point[index] - tip[index]) * axis[index] for index in range(3))
        for point in _corners(part.envelope)
    ]
    overlap_start = max(ACCESS_TOLERANCE_MM, min(projections))
    overlap_end = min(cone.reach_mm, max(projections))
    if overlap_end - overlap_start <= ACCESS_TOLERANCE_MM:
        return False

    slope = math.tan(math.radians(cone.approach_half_angle_degrees))
    maximum_radius = cone.tool_diameter_mm / 2 + cone.clearance_mm + slope * overlap_end
    segment_start = (
        tip[0] + axis[0] * overlap_start,
        tip[1] + axis[1] * overlap_start,
        tip[2] + axis[2] * overlap_start,
    )
    segment_end = (
        tip[0] + axis[0] * overlap_end,
        tip[1] + axis[1] * overlap_end,
        tip[2] + axis[2] * overlap_end,
    )
    part_minimum = part.envelope.minimum.values()
    part_maximum = part.envelope.maximum.values()
    minimum = (
        part_minimum[0] - maximum_radius,
        part_minimum[1] - maximum_radius,
        part_minimum[2] - maximum_radius,
    )
    maximum = (
        part_maximum[0] + maximum_radius,
        part_maximum[1] + maximum_radius,
        part_maximum[2] + maximum_radius,
    )
    return _segment_intersects_aabb(segment_start, segment_end, minimum, maximum)


def _part_families(parts: tuple[AssemblyPart, ...]) -> tuple[PartFamily, ...]:
    families: dict[str, list[str]] = {}
    for part in parts:
        key = part.part_number or part.source_file or part.name
        families.setdefault(key, []).append(part.id)
    return tuple(
        PartFamily(key=key, instance_ids=tuple(instance_ids), count=len(instance_ids))
        for key, instance_ids in families.items()
    )


def _cone_inspection(
    cone: ToolAccessCone,
    *,
    status: Literal["clear", "blocked", "invalid"],
    confidence: Confidence,
    basis: str,
    blocker_part_ids: tuple[str, ...] = (),
) -> ToolConeInspection:
    return ToolConeInspection(
        cone_id=cone.id,
        name=cone.name,
        fastener_id=cone.fastener_id,
        tool=cone.tool,
        tip=cone.tip,
        axis=cone.axis,
        reach_mm=cone.reach_mm,
        tool_diameter_mm=cone.tool_diameter_mm,
        clearance_mm=cone.clearance_mm,
        approach_half_angle_degrees=cone.approach_half_angle_degrees,
        rationale=cone.rationale,
        status=status,
        confidence=confidence,
        blocker_part_ids=blocker_part_ids,
        basis=basis,
    )


def lint_assembly(spec: AssemblyLintSpec) -> AssemblyLintReport:
    """Enumerate an assembly and check declared fastener tool cones."""

    parts_by_id = {part.id: part for part in spec.parts}
    fastener_parts = tuple(part for part in spec.parts if part.kind == ComponentKind.FASTENER)
    cones_by_fastener: dict[str, list[ToolConeInspection]] = {
        part.id: [] for part in fastener_parts
    }
    diagnostics: list[AssemblyLintDiagnostic] = []
    cone_inspections: list[ToolConeInspection] = []

    for cone in spec.tool_access_cones:
        target = parts_by_id.get(cone.fastener_id)
        if target is None:
            inspection = _cone_inspection(
                cone,
                status="invalid",
                confidence=Confidence.EXACT,
                basis="The cone references an undeclared part id.",
            )
            diagnostics.append(
                AssemblyLintDiagnostic(
                    code="tool_cone_unknown_fastener",
                    severity=Severity.ERROR,
                    confidence=Confidence.EXACT,
                    message=(
                        f"Tool cone {cone.id!r} references unknown fastener {cone.fastener_id!r}."
                    ),
                    evidence={"tool_cone_id": cone.id, "fastener_id": cone.fastener_id},
                )
            )
        elif target.kind != ComponentKind.FASTENER:
            inspection = _cone_inspection(
                cone,
                status="invalid",
                confidence=Confidence.EXACT,
                basis="The referenced part is not declared as a fastener.",
            )
            diagnostics.append(
                AssemblyLintDiagnostic(
                    code="tool_cone_target_not_fastener",
                    severity=Severity.ERROR,
                    confidence=Confidence.EXACT,
                    message=(
                        f"Tool cone {cone.id!r} targets part {target.id!r}, "
                        "which is not a fastener."
                    ),
                    evidence={"tool_cone_id": cone.id, "part_id": target.id},
                )
            )
        else:
            blockers = tuple(
                part.id
                for part in spec.parts
                if part.id != target.id and _cone_may_intersect_part(cone, part)
            )
            inspection = _cone_inspection(
                cone,
                status="blocked" if blockers else "clear",
                confidence=Confidence.BOUNDED,
                basis=(
                    "Conservative finite-cone test against declared axis-aligned part "
                    "envelopes; a possible obstruction requires detailed geometry review."
                ),
                blocker_part_ids=blockers,
            )
            cones_by_fastener[target.id].append(inspection)
            if blockers:
                diagnostics.append(
                    AssemblyLintDiagnostic(
                        code="tool_cone_possible_obstruction",
                        severity=Severity.WARNING,
                        confidence=Confidence.BOUNDED,
                        message=(
                            f"Tool cone {cone.id!r} may be obstructed by {', '.join(blockers)}."
                        ),
                        evidence={
                            "tool_cone_id": cone.id,
                            "fastener_id": target.id,
                            "blocker_part_ids": list(blockers),
                        },
                    )
                )
        cone_inspections.append(inspection)

    fastener_inspections: list[FastenerInspection] = []
    for part in fastener_parts:
        assert part.fastener is not None
        cone_results = cones_by_fastener[part.id]
        if not cone_results:
            accessibility: Literal["clear", "blocked", "unchecked"] = "unchecked"
            diagnostics.append(
                AssemblyLintDiagnostic(
                    code="fastener_missing_tool_cone",
                    severity=Severity.ERROR,
                    confidence=Confidence.EXACT,
                    message=f"Fastener {part.id!r} has no valid tool access cone.",
                    evidence={"fastener_id": part.id},
                )
            )
        elif any(result.status == "clear" for result in cone_results):
            accessibility = "clear"
        else:
            accessibility = "blocked"
            diagnostics.append(
                AssemblyLintDiagnostic(
                    code="fastener_not_tool_accessible",
                    severity=Severity.ERROR,
                    confidence=Confidence.BOUNDED,
                    message=(
                        f"Every declared tool approach for fastener {part.id!r} has a "
                        "possible obstruction."
                    ),
                    evidence={
                        "fastener_id": part.id,
                        "tool_cone_ids": [result.cone_id for result in cone_results],
                    },
                )
            )
        fastener_inspections.append(
            FastenerInspection(
                part_id=part.id,
                name=part.name,
                designation=part.fastener.designation,
                drive=part.fastener.drive,
                identity_confidence=part.fastener.confidence,
                identity_basis=part.fastener.basis,
                tool_cone_ids=tuple(result.cone_id for result in cone_results),
                accessibility=accessibility,
            )
        )

    error_count = sum(item.severity == Severity.ERROR for item in diagnostics)
    warning_count = sum(item.severity == Severity.WARNING for item in diagnostics)
    families = _part_families(spec.parts)
    accessible_count = sum(item.accessibility == "clear" for item in fastener_inspections)
    blocked_count = sum(item.accessibility == "blocked" for item in fastener_inspections)
    unchecked_count = sum(item.accessibility == "unchecked" for item in fastener_inspections)
    return AssemblyLintReport(
        assembly_name=spec.name,
        source_url=spec.source_url,
        source_license=spec.source_license,
        assumptions=spec.assumptions,
        summary=AssemblyLintSummary(
            status="fail" if error_count else "pass",
            part_count=len(spec.parts),
            part_family_count=len(families),
            fastener_count=len(fastener_parts),
            tool_cone_count=len(spec.tool_access_cones),
            accessible_fastener_count=accessible_count,
            blocked_fastener_count=blocked_count,
            unchecked_fastener_count=unchecked_count,
            error_count=error_count,
            warning_count=warning_count,
        ),
        parts=spec.parts,
        part_families=families,
        fasteners=tuple(fastener_inspections),
        tool_access_cones=tuple(cone_inspections),
        diagnostics=tuple(diagnostics),
        limitations=(
            "Part enumeration and declared relationships are exact with respect to the "
            "manifest, not the source CAD files.",
            "Tool accessibility is a bounded conservative AABB-envelope check and may "
            "report false obstructions.",
            "No fit, thread engagement, torque, manufacturability, "
            "collision-through-motion, or structural guarantee is made.",
        ),
    )


def render_assembly_lint_text(report: AssemblyLintReport) -> str:
    """Render the complete report without discarding agent-relevant identifiers."""

    lines = [
        f"{report.summary.status.upper()} {report.assembly_name} ({report.units})",
        "",
        f"Parts ({report.summary.part_count} instances):",
    ]
    for part in report.parts:
        identity = part.part_number or part.source_file or "custom"
        lines.append(f"- {part.id} [{part.kind.value}] {part.name} ({identity})")
    lines.extend(["", f"Fasteners ({report.summary.fastener_count}):"])
    for fastener in report.fasteners:
        cone_ids = ", ".join(fastener.tool_cone_ids) or "none"
        lines.append(
            f"- {fastener.part_id}: {fastener.designation}; {fastener.drive}; "
            f"access={fastener.accessibility}; cones={cone_ids}"
        )
    lines.extend(["", f"Tool cones ({report.summary.tool_cone_count}):"])
    for cone in report.tool_access_cones:
        blockers = ", ".join(cone.blocker_part_ids) or "none"
        lines.append(
            f"- {cone.cone_id} -> {cone.fastener_id}: {cone.status} "
            f"({cone.confidence.value}); tool={cone.tool}; reach={cone.reach_mm:g} mm; "
            f"blockers={blockers}"
        )
    lines.extend(["", f"Diagnostics ({len(report.diagnostics)}):"])
    if report.diagnostics:
        for diagnostic in report.diagnostics:
            lines.append(
                f"- {diagnostic.severity.value} {diagnostic.code} "
                f"[{diagnostic.confidence.value}]: {diagnostic.message}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            (
                f"Summary: {report.summary.error_count} errors, "
                f"{report.summary.warning_count} warnings; "
                f"{report.summary.accessible_fastener_count}/"
                f"{report.summary.fastener_count} fasteners have a clear bounded approach."
            ),
        ]
    )
    return "\n".join(lines)
