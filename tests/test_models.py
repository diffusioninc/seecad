from __future__ import annotations

import pytest
from pydantic import ValidationError

from seecad.models import Box, CreateDesignRequest, DesignSpec, ImageEvidence, PositiveSolid, Vec3


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
        positive_solids=(
            PositiveSolid(id="foo-bar", name="A", shape=Box(size=Vec3(x=1, y=1, z=1))),
            PositiveSolid(id="foo_bar", name="B", shape=Box(size=Vec3(x=1, y=1, z=1))),
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
