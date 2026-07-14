from __future__ import annotations

import asyncio
import base64
import tempfile
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import seecad.worker as worker_module
from seecad.config import Settings
from seecad.engine import (
    HEADER_DIAGNOSTICS,
    HEADER_FORMAT,
    HEADER_PROTOCOL,
    HEADER_SOURCE_SHA256,
    HEADER_WORKER_BUILD_ID,
    WORKER_DIAGNOSTICS_LIMIT,
    CompilationResult,
    NopSCADProvenance,
)
from seecad.worker import create_worker_app

PROVENANCE = NopSCADProvenance(revision="a" * 40, tree_sha256="b" * 64)
BUILD_ID = "sha256-" + "c" * 64


class FakeEngine:
    def __init__(self) -> None:
        self.sources: list[str] = []

    def is_available(self) -> bool:
        return True

    def compile(self, source: str, *, output_format: str = "stl") -> CompilationResult:
        self.sources.append(source)
        return CompilationResult(
            content=b"mesh-bytes",
            format=output_format,  # type: ignore[arg-type]
            engine="local",
            duration_seconds=0.125,
            diagnostics="z" * (WORKER_DIAGNOSTICS_LIMIT + 100),
        )


def _app(engine: FakeEngine) -> object:
    return create_worker_app(
        Settings(
            openscad_worker_build_id=BUILD_ID,
        ),
        engine=engine,
        provenance=PROVENANCE,
        openscad_version="OpenSCAD version 2021.01",
    )


def test_worker_accepts_raw_utf8_and_returns_bound_evidence_headers() -> None:
    engine = FakeEngine()
    with TestClient(_app(engine)) as client:  # type: ignore[arg-type]
        response = client.post(
            "/v1/compile?format=stl",
            content=b"cube([1, 1, 1]);\n",
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
    assert response.status_code == 200
    assert response.content == b"mesh-bytes"
    assert engine.sources == ["cube([1, 1, 1]);\n"]
    assert response.headers[HEADER_PROTOCOL] == "1"
    assert response.headers[HEADER_WORKER_BUILD_ID] == BUILD_ID
    assert response.headers[HEADER_FORMAT] == "stl"
    assert len(response.headers[HEADER_SOURCE_SHA256]) == 64
    diagnostics = base64.b64decode(response.headers[HEADER_DIAGNOSTICS], validate=True)
    assert len(diagnostics) == WORKER_DIAGNOSTICS_LIMIT


@pytest.mark.parametrize(
    ("content", "content_type", "status"),
    [
        (b"\xff", "text/plain", 400),
        (b"cube(1);", "application/json", 415),
        (b"cube(1);", "text/plain", 200),
    ],
)
def test_worker_validates_raw_input(content: bytes, content_type: str, status: int) -> None:
    with TestClient(_app(FakeEngine())) as client:  # type: ignore[arg-type]
        response = client.post(
            "/v1/compile?format=stl",
            content=content,
            headers={"Content-Type": content_type},
        )
    assert response.status_code == status


def test_worker_rejects_oversized_declared_body_without_reading_it() -> None:
    with TestClient(_app(FakeEngine())) as client:  # type: ignore[arg-type]
        response = client.post(
            "/v1/compile?format=stl",
            content=b"",
            headers={
                "Content-Type": "text/plain",
                "Content-Length": str(8 * 1024 * 1024 + 1),
            },
        )
    assert response.status_code == 413


def test_worker_rejects_non_mesh_output_formats() -> None:
    with TestClient(_app(FakeEngine())) as client:  # type: ignore[arg-type]
        response = client.post(
            "/v1/compile?format=png",
            content=b"cube(1);",
            headers={"Content-Type": "text/plain"},
        )
    assert response.status_code == 422


def test_worker_has_one_compile_slot_and_fails_busy() -> None:
    started = threading.Event()
    release = threading.Event()

    class SlowEngine(FakeEngine):
        def compile(self, source: str, *, output_format: str = "stl") -> CompilationResult:
            started.set()
            assert release.wait(timeout=3)
            return super().compile(source, output_format=output_format)

    application = _app(SlowEngine())

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=application)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://worker") as client:
            first_task = asyncio.create_task(
                client.post(
                    "/v1/compile?format=stl",
                    content=b"cube(1);",
                    headers={"Content-Type": "text/plain"},
                )
            )
            assert await asyncio.to_thread(started.wait, 2)
            busy = await client.post(
                "/v1/compile?format=stl",
                content=b"cube(2);",
                headers={"Content-Type": "text/plain"},
            )
            release.set()
            return await first_task, busy

    first, busy = asyncio.run(exercise())
    assert first.status_code == 200
    assert busy.status_code == 503
    assert busy.headers["Retry-After"] == "1"


def test_socket_cleanup_only_removes_an_owned_unix_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory(prefix="scw-", dir="/tmp") as temporary:
        socket_path = Path(temporary) / "w.sock"
        monkeypatch.setattr(worker_module, "FIXED_WORKER_SOCKET", socket_path)
        socket_path.write_text("not a socket")
        with pytest.raises(RuntimeError, match="unsafe"):
            worker_module._remove_owned_socket()
        socket_path.unlink()
        listener = worker_module._bind_owned_socket()
        try:
            assert socket_path.stat().st_mode & 0o777 == 0o600
            worker_module._remove_owned_socket()
            assert not socket_path.exists()
        finally:
            listener.close()
