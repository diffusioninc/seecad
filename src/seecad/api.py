"""FastAPI transport for SeeCAD's immutable revision service."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from seecad.config import get_settings
from seecad.errors import SeeCADError
from seecad.models import (
    AnalysisResponse,
    AnalyzeRequest,
    ApprovalRequest,
    CompareRequest,
    ComparisonResponse,
    CompileRequest,
    CreateDesignRequest,
    CreateRevisionRequest,
    DesignHistoryResponse,
    HealthResponse,
    ProofSheetRequest,
    RevisionResponse,
)
from seecad.service import SeeCADService

API_REQUEST_LIMIT_BYTES = 50 * 1024 * 1024
API_REQUEST_LIMIT_MIB = API_REQUEST_LIMIT_BYTES // (1024 * 1024)


def _request_too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={
            "error": {
                "code": "request_too_large",
                "message": f"Request exceeds the {API_REQUEST_LIMIT_MIB} MiB API limit.",
                "details": {},
            }
        },
    )


class RequestSizeLimitMiddleware:
    """Enforce the request cap from both headers and bytes received from ASGI."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = API_REQUEST_LIMIT_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.lower(): value for key, value in cast(list[tuple[bytes, bytes]], scope["headers"])
        }
        content_length = headers.get(b"content-length", b"")
        if content_length.isdigit() and int(content_length) > self.max_bytes:
            await _request_too_large_response()(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
                if len(body) > self.max_bytes:
                    await _request_too_large_response()(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                return

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)


@lru_cache(maxsize=1)
def get_service() -> SeeCADService:
    return SeeCADService(get_settings())


ServiceDependency = Annotated[SeeCADService, Depends(get_service)]


def create_app(*, request_limit_bytes: int = API_REQUEST_LIMIT_BYTES) -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="SeeCAD API",
        version="0.1.0",
        description="Semantic CAD planning, deterministic OpenSCAD, and evidence-aware DFM.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )
    application.add_middleware(RequestSizeLimitMiddleware, max_bytes=request_limit_bytes)

    @application.exception_handler(SeeCADError)
    async def handle_domain_error(_request: Request, exc: SeeCADError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": jsonable_encoder(exc.details),
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "request_validation_failed",
                    "message": "Request body or parameters failed validation.",
                    "details": {"errors": jsonable_encoder(exc.errors())},
                }
            },
        )

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    @application.get("/v1/health", response_model=HealthResponse, tags=["operations"])
    async def health(service: ServiceDependency) -> HealthResponse:
        return await run_in_threadpool(service.health)

    @application.get("/ready", response_model=HealthResponse, tags=["operations"])
    @application.get("/v1/ready", response_model=HealthResponse, tags=["operations"])
    async def ready(service: ServiceDependency) -> Response:
        current = await run_in_threadpool(service.health)
        return JSONResponse(
            status_code=200 if current.status == "ok" else 503,
            content=jsonable_encoder(current),
        )

    @application.post(
        "/v1/designs", response_model=RevisionResponse, status_code=201, tags=["designs"]
    )
    async def create_design(
        payload: CreateDesignRequest, service: ServiceDependency
    ) -> RevisionResponse:
        return await run_in_threadpool(service.create_design, payload)

    @application.post(
        "/v1/designs/{design_id}/revisions",
        response_model=RevisionResponse,
        status_code=201,
        tags=["designs"],
    )
    async def create_revision(
        design_id: str,
        payload: CreateRevisionRequest,
        service: ServiceDependency,
    ) -> RevisionResponse:
        return await run_in_threadpool(service.create_revision, design_id, payload)

    @application.get(
        "/v1/designs/{design_id}", response_model=DesignHistoryResponse, tags=["designs"]
    )
    async def get_design(design_id: str, service: ServiceDependency) -> DesignHistoryResponse:
        return await run_in_threadpool(service.get_design, design_id)

    @application.get(
        "/v1/designs/{design_id}/revisions/{revision_id}",
        response_model=RevisionResponse,
        tags=["designs"],
    )
    async def get_revision(
        design_id: str, revision_id: str, service: ServiceDependency
    ) -> RevisionResponse:
        return await run_in_threadpool(service.get_revision, design_id, revision_id)

    @application.post(
        "/v1/designs/{design_id}/revisions/{revision_id}/compile",
        response_model=RevisionResponse,
        tags=["build"],
    )
    async def compile_revision(
        design_id: str,
        revision_id: str,
        payload: CompileRequest,
        service: ServiceDependency,
    ) -> RevisionResponse:
        return await run_in_threadpool(service.compile_revision, design_id, revision_id, payload)

    @application.post(
        "/v1/designs/{design_id}/revisions/{revision_id}/proof-sheets",
        response_model=RevisionResponse,
        tags=["analysis"],
    )
    async def generate_proof_sheets(
        design_id: str,
        revision_id: str,
        payload: ProofSheetRequest,
        service: ServiceDependency,
    ) -> RevisionResponse:
        return await run_in_threadpool(
            service.generate_proof_sheets, design_id, revision_id, payload
        )

    @application.post(
        "/v1/designs/{design_id}/revisions/{revision_id}/analyze",
        response_model=AnalysisResponse,
        tags=["analysis"],
    )
    async def analyze_revision(
        design_id: str,
        revision_id: str,
        payload: AnalyzeRequest,
        service: ServiceDependency,
    ) -> AnalysisResponse:
        return await run_in_threadpool(
            service.analyze_revision,
            design_id,
            revision_id,
            auto_compile=payload.auto_compile,
            profile=payload.profile,
        )

    @application.post(
        "/v1/designs/{design_id}/revisions/{revision_id}/approve",
        response_model=RevisionResponse,
        status_code=201,
        tags=["analysis"],
    )
    async def approve_revision(
        design_id: str,
        revision_id: str,
        payload: ApprovalRequest,
        service: ServiceDependency,
    ) -> RevisionResponse:
        return await run_in_threadpool(
            service.approve_revision,
            design_id,
            revision_id,
            payload,
        )

    @application.post("/v1/compare", response_model=ComparisonResponse, tags=["analysis"])
    async def compare(payload: CompareRequest, service: ServiceDependency) -> ComparisonResponse:
        return await run_in_threadpool(service.compare, payload)

    @application.get("/v1/artifacts/{sha256}", tags=["artifacts"])
    async def get_artifact(sha256: str, service: ServiceDependency) -> Response:
        data, artifact = await run_in_threadpool(service.get_artifact, sha256)
        return Response(
            content=data,
            media_type=artifact.media_type,
            headers={"ETag": f'"sha256:{artifact.sha256}"', "Cache-Control": "immutable"},
        )

    @application.get("/v1/designs/{design_id}/revisions/{revision_id}/export", tags=["artifacts"])
    async def export_revision(
        design_id: str,
        revision_id: str,
        service: ServiceDependency,
        format: Annotated[
            Literal[
                "spec",
                "scad",
                "stl",
                "3mf",
                "analysis",
                "proof_sheet_manifest",
                "proof_sheets",
                "proof_sheet_archive",
            ],
            Query(),
        ] = "scad",
    ) -> Response:
        data, artifact = await run_in_threadpool(
            service.export_revision, design_id, revision_id, format
        )
        disposition = "inline" if format == "proof_sheets" else "attachment"
        headers = {
            "Content-Disposition": f'{disposition}; filename="{artifact.filename}"',
            "ETag": f'"sha256:{artifact.sha256}"',
            "X-Content-Type-Options": "nosniff",
        }
        if format == "proof_sheets":
            headers["Content-Security-Policy"] = (
                "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
                "base-uri 'none'; frame-ancestors 'none'; sandbox"
            )
        return Response(
            content=data,
            media_type=artifact.media_type,
            headers=headers,
        )

    return application


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("seecad.api:app", host=settings.api_host, port=settings.api_port)
