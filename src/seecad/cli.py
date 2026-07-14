"""Typer command line client for local and automated SeeCAD workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from seecad.config import get_settings
from seecad.errors import SeeCADError
from seecad.models import (
    AssemblyComponent,
    CompareRequest,
    CompileRequest,
    ComponentKind,
    CreateDesignRequest,
    CreateRevisionRequest,
    Cylinder,
    DesignSpec,
    NegativeFeature,
    NegativeIntent,
    PositiveSolid,
    RoundedBox,
    ToolAccessChannel,
    Transform,
    Vec3,
)
from seecad.service import SeeCADService

app = typer.Typer(
    name="seecad",
    help="Semantic AI-assisted CAD with deterministic, auditable OpenSCAD output.",
    no_args_is_help=True,
)


def _service() -> SeeCADService:
    return SeeCADService(get_settings())


def _emit(value: object) -> None:
    serializer = getattr(value, "model_dump_json", None)
    if serializer is not None:
        typer.echo(serializer(indent=2))
    else:
        typer.echo(json.dumps(value, indent=2, default=str))


def _fail(exc: SeeCADError) -> None:
    typer.echo(
        json.dumps(
            {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            indent=2,
        ),
        err=True,
    )
    raise typer.Exit(code=1) from exc


@app.command()
def create(
    prompt: Annotated[str | None, typer.Option(help="Natural-language design intent.")] = None,
    spec: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
) -> None:
    """Create a new design from exactly one prompt or DesignSpec JSON file."""

    try:
        parsed = DesignSpec.model_validate_json(spec.read_text()) if spec else None
        result = _service().create_design(CreateDesignRequest(prompt=prompt, spec=parsed))
        _emit(result)
    except SeeCADError as exc:
        _fail(exc)


@app.command()
def revise(
    design_id: str,
    parent_revision_id: str,
    prompt: Annotated[str | None, typer.Option()] = None,
    spec: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
) -> None:
    """Append an immutable child revision to an existing design."""

    try:
        parsed = DesignSpec.model_validate_json(spec.read_text()) if spec else None
        result = _service().create_revision(
            design_id,
            CreateRevisionRequest(
                parent_revision_id=parent_revision_id,
                prompt=prompt,
                spec=parsed,
            ),
        )
        _emit(result)
    except SeeCADError as exc:
        _fail(exc)


@app.command("compile")
def compile_command(
    design_id: str,
    revision_id: str,
    output_format: Annotated[str, typer.Option("--format")] = "stl",
) -> None:
    """Compile a revision through the bounded OpenSCAD worker."""

    try:
        result = _service().compile_revision(
            design_id,
            revision_id,
            CompileRequest(format=output_format),  # type: ignore[arg-type]
        )
        _emit(result)
    except SeeCADError as exc:
        _fail(exc)


@app.command()
def analyze(
    design_id: str,
    revision_id: str,
    auto_compile: bool = True,
) -> None:
    """Analyze topology and bounded DFM evidence for a revision."""

    try:
        result = _service().analyze_revision(design_id, revision_id, auto_compile=auto_compile)
        _emit(result)
    except SeeCADError as exc:
        _fail(exc)


@app.command()
def get(design_id: str, revision_id: str | None = None) -> None:
    """Read a whole design history or one revision."""

    try:
        service = _service()
        result = (
            service.get_revision(design_id, revision_id)
            if revision_id
            else service.get_design(design_id)
        )
        _emit(result)
    except SeeCADError as exc:
        _fail(exc)


@app.command()
def compare(left_revision_id: str, right_revision_id: str) -> None:
    """Compare two semantic specs and their artifact sets."""

    try:
        _emit(
            _service().compare(
                CompareRequest(
                    left_revision_id=left_revision_id,
                    right_revision_id=right_revision_id,
                )
            )
        )
    except SeeCADError as exc:
        _fail(exc)


@app.command("export")
def export_command(
    design_id: str,
    revision_id: str,
    output: Annotated[Path, typer.Option("--output", "-o")],
    artifact_format: Annotated[str, typer.Option("--format")] = "scad",
) -> None:
    """Export a content-addressed derivative to a chosen local path."""

    try:
        data, artifact = _service().export_revision(design_id, revision_id, artifact_format)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        _emit({"path": str(output), "sha256": artifact.sha256})
    except SeeCADError as exc:
        _fail(exc)


def _demo_spec() -> DesignSpec:
    return DesignSpec(
        name="Precision inspection enclosure",
        intent=(
            "Printable electronics enclosure with one consolidated negative-space pass and "
            "deliberately long service-tool passages."
        ),
        units="mm",
        components=(
            AssemblyComponent(
                id="enclosure",
                name="Enclosure body",
                kind=ComponentKind.PART,
                purpose="Single printable enclosure component",
            ),
        ),
        positive_solids=(
            PositiveSolid(
                id="enclosure_body",
                name="Rounded enclosure body",
                component_id="enclosure",
                shape=RoundedBox(size=Vec3(x=86, y=62, z=24), radius=8),
                purpose="Complete material envelope before voids are applied",
            ),
        ),
        negative_features=(
            NegativeFeature(
                id="interior_pocket",
                name="Electronics cavity",
                shape=RoundedBox(size=Vec3(x=80, y=56, z=23), radius=5),
                transform=Transform(translate=Vec3(x=3, y=3, z=3)),
                intent=NegativeIntent.POCKET,
                rationale="Leaves a 3 mm floor and nominal 3 mm perimeter walls.",
                target_component_ids=("enclosure",),
            ),
            *tuple(
                NegativeFeature(
                    id=f"insert_hole_{index}",
                    name=f"Lid insert hole {index}",
                    shape=Cylinder(radius=1.6, height=12),
                    transform=Transform(translate=Vec3(x=x, y=y, z=14)),
                    intent=NegativeIntent.BLIND_HOLE,
                    rationale="Nominal M3 insert pilot; validate against the selected insert.",
                    target_component_ids=("enclosure",),
                )
                for index, (x, y) in enumerate(((8, 8), (78, 8), (78, 54), (8, 54)), start=1)
            ),
        ),
        tool_access_channels=(
            ToolAccessChannel(
                id="usb_service_channel",
                name="USB service passage",
                start=Vec3(x=43, y=-5, z=12),
                end=Vec3(x=43, y=67, z=12),
                tool_diameter=7,
                radial_clearance=1,
                endpoint_overtravel=4,
                tool="USB plug and inspection tool",
                rationale="Crosses both wall faces so wall edits do not strand the subtraction.",
                target_component_ids=("enclosure",),
            ),
            ToolAccessChannel(
                id="probe_service_channel",
                name="Calibration probe passage",
                start=Vec3(x=-5, y=31, z=14),
                end=Vec3(x=91, y=31, z=14),
                tool_diameter=4,
                endpoint_overtravel=4,
                tool="4 mm calibration probe",
                rationale="Provides a straight service path through the enclosure envelope.",
                target_component_ids=("enclosure",),
            ),
        ),
        assumptions=(
            "Nominal fit dimensions require printer- and material-specific coupons.",
            "No structural, ingress, thermal, or electrical safety guarantee is made.",
        ),
    )


@app.command()
def demo(
    output: Annotated[Path, typer.Option("--output", "-o")] = Path(".seecad/demo"),
) -> None:
    """Generate, compile, and analyze a semantic precision-enclosure fixture."""

    try:
        service = _service()
        created = service.create_design(CreateDesignRequest(spec=_demo_spec()))
        output.mkdir(parents=True, exist_ok=True)
        for filename in (
            "design.json",
            "model.scad",
            "manifest.json",
            "model.stl",
            "compile-stl.json",
            "analysis.json",
            "analysis-profile.json",
            "evidence-manifest.json",
        ):
            output.joinpath(filename).unlink(missing_ok=True)
        if not service.engine.is_available():
            for role in ("spec", "scad", "manifest"):
                data, artifact = service.export_revision(
                    created.design_id, created.revision_id, role
                )
                output.joinpath(artifact.filename).write_bytes(data)
            _emit(
                {
                    "design_id": created.design_id,
                    "revision_id": created.revision_id,
                    "output": str(output),
                    "compiled": False,
                    "reason": "OpenSCAD worker unavailable",
                }
            )
            return
        compiled = service.compile_revision(
            created.design_id, created.revision_id, CompileRequest(format="stl")
        )
        analyzed = service.analyze_revision(
            compiled.design_id, compiled.revision_id, auto_compile=False
        )
        bundle = service.export_evidence_bundle(
            analyzed.revision.design_id, analyzed.revision.revision_id
        )
        for filename, data in bundle.files.items():
            output.joinpath(filename).write_bytes(data)
        output.joinpath("evidence-manifest.json").write_bytes(bundle.manifest)
        _emit(
            {
                "design_id": created.design_id,
                "revision_id": analyzed.revision.revision_id,
                "output": str(output),
                "compiled": True,
                "mesh_sha256": analyzed.analysis.mesh_sha256,
                "evidence_manifest_sha256": bundle.manifest_sha256,
            }
        )
    except SeeCADError as exc:
        _fail(exc)


@app.command()
def serve() -> None:
    """Run the HTTP API with configured host and port."""

    from seecad.api import run

    run()


@app.command()
def mcp() -> None:
    """Run the stdio MCP server."""

    from seecad.mcp_server import run

    run()
