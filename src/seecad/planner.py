"""OpenAI Responses planner with a flat, validated Structured Outputs boundary."""

from __future__ import annotations

import re
from typing import Any, cast

from seecad.config import Settings
from seecad.errors import PlannerError, PlannerUnavailableError
from seecad.models import ImageEvidence, PlannedDesign
from seecad.planner_schema import PlannerOutput

PLANNER_INSTRUCTIONS = """You are SeeCAD's senior mechanical design planner.
Translate the user's intent and any image evidence into the supplied semantic schema.

Declare every physical part, stock member, connector, and fastener as an assembly component.
Assign every positive solid to exactly one component. Model material in positive_solids first.
Put every ordinary removal in negative_features and name only the components it is allowed to
cut in target_component_ids. Put screwdriver, probe, cable, key, and service reach passages
in tool_access_channels; make their start/end paths deliberately extend past the faces they
must traverse and target only the components that require the passage. Never alternate
positive and negative edits to represent history. The deterministic renderer scopes each
negative to its named component envelope and performs one final consolidated subtraction.

Distinct assembly components must not interpenetrate. Their conservative transformed bounding
boxes may touch at intended interfaces but must not overlap by positive volume. Use local shape
coordinates plus transforms so component envelopes remain auditable. A connector must declare
at least two must_contact components; a fastener must declare at least one. Place paired gussets
on genuinely disjoint faces or replace them with one intentionally modeled corner connector.
Do not overlap two plates and rely on a valid union. Do not fuse standard hardware into a stock
component merely to bypass component validation.

For a multi-component assembly, use core primitives only. The current audited nop_* planner
surface does not declare conservative placement bounds and is therefore limited to single-
component designs until its bounds contracts are added.

Use millimetres. Prefer simple, auditable primitives. Treat dimensions inferred from an
image as assumptions unless a trustworthy scale reference is visible. Do not claim that
structural integrity, fit, printability, ingress protection, thermal behavior, or safety
has been proven.

For every shape, provide every schema field. Set fields that do not apply to null and set
every field that applies to a concrete non-null value. Applicable fields by kind are:
- box: size, center
- rounded_box: size, radius, center, facets
- cylinder: radius, height, center, facets
- cone: radius_bottom, radius_top, height, center, facets
- sphere: radius, facets
- torus: major_radius, minor_radius, major_facets, minor_facets
- extruded_polygon: points, height, center, twist_degrees, slices, convexity
- nop_rounded_rectangle: size, radius, center
- nop_rounded_cylinder: radius, height, edge_radius
- nop_poly_cylinder, nop_teardrop, nop_teardrop_plus: radius, height, center
- nop_tearslot: radius, height, center, slot_width

The nop_* kinds are the only model-selectable NopSCADlib surface. They map to audited
library calls in code. Never emit library_call, source paths, module names, argument lists,
raw OpenSCAD, include directives, or arbitrary paths. Return a useful conservative design
even when some details are unknown, and record those details in assumptions and
unresolved_questions.
"""


_SAFE_API_DETAIL = re.compile(r"^[A-Za-z0-9_.:/\[\]-]{1,160}$")


def _safe_api_error_details(exc: Exception) -> dict[str, str | int]:
    """Extract diagnostic API metadata without copying messages, bodies, or prompts."""

    details: dict[str, str | int] = {"exception_type": type(exc).__name__}
    status_code = getattr(exc, "status_code", None)
    if (
        isinstance(status_code, int)
        and not isinstance(status_code, bool)
        and 100 <= status_code <= 599
    ):
        details["api_status_code"] = status_code
    for attribute, key in (("code", "api_code"), ("param", "api_param")):
        value = getattr(exc, attribute, None)
        if isinstance(value, str):
            value = value.strip()
            if _SAFE_API_DETAIL.fullmatch(value):
                details[key] = value
    return details


class OpenAIPlanner:
    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client
        if client is None and settings.openai_api_key is not None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                timeout=settings.openai_timeout_seconds,
                # Create is not idempotent yet. Keep the planner timeout inside the
                # frontend/proxy budget and let callers explicitly retry a failed request.
                max_retries=0,
            )

    @property
    def configured(self) -> bool:
        return self._client is not None

    def plan(self, prompt: str, *, images: list[ImageEvidence] | None = None) -> PlannedDesign:
        if self._client is None:
            raise PlannerUnavailableError(
                "OpenAI planning requires OPENAI_API_KEY in the process environment"
            )
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        content.extend(
            {
                "type": "input_image",
                "image_url": image.url,
                "detail": image.detail,
            }
            for image in images or []
        )
        try:
            response = cast(Any, self._client).responses.parse(
                model=self.settings.openai_model,
                instructions=PLANNER_INSTRUCTIONS,
                input=[{"role": "user", "content": content}],
                text_format=PlannerOutput,
                reasoning={
                    "mode": self.settings.openai_reasoning_mode,
                    "effort": self.settings.openai_reasoning_effort,
                },
                max_output_tokens=self.settings.openai_max_output_tokens,
                store=False,
            )
        except Exception as exc:
            raise PlannerError(
                "OpenAI could not produce a design plan",
                details=_safe_api_error_details(exc),
            ) from exc
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise PlannerError("OpenAI returned no usable structured design")
        try:
            output = (
                parsed
                if isinstance(parsed, PlannerOutput)
                else PlannerOutput.model_validate(parsed)
            )
            return output.to_domain()
        except (TypeError, ValueError) as exc:
            raise PlannerError("OpenAI returned a design that failed semantic validation") from exc
