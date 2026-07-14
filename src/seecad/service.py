"""Application orchestration across planning, rendering, storage, and analysis."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast

from pydantic import JsonValue

from seecad.analysis import MeshAnalyzer
from seecad.config import Settings, get_settings
from seecad.engine import OpenSCADEngine
from seecad.errors import ConflictError, NotFoundError
from seecad.models import (
    AnalysisResponse,
    ApprovalRequest,
    ArtifactRef,
    CompareRequest,
    ComparisonResponse,
    CompileRequest,
    CreateDesignRequest,
    CreateRevisionRequest,
    DesignHistoryResponse,
    DesignSpec,
    DifferenceEntry,
    HealthResponse,
    MeshAnalysis,
    PrintProfile,
    RevisionResponse,
    canonical_print_profile_bytes,
    print_profile_sha256,
)
from seecad.planner import OpenAIPlanner
from seecad.scad import ScadGenerator, canonical_spec_bytes
from seecad.store import ArtifactStore, RevisionRepository

EVIDENCE_BUNDLE_ROLES = (
    "spec",
    "scad",
    "manifest",
    "stl",
    "compile_stl",
    "analysis",
    "analysis_profile",
)


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Verified files and deterministic inventory for one analyzed revision."""

    revision: RevisionResponse
    files: dict[str, bytes]
    manifest: bytes
    manifest_sha256: str


