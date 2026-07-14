"""Stable domain errors shared by HTTP, CLI, and MCP surfaces."""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import JsonValue, TypeAdapter, ValidationError

_DETAILS_ADAPTER = TypeAdapter(dict[str, JsonValue])


class SeeCADError(Exception):
    """Base exception with a stable, machine-readable code."""

    code = "seecad_error"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        try:
            validated = _DETAILS_ADAPTER.validate_python(dict(details or {}))
            if (
                len(validated) > 64
                or len(json.dumps(validated, separators=(",", ":")).encode()) > 64 * 1024
            ):
                self.details: dict[str, JsonValue] = {"details_truncated": True}
            else:
                self.details = validated
        except (ValidationError, TypeError, ValueError):
            self.details = {"details_redacted": True}


class InvalidDesignError(SeeCADError):
    code = "invalid_design"
    status_code = 422


class NotFoundError(SeeCADError):
    code = "not_found"
    status_code = 404


class ConflictError(SeeCADError):
    code = "conflict"
    status_code = 409


class ArtifactError(SeeCADError):
    code = "artifact_error"
    status_code = 500


class EngineUnavailableError(SeeCADError):
    code = "engine_unavailable"
    status_code = 503


class CompilationError(SeeCADError):
    code = "compilation_failed"
    status_code = 422


class AnalysisError(SeeCADError):
    code = "analysis_failed"
    status_code = 422


class PlannerError(SeeCADError):
    code = "planning_failed"
    status_code = 502


class PlannerUnavailableError(SeeCADError):
    code = "planner_unavailable"
    status_code = 503


class SecurityError(SeeCADError):
    code = "security_violation"
    status_code = 400
