from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from seecad.config import Settings
from seecad.engine import (
    HEADER_DIAGNOSTICS,
    HEADER_DURATION_MS,
    HEADER_FORMAT,
    HEADER_NOP_REVISION,
    HEADER_NOP_TREE_SHA256,
    HEADER_OPENSCAD_VERSION,
    HEADER_PROTOCOL,
    HEADER_SHA256,
    HEADER_SIZE,
    HEADER_SOURCE_SHA256,
    HEADER_WORKER_BUILD_ID,
    HEADER_WORKER_STATE,
    CompilationProvenance,
    NopSCADProvenance,
    OpenSCADEngine,
)
from seecad.errors import CompilationError, EngineUnavailableError

BUILD_ID = "sha256-" + "c" * 64
_NOP_FILE = b"module fixture() { cube(1); }\n"
_NOP_FILE_HASH = hashlib.sha256(_NOP_FILE).hexdigest()
PROVENANCE = NopSCADProvenance(
    revision="a" * 40,
    tree_sha256=hashlib.sha256(
        f"{_NOP_FILE_HASH}  vendor/NopSCADlib/core.scad\n".encode()
    ).hexdigest(),
)


def _common_headers() -> dict[str, str]:
    return {
        HEADER_PROTOCOL: "1",
        HEADER_WORKER_BUILD_ID: BUILD_ID,
        HEADER_OPENSCAD_VERSION: "OpenSCAD version 2021.01",
        HEADER_NOP_REVISION: PROVENANCE.revision,
        HEADER_NOP_TREE_SHA256: PROVENANCE.tree_sha256,
    }


def _health_response(*, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        204,
        headers=headers or _common_headers(),
        stream=httpx.ByteStream(b""),
    )


def _engine(tmp_path: Path, handler: httpx.MockTransport) -> OpenSCADEngine:
    nop_root = tmp_path / "NopSCADlib"
    nop_root.mkdir()
    (nop_root / "core.scad").write_bytes(_NOP_FILE)
    (tmp_path / "NopSCADlib.UPSTREAM.json").write_text(
        json.dumps(
            {
                "revision": PROVENANCE.revision,
                "tree_sha256": PROVENANCE.tree_sha256,
            }
        )
    )
    engine = OpenSCADEngine(
        Settings(
            openscad_mode="remote",
            openscad_worker_socket=tmp_path / "worker.sock",
            openscad_worker_build_id=BUILD_ID,
            nopscad_root=nop_root,
        )
    )

    def client(*, health: bool) -> httpx.Client:
        del health
        return httpx.Client(transport=handler, base_url="http://worker")

    engine._remote_client = client  # type: ignore[method-assign]
    return engine


def _success_response(request: httpx.Request, artifact: bytes) -> httpx.Response:
    source_sha = hashlib.sha256(request.content).hexdigest()
    return httpx.Response(
        200,
        stream=httpx.ByteStream(artifact),
        headers={
            **_common_headers(),
            HEADER_FORMAT: request.url.params["format"],
            HEADER_SHA256: hashlib.sha256(artifact).hexdigest(),
            HEADER_SIZE: str(len(artifact)),
            HEADER_DURATION_MS: "125",
            HEADER_SOURCE_SHA256: source_sha,
            HEADER_DIAGNOSTICS: base64.b64encode(b"rendered").decode(),
            "Content-Length": str(len(artifact)),
        },
    )


def test_remote_engine_health_compile_and_typed_provenance(tmp_path: Path) -> None:
    artifact = b"solid mesh\nendsolid mesh\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _health_response()
        return _success_response(request, artifact)

    engine = _engine(tmp_path, httpx.MockTransport(handler))
    result = engine.compile("cube([1, 1, 1]);", output_format="stl")
    assert result.content == artifact
    assert result.engine == "remote"
    assert result.diagnostics == "rendered"
    assert result.provenance == CompilationProvenance(
        protocol="1",
        worker_build_id=BUILD_ID,
        openscad_version="OpenSCAD version 2021.01",
        nopscad_revision=PROVENANCE.revision,
        nopscad_tree_sha256=PROVENANCE.tree_sha256,
        source_sha256=hashlib.sha256(b"cube([1, 1, 1]);").hexdigest(),
    )


@pytest.mark.parametrize("tampered_header", [HEADER_SHA256, HEADER_SOURCE_SHA256])
def test_remote_engine_rejects_digest_mismatch(
    tmp_path: Path,
    tampered_header: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _health_response()
        response = _success_response(request, b"mesh")
        response.headers[tampered_header] = "0" * 64
        return response

    engine = _engine(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(EngineUnavailableError, match="protocol validation"):
        engine.compile("cube(1);")


def test_remote_engine_rejects_wrong_worker_identity_at_health(tmp_path: Path) -> None:
    headers = _common_headers()
    headers[HEADER_WORKER_BUILD_ID] = "untrusted-build"
    transport = httpx.MockTransport(lambda _request: _health_response(headers=headers))
    engine = _engine(tmp_path, transport)
    assert not engine.is_available()


def test_remote_health_body_is_streamed_and_bounded(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            204,
            headers=_common_headers(),
            stream=httpx.ByteStream(b"x" * 1025),
        )
    )
    engine = _engine(tmp_path, transport)
    assert not engine.is_available()


def test_remote_engine_maps_busy_without_returning_worker_body(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _health_response()
        return httpx.Response(
            503,
            text="secret worker path /tmp/model.scad",
            headers={**_common_headers(), HEADER_WORKER_STATE: "busy"},
        )

    engine = _engine(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(EngineUnavailableError, match="busy") as caught:
        engine.compile("cube(1);")
    assert caught.value.details == {"reason": "busy"}
    assert "/tmp" not in str(caught.value.details)


def test_remote_engine_streams_and_bounds_an_undeclared_response(tmp_path: Path) -> None:
    class OversizedStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"x" * 700
            yield b"x" * 700

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _health_response()
        return httpx.Response(
            200,
            stream=OversizedStream(),
            headers={
                **_common_headers(),
                HEADER_FORMAT: "stl",
                HEADER_SHA256: hashlib.sha256(b"x" * 1024).hexdigest(),
                HEADER_SIZE: "1024",
                HEADER_DURATION_MS: "1",
                HEADER_SOURCE_SHA256: hashlib.sha256(request.content).hexdigest(),
                HEADER_DIAGNOSTICS: "",
            },
        )

    engine = _engine(tmp_path, httpx.MockTransport(handler))
    engine.settings = engine.settings.model_copy(update={"max_artifact_bytes": 1024})
    with pytest.raises(CompilationError, match="artifact limit"):
        engine.compile("cube(1);")
