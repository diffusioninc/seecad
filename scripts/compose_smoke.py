#!/usr/bin/env python3
"""Exercise the production-shaped Compose boundary without an OpenAI credential."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

BASE_URL = os.environ.get("SEECAD_SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 180,
) -> tuple[bytes, str]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {} if payload is None else {"Content-Type": "application/json"}
    req = urllib.request.Request(f"{BASE_URL}{path}", data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read(), response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc


def request_json(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 180,
) -> dict[str, Any]:
    content, media_type = request(method, path, body, timeout=timeout)
    if media_type != "application/json":
        raise RuntimeError(f"{method} {path} returned unexpected media type {media_type}")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise RuntimeError(f"{method} {path} returned a non-object JSON response")
    return result


def wait_until_ready() -> dict[str, Any]:
    deadline = time.monotonic() + 180
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            health = request_json("GET", "/health", timeout=3)
            if (
                health.get("status") == "ok"
                and health.get("openscad_available") is True
                and health.get("storage_writable") is True
            ):
                return health
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"SeeCAD did not become ready: {last_error}")


def artifact_bytes(sha256: str) -> bytes:
    content, _media_type = request("GET", f"/v1/artifacts/{sha256}")
    return content


def number(value: float) -> dict[str, Any]:
    return {"kind": "number", "value": value}


def boolean(value: bool) -> dict[str, Any]:
    return {"kind": "boolean", "value": value}


def vector(*values: float) -> dict[str, Any]:
    return {"kind": "vector", "values": list(values)}


def nop_solid(
    *,
    entity_id: str,
    name: str,
    source_path: str,
    module: str,
    named_arguments: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "id": entity_id,
        "name": name,
        "shape": {
            "kind": "library_call",
            "library": "nopscadlib",
            "source_path": source_path,
            "module": module,
            "named_arguments": [
                {"name": argument_name, "value": value} for argument_name, value in named_arguments
            ],
        },
        "purpose": "Compile-time coverage of an audited NopSCADlib primitive.",
    }


def audited_nop_cases() -> list[
    tuple[dict[str, Any], tuple[tuple[float, float], tuple[float, float], tuple[float, float]]]
]:
    return [
        (
            nop_solid(
                entity_id="nop-rounded-rectangle",
                name="Nop rounded rectangle",
                source_path="utils/core/rounded_rectangle.scad",
                module="rounded_rectangle",
                named_arguments=[
                    ("size", vector(10.0, 8.0, 3.0)),
                    ("r", number(1.0)),
                    ("center", boolean(False)),
                    ("xy_center", boolean(False)),
                ],
            ),
            ((9.9, 10.1), (7.9, 8.1), (2.9, 3.1)),
        ),
        (
            nop_solid(
                entity_id="nop-rounded-cylinder",
                name="Nop rounded cylinder",
                source_path="utils/rounded_cylinder.scad",
                module="rounded_cylinder",
                named_arguments=[
                    ("r", number(5.0)),
                    ("h", number(6.0)),
                    ("r2", number(1.0)),
                ],
            ),
            ((9.8, 10.2), (9.8, 10.2), (5.9, 6.1)),
        ),
        (
            nop_solid(
                entity_id="nop-poly-cylinder",
                name="Nop compensated cylinder",
                source_path="utils/core/polyholes.scad",
                module="poly_cylinder",
                named_arguments=[
                    ("r", number(3.0)),
                    ("h", number(6.0)),
                    ("center", boolean(False)),
                ],
            ),
            ((5.9, 6.5), (5.9, 6.5), (5.9, 6.1)),
        ),
        (
            nop_solid(
                entity_id="nop-teardrop",
                name="Nop teardrop",
                source_path="utils/core/teardrops.scad",
                module="teardrop",
                named_arguments=[
                    ("h", number(6.0)),
                    ("r", number(3.0)),
                    ("center", boolean(True)),
                ],
            ),
            ((5.8, 6.2), (5.8, 6.2), (5.9, 6.1)),
        ),
        (
            nop_solid(
                entity_id="nop-teardrop-plus",
                name="Nop teardrop plus",
                source_path="utils/core/teardrops.scad",
                module="teardrop_plus",
                named_arguments=[
                    ("h", number(6.0)),
                    ("r", number(3.0)),
                    ("center", boolean(True)),
                ],
            ),
            ((5.8, 6.2), (5.8, 6.5), (5.9, 6.1)),
        ),
        (
            nop_solid(
                entity_id="nop-tearslot",
                name="Nop tearslot",
                source_path="utils/core/teardrops.scad",
                module="tearslot",
                named_arguments=[
                    ("h", number(6.0)),
                    ("r", number(3.0)),
                    ("center", boolean(True)),
                    ("w", number(8.0)),
                ],
            ),
            ((13.8, 14.2), (5.8, 6.2), (5.9, 6.1)),
        ),
    ]


def verify_audited_nop_primitives(
    cases: list[
        tuple[
            dict[str, Any],
            tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
        ]
    ],
) -> dict[str, dict[str, Any]]:
    verified: dict[str, dict[str, Any]] = {}
    for solid, expected_ranges in cases:
        entity_id = str(solid["id"])
        component_id = "audited-part"
        created = request_json(
            "POST",
            "/v1/designs",
            {
                "spec": {
                    "schema_version": "1.1",
                    "name": str(solid["name"]),
                    "intent": f"Render only the audited {entity_id} primitive.",
                    "units": "mm",
                    "components": [
                        {
                            "id": component_id,
                            "name": "Audited part",
                            "kind": "part",
                            "purpose": "Single audited NopSCADlib primitive.",
                        }
                    ],
                    "positive_solids": [{**solid, "component_id": component_id}],
                    "negative_features": [],
                    "tool_access_channels": [],
                }
            },
        )
        design_id = str(created["design_id"])
        compiled = request_json(
            "POST",
            f"/v1/designs/{design_id}/revisions/{created['revision_id']}/compile",
            {"format": "stl"},
        )
        stl_ref = compiled["artifacts"]["stl"]
        if len(artifact_bytes(str(stl_ref["sha256"]))) <= 84:
            raise RuntimeError(f"{entity_id} produced no non-empty STL geometry")
        report_ref = compiled["artifacts"]["compile_stl"]
        report = json.loads(artifact_bytes(str(report_ref["sha256"])))
        diagnostics = report.get("diagnostics")
        if not isinstance(diagnostics, str):
            raise RuntimeError(f"{entity_id} compile report has invalid diagnostics")
        lowered_diagnostics = diagnostics.lower()
        forbidden_diagnostics = (
            "unknown module",
            "undefined",
            "can't open include file",
            "can't open library",
            "parser error",
            "syntax error",
            "no top level geometry to render",
        )
        if any(marker in lowered_diagnostics for marker in forbidden_diagnostics):
            raise RuntimeError(f"{entity_id} produced an unresolved OpenSCAD diagnostic")

        analyzed = request_json(
            "POST",
            f"/v1/designs/{design_id}/revisions/{compiled['revision_id']}/analyze",
            {"auto_compile": False},
        )["analysis"]
        measurements = {
            measurement["name"]: measurement["value"] for measurement in analyzed["measurements"]
        }
        triangle_count = measurements.get("triangle_count")
        if not isinstance(triangle_count, int) or triangle_count <= 0:
            raise RuntimeError(f"{entity_id} has no analyzed triangles")
        if measurements.get("watertight") is not True:
            raise RuntimeError(f"{entity_id} is not watertight")
        bounds = measurements.get("bounds_extents")
        if not isinstance(bounds, list) or len(bounds) != 3:
            raise RuntimeError(f"{entity_id} has invalid analyzed bounds")
        numeric_bounds = [float(value) for value in bounds]
        if any(
            not lower <= actual <= upper
            for actual, (lower, upper) in zip(numeric_bounds, expected_ranges, strict=True)
        ):
            raise RuntimeError(
                f"{entity_id} bounds {numeric_bounds!r} fall outside {expected_ranges!r}"
            )
        verified[entity_id] = {
            "stl_sha256": stl_ref["sha256"],
            "triangle_count": triangle_count,
            "bounds_mm": numeric_bounds,
        }
    return verified


def main() -> None:
    health = wait_until_ready()
    created = request_json(
        "POST",
        "/v1/designs",
        {
            "spec": {
                "schema_version": "1.1",
                "name": "Compose boundary smoke",
                "intent": "Exercise positive volume, consolidated subtraction, and tool access.",
                "units": "mm",
                "components": [
                    {
                        "id": "body-component",
                        "name": "Body component",
                        "kind": "part",
                        "purpose": "Single fabricated smoke-test body.",
                    }
                ],
                "positive_solids": [
                    {
                        "id": "body",
                        "name": "Body",
                        "component_id": "body-component",
                        "shape": {"kind": "box", "size": {"x": 20.0, "y": 12.0, "z": 8.0}},
                    }
                ],
                "negative_features": [
                    {
                        "id": "mount-hole",
                        "name": "Mount hole",
                        "shape": {"kind": "cylinder", "radius": 2.0, "height": 12.0},
                        "transform": {"translate": {"x": 10.0, "y": 6.0, "z": -2.0}},
                        "intent": "through_hole",
                        "rationale": "Fastener clearance.",
                        "target_component_ids": ["body-component"],
                    }
                ],
                "tool_access_channels": [
                    {
                        "id": "driver-access",
                        "name": "Driver access",
                        "start": {"x": -3.0, "y": 6.0, "z": 4.0},
                        "end": {"x": 23.0, "y": 6.0, "z": 4.0},
                        "tool_diameter": 3.0,
                        "endpoint_overtravel": 2.0,
                        "tool": "3 mm driver",
                        "rationale": "Keep the approach path independent of later wall edits.",
                        "target_component_ids": ["body-component"],
                    }
                ],
            }
        },
    )
    design_id = str(created["design_id"])
    created_revision = str(created["revision_id"])

    compiled = request_json(
        "POST",
        f"/v1/designs/{design_id}/revisions/{created_revision}/compile",
        {"format": "stl"},
    )
    stl = compiled["artifacts"]["stl"]
    report_ref = compiled["artifacts"]["compile_stl"]
    report = json.loads(artifact_bytes(str(report_ref["sha256"])))
    provenance = report.get("provenance")
    if not isinstance(provenance, dict):
        raise RuntimeError("remote compile report is missing worker provenance")
    if report.get("output_sha256") != stl["sha256"]:
        raise RuntimeError("compile report does not identify the accepted STL")
    for field in (
        "protocol",
        "worker_build_id",
        "openscad_version",
        "nopscad_revision",
        "nopscad_tree_sha256",
        "source_sha256",
    ):
        if not provenance.get(field):
            raise RuntimeError(f"remote compile provenance is missing {field}")

    analyzed_response = request_json(
        "POST",
        f"/v1/designs/{design_id}/revisions/{compiled['revision_id']}/analyze",
        {"auto_compile": False},
    )
    analyzed = analyzed_response["revision"]
    analysis = analyzed_response["analysis"]
    if analysis.get("mesh_sha256") != stl["sha256"]:
        raise RuntimeError("analysis does not identify the accepted STL")
    if not analysis.get("findings"):
        raise RuntimeError("analysis returned no evidence findings")

    approved = request_json(
        "POST",
        f"/v1/designs/{design_id}/revisions/{analyzed['revision_id']}/approve",
        {
            "attestor": "Compose CI",
            "statement": "Verified the immutable mesh and analysis evidence chain.",
        },
    )
    if approved.get("metadata", {}).get("event") != "approved":
        raise RuntimeError("approval attestation was not persisted")

    three_mf = request_json(
        "POST",
        f"/v1/designs/{design_id}/revisions/{compiled['revision_id']}/compile",
        {"format": "3mf"},
    )
    three_mf_ref = three_mf["artifacts"]["3mf"]
    if not artifact_bytes(str(three_mf_ref["sha256"])).startswith(b"PK\x03\x04"):
        raise RuntimeError("3MF artifact is not a ZIP-based 3MF package")

    audited_nop = verify_audited_nop_primitives(audited_nop_cases())

    print(
        json.dumps(
            {
                "status": "ok",
                "version": health.get("version"),
                "design_id": design_id,
                "approved_revision_id": approved["revision_id"],
                "stl_sha256": stl["sha256"],
                "three_mf_sha256": three_mf_ref["sha256"],
                "worker_build_id": provenance["worker_build_id"],
                "audited_nop": audited_nop,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