class SeeCADService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        planner: OpenAIPlanner | None = None,
        engine: OpenSCADEngine | None = None,
        analyzer: MeshAnalyzer | None = None,
        artifacts: ArtifactStore | None = None,
        repository: RevisionRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.artifacts = artifacts or ArtifactStore(
            self.settings.resolved_data_dir / "blobs",
            max_bytes=self.settings.max_artifact_bytes,
        )
        self.repository = repository or RevisionRepository(
            self.settings.resolved_database_path, self.artifacts
        )
        self.planner = planner or OpenAIPlanner(self.settings)
        self.engine = engine or OpenSCADEngine(self.settings)
        self.analyzer = analyzer or MeshAnalyzer()
        self.generator = ScadGenerator(nopscad_root=self.settings.nopscad_root)

    def create_design(self, request: CreateDesignRequest) -> RevisionResponse:
        recorded_prompt = request.prompt
        if request.spec is not None:
            spec = request.spec
            planning_metadata: dict[str, JsonValue] = {"source": "explicit_spec"}
        else:
            assert request.prompt is not None
            recorded_prompt = self._constrained_planner_prompt(
                request.prompt,
                requested_profile=request.requested_profile,
                load_case=request.load_case,
                dimensional_tolerance=request.dimensional_tolerance,
                infill_percent=request.infill_percent,
            )
            planned = self.planner.plan(recorded_prompt, images=request.images)
            spec = planned.spec
            if request.requested_profile is not None:
                spec = spec.model_copy(update={"print_profile": request.requested_profile})
            planning_metadata = {
                "source": "openai_responses",
                "model": self.settings.openai_model,
                "reasoning_mode": self.settings.openai_reasoning_mode,
                "reasoning_effort": self.settings.openai_reasoning_effort,
                "rationale": planned.rationale,
                "unresolved_questions": cast(JsonValue, list(planned.unresolved_questions)),
                "image_evidence_count": len(request.images),
                **self._constraint_metadata(request),
            }
        stored = self._store_source_artifacts(
            spec=spec,
            planning_metadata=planning_metadata,
            prompt=recorded_prompt,
        )
        metadata = {**request.metadata, **planning_metadata, "event": "created"}
        return self.repository.create_revision(spec=spec, artifacts=stored, metadata=metadata)

    def create_revision(self, design_id: str, request: CreateRevisionRequest) -> RevisionResponse:
        parent = self.repository.get_revision(request.parent_revision_id, design_id=design_id)
        recorded_prompt = request.prompt
        if request.spec is not None:
            spec = request.spec
            planning_metadata: dict[str, JsonValue] = {
                "source": "explicit_spec",
                "parent_revision_id": parent.revision_id,
            }
        else:
            assert request.prompt is not None
            parent_json = json.dumps(
                parent.spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            )
            constrained_instruction = self._constrained_planner_prompt(
                request.prompt,
                requested_profile=request.requested_profile,
                load_case=request.load_case,
                dimensional_tolerance=request.dimensional_tolerance,
                infill_percent=request.infill_percent,
            )
            recorded_prompt = (
                "Revise the current DesignSpec according to the instruction. Preserve valid "
                "unmentioned intent and keep IDs stable where entities remain the same.\n\n"
                f"CURRENT_DESIGN_SPEC_JSON:\n{parent_json}\n\n{constrained_instruction}"
            )
            planned = self.planner.plan(
                recorded_prompt,
                images=request.images,
            )
            spec = planned.spec
            if request.requested_profile is not None:
                spec = spec.model_copy(update={"print_profile": request.requested_profile})
            planning_metadata = {
                "source": "openai_responses_revision",
                "model": self.settings.openai_model,
                "reasoning_mode": self.settings.openai_reasoning_mode,
                "reasoning_effort": self.settings.openai_reasoning_effort,
                "rationale": planned.rationale,
                "unresolved_questions": cast(JsonValue, list(planned.unresolved_questions)),
                "image_evidence_count": len(request.images),
                "parent_revision_id": parent.revision_id,
                **self._constraint_metadata(request),
            }
        stored = self._store_source_artifacts(
            spec=spec,
            planning_metadata=planning_metadata,
            prompt=recorded_prompt,
        )
        return self.repository.create_revision(
            spec=spec,
            artifacts=stored,
            design_id=design_id,
            parent_revision_id=parent.revision_id,
            metadata={**request.metadata, **planning_metadata, "event": "revised"},
        )

    def compile_revision(
        self,
        design_id: str,
        revision_id: str,
        request: CompileRequest,
    ) -> RevisionResponse:
        revision = self.repository.get_revision(revision_id, design_id=design_id)
        if request.format in revision.artifacts:
            return revision
        scad = revision.artifacts.get("scad")
        if scad is None:
            raise ConflictError("revision has no generated SCAD artifact")
        try:
            source = self.artifacts.get(scad.sha256).decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ConflictError("SCAD artifact is not valid UTF-8") from exc
        result = self.engine.compile(source, output_format=request.format)
        compile_provenance: dict[str, object] | None = None
        if result.provenance is not None:
            if result.provenance.source_sha256 != scad.sha256:
                raise ConflictError("worker provenance does not reference the compiled SCAD")
            compile_provenance = {
                "protocol": result.provenance.protocol,
                "worker_build_id": result.provenance.worker_build_id,
                "openscad_version": result.provenance.openscad_version,
                "nopscad_revision": result.provenance.nopscad_revision,
                "nopscad_tree_sha256": result.provenance.nopscad_tree_sha256,
                "source_sha256": result.provenance.source_sha256,
            }
        media_type = "model/stl" if request.format == "stl" else "model/3mf"
        compiled = self.artifacts.put(
            result.content,
            media_type=media_type,
            filename=f"model.{request.format}",
        )
        report = self._put_json(
            {
                "schema_version": "1.0",
                "engine": result.engine,
                "format": result.format,
                "duration_seconds": result.duration_seconds,
                "diagnostics": result.diagnostics,
                "source_sha256": scad.sha256,
                "output_sha256": compiled.sha256,
                "provenance": compile_provenance,
            },
            filename=f"compile-{request.format}.json",
        )
        artifacts = {
            **revision.artifacts,
            request.format: compiled,
            f"compile_{request.format}": report,
        }
        metadata = {
            **revision.metadata,
            "event": "compiled",
            "compiled_format": request.format,
            "compile_engine": result.engine,
        }
        return self.repository.create_revision(
            spec=revision.spec,
            artifacts=artifacts,
            design_id=design_id,
            parent_revision_id=revision.revision_id,
            metadata=metadata,
        )

    def analyze_revision(
        self,
        design_id: str,
        revision_id: str,
        *,
        auto_compile: bool = True,
        profile: PrintProfile | None = None,
    ) -> AnalysisResponse:
        revision = self.repository.get_revision(revision_id, design_id=design_id)
        effective_profile = profile or revision.spec.print_profile
        profile_digest = print_profile_sha256(effective_profile)
        cached = self._cached_analysis(revision, profile_digest=profile_digest)
        if cached is not None:
            return cached
        if "stl" in revision.artifacts:
            for candidate in reversed(self.repository.list_revisions(design_id)):
                if (
                    candidate.parent_revision_id == revision.revision_id
                    and candidate.metadata.get("event") == "analyzed"
                ):
                    cached = self._cached_analysis(candidate, profile_digest=profile_digest)
                    if cached is not None:
                        return cached
        if "stl" not in revision.artifacts:
            if not auto_compile:
                raise ConflictError("analysis requires an STL artifact")
            revision = self.compile_revision(
                design_id, revision.revision_id, CompileRequest(format="stl")
            )
        stl = revision.artifacts["stl"]
        analysis = self.analyzer.analyze_stl(
            self.artifacts.get(stl.sha256),
            profile=effective_profile,
            mesh_sha256=stl.sha256,
        )
        analysis_ref = self.artifacts.put(
            analysis.model_dump_json(indent=2).encode("utf-8"),
            media_type="application/json",
            filename="analysis.json",
        )
        profile_ref = self.artifacts.put(
            canonical_print_profile_bytes(effective_profile),
            media_type="application/json",
            filename="analysis-profile.json",
        )
        result_revision = self.repository.create_revision(
            spec=revision.spec,
            artifacts={
                **revision.artifacts,
                "analysis": analysis_ref,
                "analysis_profile": profile_ref,
            },
            design_id=design_id,
            parent_revision_id=revision.revision_id,
            metadata={
                **revision.metadata,
                "event": "analyzed",
                "analysis_mesh_sha256": stl.sha256,
                "analysis_profile_sha256": profile_digest,
            },
        )
        return AnalysisResponse(revision=result_revision, analysis=analysis)

    def approve_revision(
        self,
        design_id: str,
        revision_id: str,
        request: ApprovalRequest,
    ) -> RevisionResponse:
        revision = self.repository.get_revision(revision_id, design_id=design_id)
        if revision.metadata.get("event") == "approved" or "approval" in revision.artifacts:
            raise ConflictError("revision is already an approval attestation")
        if revision.metadata.get("event") != "analyzed":
            raise ConflictError("approval is only available for an analyzed live revision")

        required_roles = ("spec", "scad", "stl", "compile_stl", "analysis", "analysis_profile")
        missing_roles = [role for role in required_roles if role not in revision.artifacts]
        if missing_roles:
            raise ConflictError(
                "approval requires an analyzed STL revision with its complete evidence chain",
                details={"missing_artifact_roles": missing_roles},
            )
        if self.artifacts.get(revision.artifacts["spec"].sha256) != canonical_spec_bytes(
            revision.spec
        ):
            raise ConflictError("spec artifact does not match the analyzed revision")

        analysis = MeshAnalysis.model_validate_json(
            self.artifacts.get(revision.artifacts["analysis"].sha256)
        )
        if analysis.mesh_sha256 != revision.artifacts["stl"].sha256:
            raise ConflictError("analysis does not reference this revision's STL artifact")
        if analysis.print_profile_sha256 != revision.artifacts["analysis_profile"].sha256:
            raise ConflictError("analysis profile evidence does not match its canonical digest")

        try:
            compile_report = json.loads(
                self.artifacts.get(revision.artifacts["compile_stl"].sha256)
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConflictError("STL compile report is not valid JSON evidence") from exc
        if not isinstance(compile_report, dict):
            raise ConflictError("STL compile report is not a JSON object")
        if compile_report.get("output_sha256") != revision.artifacts["stl"].sha256:
            raise ConflictError("STL compile report does not reference this revision's mesh")
        if compile_report.get("source_sha256") != revision.artifacts["scad"].sha256:
            raise ConflictError("STL compile report does not reference this revision's SCAD")

        artifact_digests = {
            role: artifact.sha256 for role, artifact in sorted(revision.artifacts.items())
        }
        attested_at = datetime.now(UTC)
        attestation = {
            "schema_version": "1.0",
            "kind": "human_revision_approval",
            "attested_at": attested_at.isoformat(),
            "attestor": request.attestor,
            "statement": request.statement,
            "design_id": design_id,
            "parent_revision_id": revision.revision_id,
            "parent_spec_sha256": revision.artifacts["spec"].sha256,
            "mesh_sha256": revision.artifacts["stl"].sha256,
            "compile_report_sha256": revision.artifacts["compile_stl"].sha256,
            "analysis_sha256": revision.artifacts["analysis"].sha256,
            "analysis_profile_sha256": analysis.print_profile_sha256,
            "parent_artifact_sha256": artifact_digests,
        }
        approval_ref = self._put_json(attestation, filename="approval.json")
        return self.repository.create_revision(
            spec=revision.spec,
            artifacts={**revision.artifacts, "approval": approval_ref},
            design_id=design_id,
            parent_revision_id=revision.revision_id,
            metadata={
                **revision.metadata,
                "event": "approved",
                "approved_parent_revision_id": revision.revision_id,
                "approval_sha256": approval_ref.sha256,
                "attestor": request.attestor,
            },
        )

    def get_revision(self, design_id: str, revision_id: str) -> RevisionResponse:
        return self.repository.get_revision(revision_id, design_id=design_id)

    def get_design(self, design_id: str) -> DesignHistoryResponse:
        return DesignHistoryResponse(
            design_id=design_id,
            revisions=self.repository.list_revisions(design_id),
        )

    def compare(self, request: CompareRequest) -> ComparisonResponse:
        left = self.repository.get_revision(request.left_revision_id)
        right = self.repository.get_revision(request.right_revision_id)
        left_spec = left.spec.model_dump(mode="json")
        right_spec = right.spec.model_dump(mode="json")
        differences: list[DifferenceEntry] = []
        self._diff(left_spec, right_spec, path="$", output=differences)
        roles = sorted(set(left.artifacts) | set(right.artifacts))
        artifact_changes: dict[str, JsonValue] = {}
        for role in roles:
            left_artifact = left.artifacts.get(role)
            right_artifact = right.artifacts.get(role)
            left_sha = left_artifact.sha256 if left_artifact else None
            right_sha = right_artifact.sha256 if right_artifact else None
            if left_sha != right_sha:
                artifact_changes[role] = {"left": left_sha, "right": right_sha}
        return ComparisonResponse(
            left_revision_id=left.revision_id,
            right_revision_id=right.revision_id,
            same_spec=not differences,
            differences=differences,
            artifact_changes=artifact_changes,
        )

    def export_revision(
        self, design_id: str, revision_id: str, artifact_format: str
    ) -> tuple[bytes, ArtifactRef]:
        revision = self.repository.get_revision(revision_id, design_id=design_id)
        role = "spec" if artifact_format == "spec" else artifact_format
        artifact = revision.artifacts.get(role)
        if artifact is None:
            raise NotFoundError(
                "requested export does not exist on this revision",
                details={"format": artifact_format},
            )
        return self.artifacts.get(artifact.sha256), artifact

    def export_evidence_bundle(self, design_id: str, revision_id: str) -> EvidenceBundle:
        """Export the complete evidence set linked by one analyzed revision."""

        revision = self.repository.get_revision(revision_id, design_id=design_id)
        if revision.metadata.get("event") != "analyzed":
            raise ConflictError("evidence bundle export requires an analyzed revision")
        missing_roles = [role for role in EVIDENCE_BUNDLE_ROLES if role not in revision.artifacts]
        if missing_roles:
            raise ConflictError(
                "analyzed revision is missing required evidence artifacts",
                details={"missing_artifact_roles": missing_roles},
            )

        chain: list[RevisionResponse] = []
        cursor = revision
        while True:
            chain.append(cursor)
            if cursor.parent_revision_id is None:
                break
            cursor = self.repository.get_revision(cursor.parent_revision_id, design_id=design_id)
        chain.reverse()

        files: dict[str, bytes] = {}
        artifact_entries: list[dict[str, object]] = []
        for role in EVIDENCE_BUNDLE_ROLES:
            data, artifact = self.export_revision(design_id, revision_id, role)
            if artifact.filename == "evidence-manifest.json" or artifact.filename in files:
                raise ConflictError(
                    "evidence bundle artifact filenames must be unique",
                    details={"filename": artifact.filename, "role": role},
                )
            files[artifact.filename] = data
            introduced_revision_id = next(
                candidate.revision_id
                for candidate in chain
                if (
                    candidate.artifacts.get(role) is not None
                    and candidate.artifacts[role].sha256 == artifact.sha256
                )
            )
            artifact_entries.append(
                {
                    "role": role,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                    "media_type": artifact.media_type,
                    "filename": artifact.filename,
                    "revision_id": revision.revision_id,
                    "introduced_revision_id": introduced_revision_id,
                }
            )

        revision_chain: list[dict[str, object]] = []
        for candidate in chain:
            event = candidate.metadata.get("event")
            if not isinstance(event, str):
                raise ConflictError(
                    "evidence revision chain has an invalid event",
                    details={"revision_id": candidate.revision_id},
                )
            revision_chain.append(
                {
                    "revision_id": candidate.revision_id,
                    "parent_revision_id": candidate.parent_revision_id,
                    "event": event,
                }
            )

        document = {
            "schema_version": "1.0",
            "kind": "seecad_evidence_bundle",
            "design_id": design_id,
            "revision_id": revision.revision_id,
            "parent_revision_id": revision.parent_revision_id,
            "source_revision_id": chain[0].revision_id,
            "revision_chain": revision_chain,
            "artifacts": artifact_entries,
        }
        serialized = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True)
        manifest = serialized.encode("utf-8") + b"\n"
        return EvidenceBundle(
            revision=revision,
            files=files,
            manifest=manifest,
            manifest_sha256=sha256(manifest).hexdigest(),
        )

    def get_artifact(self, sha256: str) -> tuple[bytes, ArtifactRef]:
        data = self.artifacts.get(sha256)
        # Artifact metadata is revision-scoped. Direct retrieval uses a generic type.
        return data, ArtifactRef(
            sha256=sha256,
            size_bytes=len(data),
            media_type="application/octet-stream",
            filename=sha256,
        )

    def health(self) -> HealthResponse:
        storage_writable = self.artifacts.writable()
        openscad_available = self.engine.is_available()
        return HealthResponse(
            status="ok" if storage_writable and openscad_available else "degraded",
            version="0.1.0",
            planner_configured=self.planner.configured,
            openscad_available=openscad_available,
            storage_writable=storage_writable,
        )

    def _put_json(self, value: Mapping[str, object], *, filename: str) -> ArtifactRef:
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.artifacts.put(data, media_type="application/json", filename=filename)

    def _cached_analysis(
        self,
        revision: RevisionResponse,
        *,
        profile_digest: str,
    ) -> AnalysisResponse | None:
        analysis_ref = revision.artifacts.get("analysis")
        profile_ref = revision.artifacts.get("analysis_profile")
        stl_ref = revision.artifacts.get("stl")
        if (
            analysis_ref is None
            or profile_ref is None
            or stl_ref is None
            or profile_ref.sha256 != profile_digest
        ):
            return None
        analysis = MeshAnalysis.model_validate_json(self.artifacts.get(analysis_ref.sha256))
        if (
            analysis.print_profile_sha256 != profile_digest
            or analysis.mesh_sha256 != stl_ref.sha256
        ):
            return None
        return AnalysisResponse(revision=revision, analysis=analysis)

    @staticmethod
    def _constrained_planner_prompt(
        prompt: str,
        *,
        requested_profile: PrintProfile | None,
        load_case: str | None,
        dimensional_tolerance: float | None,
        infill_percent: float | None,
    ) -> str:
        if all(
            value is None
            for value in (
                requested_profile,
                load_case,
                dimensional_tolerance,
                infill_percent,
            )
        ):
            return prompt

        sections = ["USER_INTENT:", prompt, "", "REQUESTED_MANUFACTURING_CONSTRAINTS:"]
        if requested_profile is not None:
            profile_json = canonical_print_profile_bytes(requested_profile).decode("utf-8")
            sections.extend(
                (
                    f"PRINT_PROFILE_CANONICAL_JSON: {profile_json}",
                    f"PRINT_PROFILE_SHA256: {print_profile_sha256(requested_profile)}",
                )
            )
        if dimensional_tolerance is not None:
            sections.append(f"DIMENSIONAL_TOLERANCE_MM: {dimensional_tolerance:.17g}")
        if infill_percent is not None:
            sections.append(f"INFILL_PERCENT: {infill_percent:.17g}")
        if load_case is not None:
            sections.append(f"LOAD_CASE: {load_case}")
        sections.append("")
        sections.append("Treat these as design inputs, not descriptive metadata.")
        if requested_profile is not None:
            sections.append(
                "The generated DesignSpec.print_profile must exactly match "
                "PRINT_PROFILE_CANONICAL_JSON."
            )
        return "\n".join(sections)

    @staticmethod
    def _constraint_metadata(
        request: CreateDesignRequest | CreateRevisionRequest,
    ) -> dict[str, JsonValue]:
        metadata: dict[str, JsonValue] = {}
        if request.requested_profile is not None:
            metadata["requested_profile"] = cast(
                JsonValue, request.requested_profile.model_dump(mode="json")
            )
            metadata["requested_profile_sha256"] = print_profile_sha256(request.requested_profile)
        if request.load_case is not None:
            metadata["requested_load_case"] = request.load_case
        if request.dimensional_tolerance is not None:
            metadata["requested_dimensional_tolerance_mm"] = request.dimensional_tolerance
        if request.infill_percent is not None:
            metadata["requested_infill_percent"] = request.infill_percent
        return metadata

    def _store_source_artifacts(
        self,
        *,
        spec: DesignSpec,
        planning_metadata: Mapping[str, JsonValue],
        prompt: str | None,
    ) -> dict[str, ArtifactRef]:
        validated = DesignSpec.model_validate(spec, strict=True)
        generated = self.generator.generate(validated)
        manifest = {**generated.manifest, "planning": dict(planning_metadata)}
        stored: dict[str, ArtifactRef] = {
            "spec": self.artifacts.put(
                canonical_spec_bytes(validated),
                media_type="application/json",
                filename="design.json",
            ),
            "scad": self.artifacts.put(
                generated.source.encode("utf-8"),
                media_type="application/x-openscad",
                filename="model.scad",
            ),
            "manifest": self._put_json(manifest, filename="manifest.json"),
        }
        if prompt is not None:
            stored["prompt"] = self.artifacts.put(
                prompt.encode("utf-8"),
                media_type="text/plain; charset=utf-8",
                filename="prompt.txt",
            )
        return stored

    @classmethod
    def _diff(
        cls,
        left: JsonValue,
        right: JsonValue,
        *,
        path: str,
        output: list[DifferenceEntry],
    ) -> None:
        if len(output) >= 1000:
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                child = f"{path}.{key}"
                if key not in left:
                    output.append(DifferenceEntry(path=child, left=None, right=right[key]))
                elif key not in right:
                    output.append(DifferenceEntry(path=child, left=left[key], right=None))
                else:
                    cls._diff(left[key], right[key], path=child, output=output)
            return
        if isinstance(left, list) and isinstance(right, list):
            for index in range(max(len(left), len(right))):
                child = f"{path}[{index}]"
                if index >= len(left):
                    output.append(DifferenceEntry(path=child, left=None, right=right[index]))
                elif index >= len(right):
                    output.append(DifferenceEntry(path=child, left=left[index], right=None))
                else:
                    cls._diff(left[index], right[index], path=child, output=output)
            return
        if left != right:
            output.append(DifferenceEntry(path=path, left=left, right=right))
