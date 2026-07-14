from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_service import make_service

from seecad.api import API_REQUEST_LIMIT_BYTES, create_app, get_service
from seecad.models import DesignSpec


def test_http_contract_create_get_and_revise(tmp_path: Path, simple_spec: DesignSpec) -> None:
    service, _engine = make_service(tmp_path)
    app = create_app()
    app.dependency_overrides[get_service] = lambda: service
    with TestClient(app) as client:
        response = client.post("/v1/designs", json={"spec": simple_spec.model_dump(mode="json")})
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["spec"]["positive_solids"][0]["id"] == "main-body"
        history = client.get(f"/v1/designs/{created['design_id']}")
        assert history.status_code == 200
        revised = client.post(
            f"/v1/designs/{created['design_id']}/revisions",
            json={
                "parent_revision_id": created["revision_id"],
                "spec": simple_spec.model_dump(mode="json"),
            },
        )
        assert revised.status_code == 201, revised.text
        assert revised.json()["parent_revision_id"] == created["revision_id"]


def test_http_errors_are_stable(tmp_path: Path) -> None:
    service, _engine = make_service(tmp_path)
    app = create_app()
    app.dependency_overrides[get_service] = lambda: service
    with TestClient(app) as client:
        invalid = client.post("/v1/designs", json={})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "request_validation_failed"
        missing = client.get("/v1/designs/dsgn_000000000000000000000000")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"


def test_readiness_fails_when_worker_is_lost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, engine = make_service(tmp_path)
    app = create_app()
    app.dependency_overrides[get_service] = lambda: service
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        monkeypatch.setattr(engine, "is_available", lambda: False)
        health = client.get("/health")
        readiness = client.get("/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["openscad_available"] is False
    assert readiness.status_code == 503
    assert readiness.json()["status"] == "degraded"


def test_chunked_request_body_is_bounded_while_consumed(tmp_path: Path) -> None:
    service, _engine = make_service(tmp_path)
    app = create_app(request_limit_bytes=8)
    app.dependency_overrides[get_service] = lambda: service

    def chunks() -> Iterator[bytes]:
        yield b'{"pro'
        yield b'mpt":"x"}'

    with TestClient(app) as client:
        response = client.post(
            "/v1/designs",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json() == {
        "error": {
            "code": "request_too_large",
            "message": "Request exceeds the 50 MiB API limit.",
            "details": {},
        }
    }


def test_request_limit_has_headroom_for_four_maximum_image_payloads() -> None:
    encoded_eight_mib = ((8 * 1024 * 1024 + 2) // 3) * 4
    data_url_overhead = len("data:image/webp;base64,")
    conservative_json_overhead = 64 * 1024
    required_bytes = 4 * (encoded_eight_mib + data_url_overhead) + conservative_json_overhead
    assert required_bytes < API_REQUEST_LIMIT_BYTES


def test_content_length_request_limit_boundary() -> None:
    app = create_app()
    with TestClient(app) as client:
        at_limit = client.post(
            "/v1/designs",
            content=b"",
            headers={"Content-Length": str(API_REQUEST_LIMIT_BYTES)},
        )
        over_limit = client.post(
            "/v1/designs",
            content=b"",
            headers={"Content-Length": str(API_REQUEST_LIMIT_BYTES + 1)},
        )

    assert at_limit.status_code != 413
    assert over_limit.status_code == 413
    assert over_limit.json()["error"]["code"] == "request_too_large"


def test_http_approval_requires_and_preserves_live_analysis(
    tmp_path: Path, simple_spec: DesignSpec
) -> None:
    service, _engine = make_service(tmp_path)
    app = create_app()
    app.dependency_overrides[get_service] = lambda: service
    with TestClient(app) as client:
        created = client.post(
            "/v1/designs", json={"spec": simple_spec.model_dump(mode="json")}
        ).json()
        compiled = client.post(
            f"/v1/designs/{created['design_id']}/revisions/{created['revision_id']}/compile",
            json={"format": "stl"},
        ).json()
        premature = client.post(
            f"/v1/designs/{created['design_id']}/revisions/{compiled['revision_id']}/approve",
            json={"attestor": "Reviewer", "statement": "Reviewed."},
        )
        assert premature.status_code == 409

        analysis_response = client.post(
            f"/v1/designs/{created['design_id']}/revisions/{compiled['revision_id']}/analyze",
            json={"auto_compile": False},
        )
        assert analysis_response.status_code == 200, analysis_response.text
        analyzed = analysis_response.json()["revision"]
        approved_response = client.post(
            f"/v1/designs/{created['design_id']}/revisions/{analyzed['revision_id']}/approve",
            json={"attestor": "Reviewer", "statement": "Reviewed exact evidence."},
        )
        assert approved_response.status_code == 201, approved_response.text
        approved = approved_response.json()

    assert approved["parent_revision_id"] == analyzed["revision_id"]
    assert approved["metadata"]["event"] == "approved"
    assert set(analyzed["artifacts"]).issubset(approved["artifacts"])
    assert "approval" in approved["artifacts"]
