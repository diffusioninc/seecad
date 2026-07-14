from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from typing import ClassVar

import pytest
from openai.lib._pydantic import to_strict_json_schema

from seecad.config import Settings
from seecad.errors import PlannerError
from seecad.models import ImageEvidence, LibraryCall
from seecad.planner import OpenAIPlanner
from seecad.planner_schema import PlannerOutput


class FakeResponses:
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed
        self.kwargs: dict[str, object] = {}

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.parsed)


class FakeAPIError(Exception):
    status_code = 400
    code = "invalid_json_schema"
    param = "text.format.schema"
    body: ClassVar[dict[str, str]] = {
        "secret": "sk-do-not-copy",
        "prompt": "private user prompt",
    }


class FailingResponses:
    def parse(self, **_kwargs: object) -> SimpleNamespace:
        raise FakeAPIError("private body and prompt must not escape")


def _vec3(x: float, y: float, z: float) -> dict[str, float]:
    return {"x": x, "y": y, "z": z}


def _transform() -> dict[str, dict[str, float]]:
    return {
        "translate": _vec3(0.0, 0.0, 0.0),
        "rotate_degrees": _vec3(0.0, 0.0, 0.0),
        "scale": _vec3(1.0, 1.0, 1.0),
    }


def _shape(kind: str, **parameters: object) -> dict[str, object]:
    shape: dict[str, object] = {
        "kind": kind,
        "size": None,
        "radius": None,
        "height": None,
        "center": None,
        "facets": None,
        "radius_bottom": None,
        "radius_top": None,
        "major_radius": None,
        "minor_radius": None,
        "major_facets": None,
        "minor_facets": None,
        "points": None,
        "twist_degrees": None,
        "slices": None,
        "convexity": None,
        "edge_radius": None,
        "slot_width": None,
    }
    shape.update(parameters)
    return shape


def _planner_payload(*, shape: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "spec": {
            "schema_version": "1.1",
            "name": "Fixture bracket",
            "intent": "A conservative mounting fixture.",
            "units": "mm",
            "components": [
                {
                    "id": "fixture",
                    "name": "Fixture",
                    "kind": "part",
                    "purpose": "Single fabricated fixture component.",
                    "must_contact": [],
                }
            ],
            "positive_solids": [
                {
                    "id": "main-body",
                    "name": "Main body",
                    "component_id": "fixture",
                    "shape": shape
                    or _shape(
                        "box",
                        size=_vec3(20.0, 12.0, 8.0),
                        center=False,
                    ),
                    "transform": _transform(),
                    "purpose": "Primary positive volume.",
                }
            ],
            "negative_features": [
                {
                    "id": "mount-hole",
                    "name": "Mount hole",
                    "shape": _shape(
                        "nop_poly_cylinder",
                        radius=2.0,
                        height=12.0,
                        center=True,
                    ),
                    "transform": {
                        **_transform(),
                        "translate": _vec3(10.0, 6.0, 4.0),
                    },
                    "intent": "through_hole",
                    "rationale": "Printer-compensated fastener clearance.",
                    "target_component_ids": ["fixture"],
                }
            ],
            "tool_access_channels": [
                {
                    "id": "driver-access",
                    "name": "Driver access",
                    "start": _vec3(-3.0, 6.0, 4.0),
                    "end": _vec3(23.0, 6.0, 4.0),
                    "tool_diameter": 3.0,
                    "radial_clearance": 0.5,
                    "endpoint_overtravel": 2.0,
                    "tool": "3 mm driver",
                    "rationale": "Preserve reach through future wall edits.",
                    "target_component_ids": ["fixture"],
                    "facets": 64,
                }
            ],
            "print_profile": {
                "process": "fdm",
                "material": "PLA",
                "nozzle_diameter": 0.4,
                "layer_height": 0.2,
                "minimum_wall": 0.8,
                "minimum_clearance": 0.2,
                "maximum_unsupported_overhang_degrees": 45.0,
                "build_volume": _vec3(220.0, 220.0, 250.0),
            },
            "assumptions": ["Dimensions are nominal."],
            "notes": ["Validate fit with a physical coupon."],
        },
        "rationale": "Conservative fixture with a printer-aware hole.",
        "unresolved_questions": ["Confirm fastener tolerance."],
    }


def test_model_facing_schema_contains_no_one_of() -> None:
    schema = to_strict_json_schema(PlannerOutput)
    encoded = json.dumps(schema, sort_keys=True)
    assert '"oneOf"' not in encoded
    assert "library_call" not in encoded
    assert "nop_poly_cylinder" in encoded

    shape_schema = schema["$defs"]["PlannerShape"]
    assert set(shape_schema["properties"]) <= set(shape_schema["required"])


