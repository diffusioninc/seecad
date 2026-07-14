from __future__ import annotations

import pytest
from pydantic import ValidationError

from seecad.models import (
    AssemblyComponent,
    Box,
    ComponentKind,
    CreateDesignRequest,
    Cylinder,
    DesignSpec,
    ExtrudedPolygon,
    ImageEvidence,
    NegativeFeature,
    NegativeIntent,
    PositiveSolid,
    Transform,
    Vec2,
    Vec3,
)


def test_units_are_explicit_and_collections_are_immutable(simple_spec: DesignSpec) -> None:
    payload = simple_spec.model_dump(mode="json")
    payload.pop("units")
    with pytest.raises(ValidationError):
        DesignSpec.model_validate(payload)
    assert isinstance(simple_spec.positive_solids, tuple)
    with pytest.raises(AttributeError):
        simple_spec.positive_solids.clear()  # type: ignore[attr-defined]


def test_ids_remain_distinct_after_scad_encoding() -> None:
    spec = DesignSpec(
        name="Distinct identifiers",
        intent="Exercise hyphen and underscore identifiers.",
        units="mm",
        components=(
            AssemblyComponent(
                id="body",
                name="Body",
                kind=ComponentKind.PART,
                purpose="One fused test component",
            ),
        ),
        positive_solids=(
            PositiveSolid(
                id="foo-bar",
                name="A",
                component_id="body",
                shape=Box(size=Vec3(x=1, y=1, z=1)),
            ),
            PositiveSolid(
                id="foo_bar",
                name="B",
                component_id="body",
                shape=Box(size=Vec3(x=1, y=1, z=1)),
            ),
        ),
    )
    assert len(spec.positive_solids) == 2


def test_minimum_geometry_prevents_scad_precision_collapse() -> None:
    with pytest.raises(ValidationError):
        Box(size=Vec3(x=1e-13, y=1, z=1))


def test_create_requires_exactly_one_input(simple_spec: DesignSpec) -> None:
    with pytest.raises(ValidationError):
        CreateDesignRequest()
    with pytest.raises(ValidationError):
        CreateDesignRequest(prompt="make it", spec=simple_spec)
    assert CreateDesignRequest(spec=simple_spec).spec == simple_spec


def test_https_image_url_size_stays_within_api_request_budget() -> None:
    with pytest.raises(ValidationError, match="8 KiB"):
        ImageEvidence(url="https://example.com/" + "a" * (8 * 1024))


def test_component_scoped_schema_rejects_unowned_negative_space() -> None:
    with pytest.raises(ValidationError, match="requires component targets"):
        DesignSpec(
            name="Unscoped slot",
            intent="Reject a subtraction with design-wide reach.",
            units="mm",
            components=(
                AssemblyComponent(
                    id="extrusion",
                    name="Extrusion",
                    kind=ComponentKind.STOCK,
                    purpose="T-slot stock member",
                ),
            ),
            positive_solids=(
                PositiveSolid(
                    id="extrusion-solid",
                    name="Extrusion solid",
                    component_id="extrusion",
                    shape=Box(size=Vec3(x=20, y=20, z=100)),
                ),
            ),
            negative_features=(
                NegativeFeature(
                    id="slot",
                    name="T-slot",
                    shape=Box(size=Vec3(x=3, y=8, z=100)),
                    intent=NegativeIntent.CLEARANCE,
                    rationale="Nominal slot envelope.",
                ),
            ),
        )


def test_crossed_gusset_component_envelopes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="component envelopes overlap"):
        DesignSpec(
            name="Crossed gussets",
            intent="Reject paired plates occupying the same corner volume.",
            units="mm",
            components=(
                AssemblyComponent(
                    id="gusset-xz",
                    name="XZ gusset",
                    kind=ComponentKind.PART,
                    purpose="First corner gusset",
                ),
                AssemblyComponent(
                    id="gusset-yz",
                    name="YZ gusset",
                    kind=ComponentKind.PART,
                    purpose="Second corner gusset",
                ),
            ),
            positive_solids=(
                PositiveSolid(
                    id="gusset-xz-solid",
                    name="XZ gusset solid",
                    component_id="gusset-xz",
                    shape=ExtrudedPolygon(
                        points=(Vec2(x=0, y=0), Vec2(x=40, y=0), Vec2(x=0, y=40)),
                        height=4,
                        slices=1,
                    ),
                    transform=Transform(
                        translate=Vec3(x=0, y=4, z=0),
                        rotate_degrees=Vec3(x=90, y=0, z=0),
                    ),
                ),
                PositiveSolid(
                    id="gusset-yz-solid",
                    name="YZ gusset solid",
                    component_id="gusset-yz",
                    shape=ExtrudedPolygon(
                        points=(Vec2(x=0, y=0), Vec2(x=40, y=0), Vec2(x=0, y=40)),
                        height=4,
                        slices=1,
                    ),
                    transform=Transform(
                        translate=Vec3(x=4, y=0, z=0),
                        rotate_degrees=Vec3(x=0, y=-90, z=0),
                    ),
                ),
            ),
        )


def test_fastener_requires_bounded_contact_with_its_declared_support() -> None:
    with pytest.raises(ValidationError, match="does not contact required component"):
        DesignSpec(
            name="Floating screw head",
            intent="Reject unsupported visible hardware.",
            units="mm",
            components=(
                AssemblyComponent(
                    id="bracket",
                    name="Bracket",
                    kind=ComponentKind.PART,
                    purpose="Fastener support surface",
                ),
                AssemblyComponent(
                    id="screw",
                    name="Screw",
                    kind=ComponentKind.FASTENER,
                    purpose="Visible screw head",
                    must_contact=("bracket",),
                ),
            ),
            positive_solids=(
                PositiveSolid(
                    id="bracket-solid",
                    name="Bracket solid",
                    component_id="bracket",
                    shape=Box(size=Vec3(x=20, y=20, z=4)),
                ),
                PositiveSolid(
                    id="screw-head",
                    name="Screw head",
                    component_id="screw",
                    shape=Cylinder(radius=4, height=4),
                    transform=Transform(translate=Vec3(x=40, y=40, z=40)),
                ),
            ),
        )
