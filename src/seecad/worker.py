"""Single-job OpenSCAD worker served only over a fixed Unix-domain socket."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
import shutil
import socket
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

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
    WORKER_DIAGNOSTICS_LIMIT,
    WORKER_HEALTH_BODY_LIMIT,
    WORKER_PROTOCOL,
    WORKER_SOURCE_LIMIT,
    CompilationResult,
    NopSCADProvenance,
    OpenSCADEngine,
    verified_nopscad_provenance,
)
from seecad.errors import CompilationError, EngineUnavailableError

FIXED_WORKER_SOCKET = Path("/run/seecad/worker.sock")
_SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,127}\Z")


class WorkerEngine(Protocol):
    def is_available(self) -> bool: ...

    def compile(
        self,
        source: str,
        *,
        output_format: Literal["stl", "3mf"] = "stl",
    ) -> CompilationResult: ...


class _WorkerLocalOpenSCADEngine(OpenSCADEngine):
    """The only engine class allowed to select the unsandboxed local binary.

    This class is private to the already isolated, no-network worker process. Public
    Settings cannot express local mode, and the application service always constructs
    the base OpenSCADEngine.
    """

    def available_mode(self) -> Literal["local"] | None:
        return "local" if shutil.which(self.settings.openscad_binary) is not None else None


@dataclass(frozen=True, slots=True)
class _WorkerRequestError(Exception):
    status_code: int
    code: str
    message: str
    headers: dict[str, str] | None = None


def _probe_openscad_version(binary: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise EngineUnavailableError("OpenSCAD is unavailable in the worker")
    try:
        completed = subprocess.run(
            [resolved, "--version"],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            env={
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "HOME": "/tmp",
                "LANG": "C.UTF-8",
                "QT_QPA_PLATFORM": "offscreen",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EngineUnavailableError("OpenSCAD version probe failed") from exc
    output = " ".join((completed.stdout + " " + completed.stderr).split())
    if completed.returncode != 0 or _SAFE_VERSION.fullmatch(output) is None:
        raise EngineUnavailableError("OpenSCAD version probe failed")
    return output


def _common_headers(
    provenance: NopSCADProvenance,
    openscad_version: str,
    worker_build_id: str,
) -> dict[str, str]:
    return {
        HEADER_PROTOCOL: WORKER_PROTOCOL,
        HEADER_WORKER_BUILD_ID: worker_build_id,
        HEADER_NOP_REVISION: provenance.revision,
        HEADER_NOP_TREE_SHA256: provenance.tree_sha256,
        HEADER_OPENSCAD_VERSION: openscad_version,
    }


def _diagnostics_header(diagnostics: str) -> str:
    raw = diagnostics.encode("utf-8", errors="replace")[-WORKER_DIAGNOSTICS_LIMIT:]
    return base64.b64encode(raw).decode("ascii")


async def _read_source(request: Request) -> str:
    if request.headers.get("content-encoding", "identity") != "identity":
        raise _WorkerRequestError(415, "unsupported_encoding", "Content encoding is unsupported")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "text/plain":
        raise _WorkerRequestError(415, "unsupported_media_type", "Expected raw UTF-8 SCAD")
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdigit():
            raise _WorkerRequestError(400, "invalid_length", "Content length is invalid")
        if int(declared) > WORKER_SOURCE_LIMIT:
            raise _WorkerRequestError(413, "source_too_large", "SCAD source exceeds 8 MiB")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > WORKER_SOURCE_LIMIT:
            raise _WorkerRequestError(413, "source_too_large", "SCAD source exceeds 8 MiB")
        body.extend(chunk)
    try:
        return bytes(body).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _WorkerRequestError(400, "invalid_utf8", "SCAD source must be UTF-8") from exc


def create_worker_app(
    settings: Settings | None = None,
    *,
    engine: WorkerEngine | None = None,
    provenance: NopSCADProvenance | None = None,
    openscad_version: str | None = None,
) -> FastAPI:
    configured = settings or Settings()
    local_settings = configured.model_copy(
        update={
            "openscad_include_paths": [configured.nopscad_root.parent],
        }
    )
    worker_engine = engine or _WorkerLocalOpenSCADEngine(local_settings)
    if provenance is None:
        verified_nopscad_provenance(configured.nopscad_root)
    version = openscad_version or _probe_openscad_version(configured.openscad_binary)
    worker_build_id = configured.resolved_worker_build_id

    def identity_headers() -> dict[str, str]:
        current = provenance or verified_nopscad_provenance(configured.nopscad_root)
        return _common_headers(current, version, worker_build_id)

    compile_lock = asyncio.Lock()

    application = FastAPI(
        title="SeeCAD OpenSCAD worker",
        version=WORKER_PROTOCOL,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.exception_handler(_WorkerRequestError)
    async def handle_request_error(_request: Request, exc: _WorkerRequestError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers=exc.headers,
        )

    @application.exception_handler(CompilationError)
    async def handle_compile_error(_request: Request, exc: CompilationError) -> JSONResponse:
        diagnostics = exc.details.get("diagnostics")
        try:
            headers = await run_in_threadpool(identity_headers)
        except EngineUnavailableError:
            headers = {}
        if isinstance(diagnostics, str):
            headers[HEADER_DIAGNOSTICS] = _diagnostics_header(diagnostics)
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "compilation_failed",
                    "message": "OpenSCAD rejected the submitted model",
                }
            },
            headers=headers,
        )

    @application.exception_handler(EngineUnavailableError)
    async def handle_engine_error(_request: Request, _exc: EngineUnavailableError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "engine_unavailable",
                    "message": "OpenSCAD is unavailable in the worker",
                }
            },
        )

    @application.get("/v1/health", status_code=204)
    async def health() -> Response:
        headers = await run_in_threadpool(identity_headers)
        if not await run_in_threadpool(worker_engine.is_available):
            raise EngineUnavailableError("OpenSCAD is unavailable in the worker")
        return Response(status_code=204, headers=headers)

    @application.post("/v1/compile")
    async def compile_scad(
        request: Request,
        format: Annotated[Literal["stl", "3mf"], Query()] = "stl",
    ) -> Response:
        source = await _read_source(request)
        if compile_lock.locked():
            raise _WorkerRequestError(
                503,
                "worker_busy",
                "The single OpenSCAD worker slot is busy",
                headers={
                    HEADER_WORKER_STATE: "busy",
                    "Retry-After": "1",
                },
            )
        await compile_lock.acquire()
        try:
            common_headers = await run_in_threadpool(identity_headers)
            result = await run_in_threadpool(
                worker_engine.compile,
                source,
                output_format=format,
            )
        finally:
            compile_lock.release()
        digest = hashlib.sha256(result.content).hexdigest()
        source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        headers = {
            **common_headers,
            HEADER_FORMAT: format,
            HEADER_SHA256: digest,
            HEADER_SOURCE_SHA256: source_sha256,
            HEADER_SIZE: str(len(result.content)),
            HEADER_DURATION_MS: str(max(0, round(result.duration_seconds * 1000))),
            HEADER_DIAGNOSTICS: _diagnostics_header(result.diagnostics),
        }
        return Response(
            content=result.content,
            media_type="model/stl" if format == "stl" else "model/3mf",
            headers=headers,
        )

    return application


def _prepare_socket_directory() -> None:
    parent = FIXED_WORKER_SOCKET.parent
    try:
        parent.mkdir(mode=0o700, parents=False, exist_ok=True)
        parent_stat = parent.lstat()
    except OSError as exc:
        raise RuntimeError("Cannot prepare the fixed worker socket directory") from exc
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
        or parent.is_symlink()
    ):
        raise RuntimeError("The fixed worker socket directory is not safely owned")
    parent.chmod(0o700)
    _remove_owned_socket()


def _remove_owned_socket() -> None:
    try:
        socket_stat = FIXED_WORKER_SOCKET.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RuntimeError("Cannot inspect the fixed worker socket") from exc
    if not stat.S_ISSOCK(socket_stat.st_mode) or socket_stat.st_uid != os.getuid():
        raise RuntimeError("Refusing to remove an unsafe worker socket path")
    FIXED_WORKER_SOCKET.unlink()


def _bind_owned_socket() -> socket.socket:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(os.fspath(FIXED_WORKER_SOCKET))
        FIXED_WORKER_SOCKET.chmod(0o600)
        socket_stat = FIXED_WORKER_SOCKET.lstat()
    except OSError:
        listener.close()
        raise
    if not stat.S_ISSOCK(socket_stat.st_mode) or socket_stat.st_uid != os.getuid():
        listener.close()
        raise RuntimeError("The bound worker socket is not safely owned")
    listener.set_inheritable(True)
    return listener


def run() -> None:
    """Own, serve, and clean up the fixed Compose worker socket."""

    import uvicorn

    settings = Settings()
    if settings.openscad_worker_socket != FIXED_WORKER_SOCKET:
        raise RuntimeError("The worker runner only serves the fixed /run/seecad socket")
    _prepare_socket_directory()
    old_umask = os.umask(0o077)
    listener: socket.socket | None = None
    try:
        listener = _bind_owned_socket()
        uvicorn.run(
            create_worker_app(settings),
            fd=listener.fileno(),
            workers=1,
            access_log=False,
            proxy_headers=False,
            server_header=False,
        )
    finally:
        if listener is not None:
            listener.close()
        os.umask(old_umask)
        _remove_owned_socket()


def healthcheck() -> None:
    """Bounded container health probe for the fixed UDS endpoint."""

    try:
        transport = httpx.HTTPTransport(uds=os.fspath(FIXED_WORKER_SOCKET), retries=0)
        with (
            httpx.Client(
                base_url="http://seecad-worker",
                transport=transport,
                timeout=httpx.Timeout(2.0),
                trust_env=False,
            ) as client,
            client.stream("GET", "/v1/health") as response,
        ):
            if response.status_code != 204:
                raise RuntimeError
            if response.headers.get(HEADER_PROTOCOL) != WORKER_PROTOCOL:
                raise RuntimeError
            if response.headers.get(HEADER_WORKER_BUILD_ID) != Settings().resolved_worker_build_id:
                raise RuntimeError
            if _SAFE_VERSION.fullmatch(response.headers.get(HEADER_OPENSCAD_VERSION, "")) is None:
                raise RuntimeError
            if not re.fullmatch(r"[a-f0-9]{40}", response.headers.get(HEADER_NOP_REVISION, "")):
                raise RuntimeError
            if not re.fullmatch(r"[a-f0-9]{64}", response.headers.get(HEADER_NOP_TREE_SHA256, "")):
                raise RuntimeError
            total = 0
            for chunk in response.iter_raw():
                total += len(chunk)
                if total > WORKER_HEALTH_BODY_LIMIT:
                    raise RuntimeError
    except (httpx.HTTPError, OSError, RuntimeError):
        raise SystemExit(1) from None