def test_planner_uses_flat_responses_output_and_converts_to_domain(tmp_path: object) -> None:
    parsed = PlannerOutput.model_validate(_planner_payload())
    responses = FakeResponses(parsed)
    client = SimpleNamespace(responses=responses)
    settings = Settings(data_dir=".seecad-test", openai_model="gpt-5.6")
    planner = OpenAIPlanner(settings, client=client)

    result = planner.plan(
        "Make a bracket",
        images=[ImageEvidence(url="https://example.com/reference.png", detail="original")],
    )

    assert result.spec.name == "Fixture bracket"
    nop_shape = result.spec.negative_features[0].shape
    assert isinstance(nop_shape, LibraryCall)
    assert nop_shape.source_path == "utils/core/polyholes.scad"
    assert nop_shape.module == "poly_cylinder"
    assert responses.kwargs["model"] == "gpt-5.6"
    assert responses.kwargs["reasoning"] == {"mode": "pro", "effort": "max"}
    assert responses.kwargs["text_format"] is PlannerOutput
    content = responses.kwargs["input"]
    assert content[0]["content"][1]["detail"] == "original"  # type: ignore[index]


@pytest.mark.parametrize(
    ("planner_shape", "domain_kind"),
    [
        (_shape("box", size=_vec3(10.0, 8.0, 6.0), center=False), "box"),
        (
            _shape(
                "rounded_box",
                size=_vec3(10.0, 8.0, 6.0),
                radius=1.0,
                center=False,
                facets=48,
            ),
            "rounded_box",
        ),
        (
            _shape("cylinder", radius=2.0, height=6.0, center=False, facets=64),
            "cylinder",
        ),
        (
            _shape(
                "cone",
                radius_bottom=3.0,
                radius_top=1.0,
                height=6.0,
                center=False,
                facets=64,
            ),
            "cone",
        ),
        (_shape("sphere", radius=3.0, facets=64), "sphere"),
        (
            _shape(
                "torus",
                major_radius=5.0,
                minor_radius=1.0,
                major_facets=96,
                minor_facets=48,
            ),
            "torus",
        ),
        (
            _shape(
                "extruded_polygon",
                points=[
                    {"x": 0.0, "y": 0.0},
                    {"x": 5.0, "y": 0.0},
                    {"x": 0.0, "y": 5.0},
                ],
                height=4.0,
                center=False,
                twist_degrees=0.0,
                slices=32,
                convexity=10,
            ),
            "extruded_polygon",
        ),
        (
            _shape(
                "nop_rounded_rectangle",
                size=_vec3(10.0, 8.0, 6.0),
                radius=1.0,
                center=False,
            ),
            "rounded_rectangle",
        ),
        (
            _shape(
                "nop_rounded_cylinder",
                radius=5.0,
                height=8.0,
                edge_radius=1.0,
            ),
            "rounded_cylinder",
        ),
        (
            _shape("nop_poly_cylinder", radius=2.0, height=6.0, center=False),
            "poly_cylinder",
        ),
        (
            _shape("nop_teardrop", radius=2.0, height=6.0, center=True),
            "teardrop",
        ),
        (
            _shape("nop_teardrop_plus", radius=2.0, height=6.0, center=True),
            "teardrop_plus",
        ),
        (
            _shape(
                "nop_tearslot",
                radius=2.0,
                height=6.0,
                center=True,
                slot_width=8.0,
            ),
            "tearslot",
        ),
    ],
)
def test_all_planner_shape_kinds_convert_deterministically(
    planner_shape: dict[str, object], domain_kind: str
) -> None:
    output = PlannerOutput.model_validate(_planner_payload(shape=planner_shape)).to_domain()
    shape = output.spec.positive_solids[0].shape
    actual_kind = shape.module if isinstance(shape, LibraryCall) else shape.kind
    assert actual_kind == domain_kind


@pytest.mark.parametrize(
    "malformed_shape",
    [
        _shape("box", size=None, center=False),
        _shape("box", size=_vec3(20.0, 12.0, 8.0), center=False, radius=2.0),
        _shape(
            "rounded_box",
            size=_vec3(4.0, 4.0, 4.0),
            radius=3.0,
            center=False,
            facets=48,
        ),
    ],
)
def test_kind_specific_or_domain_invalid_shapes_fail_safely(
    malformed_shape: dict[str, object],
) -> None:
    payload = _planner_payload(shape=malformed_shape)
    parsed = PlannerOutput.model_validate(deepcopy(payload))
    planner = OpenAIPlanner(
        Settings(data_dir=".seecad-test"),
        client=SimpleNamespace(responses=FakeResponses(parsed)),
    )

    with pytest.raises(PlannerError, match="failed semantic validation") as caught:
        planner.plan("private prompt must not appear in errors")
    assert caught.value.details == {}
    assert "private prompt" not in str(caught.value)


def test_api_error_reports_only_safe_machine_metadata() -> None:
    planner = OpenAIPlanner(
        Settings(data_dir=".seecad-test"),
        client=SimpleNamespace(responses=FailingResponses()),
    )

    with pytest.raises(PlannerError) as caught:
        planner.plan("private user prompt")

    assert caught.value.details == {
        "exception_type": "FakeAPIError",
        "api_status_code": 400,
        "api_code": "invalid_json_schema",
        "api_param": "text.format.schema",
    }
    serialized = json.dumps(caught.value.details)
    assert "sk-do-not-copy" not in serialized
    assert "private user prompt" not in serialized
