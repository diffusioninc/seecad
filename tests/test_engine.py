from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from seecad.analysis import MeshAnalyzer
from seecad.config import Settings
from seecad.engine import OpenSCADEngine
from seecad.errors import EngineUnavailableError
from seecad.models import (
    AssemblyComponent,
    ComponentKind,
    Cylinder,
    DesignSpec,
    LibraryCall,
    NegativeFeature,
    NegativeIntent,
    NumberArgument,
    PositiveSolid,
    Transform,
    Vec3,
    VectorArgument,
)
from seecad.scad import ScadGenerator


def test_docker_argv_is_networkless_readonly_and_bounded(tmp_path: Path) -> None:
    include = tmp_path / "vendor"
    include.mkdir()
    settings = Settings(
        data_dir=tmp_path / "data",
        openscad_mode="docker",
        openscad_include_paths=[include],
        max_artifact_bytes=268_435_456,
    )
    engine = OpenSCADEngine(settings)
    argv = engine._docker_argv(tmp_path / "input", tmp_path / "output", "stl", tmp_path / "cid")
    joined = " ".join(argv)
    assert "--network none" in joined
    assert "--read-only" in argv
    assert "--cap-drop ALL" in joined
    assert "--pull never" in joined
    assert "fsize=268435456:268435456" in joined
    assert "OPENSCADPATH=/libraries/0:/opt/libraries" in joined
    assert not any("sh -c" in item for item in argv)


def test_local_argv_never_uses_a_shell(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    argv = OpenSCADEngine(settings)._local_argv(Path("input.scad"), Path("output.stl"))
    assert argv == ["openscad", "-o", "output.stl", "input.scad"]


def test_auto_never_selects_unsandboxed_local_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("seecad.engine.shutil.which", lambda _binary: "/usr/bin/tool")
    auto = OpenSCADEngine(Settings(data_dir=tmp_path / "auto", openscad_mode="auto"))
    monkeypatch.setattr(auto, "_docker_image_available", lambda: True)
    assert auto.available_mode() == "docker"


def test_live_nopscad_tree_is_revalidated_before_every_docker_compile(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    root = vendor / "NopSCADlib"
    root.mkdir(parents=True)
    source_file = root / "core.scad"
    source_file.write_bytes(b"module fixture() { cube(1); }\n")
    file_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
    tree_hash = hashlib.sha256(f"{file_hash}  vendor/NopSCADlib/core.scad\n".encode()).hexdigest()
    (vendor / "NopSCADlib.UPSTREAM.json").write_text(
        json.dumps({"revision": "a" * 40, "tree_sha256": tree_hash})
    )
    engine = OpenSCADEngine(
        Settings(
            openscad_mode="docker",
            nopscad_root=root,
            openscad_include_paths=[vendor],
        )
    )
    engine.available_mode = lambda: "docker"  # type: ignore[method-assign]
    executions = 0

    def execute(
        argv: list[str],
        *,
        env: dict[str, str],
        cidfile: Path | None,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal executions
        del env, cidfile
        executions += 1
        output_mount = next(
            value
            for value in argv
            if value.startswith("type=bind,src=") and value.endswith(",dst=/output")
        )
        output_root = Path(output_mount.removeprefix("type=bind,src=").removesuffix(",dst=/output"))
        (output_root / "model.stl").write_bytes(b"mesh")
        return subprocess.CompletedProcess(argv, 0, "", "")

    engine._execute = execute  # type: ignore[method-assign]
    assert engine.compile("cube(1);").content == b"mesh"
    source_file.write_bytes(b"tampered after first compile\n")
    with pytest.raises(EngineUnavailableError, match="provenance verification"):
        engine.compile("cube(1);")
    assert executions == 1


@pytest.mark.integration
def test_pinned_worker_compiles_and_analyzes_audited_nopscad_primitive(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        openscad_mode="docker",
        openscad_include_paths=[Path("vendor")],
        nopscad_root=Path("vendor/NopSCADlib"),
        openscad_timeout_seconds=60,
    )
    engine = OpenSCADEngine(settings)
    if not engine.is_available():
        pytest.skip("the pinned seecad-openscad:local worker image is unavailable")
    spec = DesignSpec(
        name="Pinned worker integration",
        intent="Compile one audited NopSCADlib rounded solid.",
        units="mm",
        components=(
            AssemblyComponent(
                id="part",
                name="Part",
                kind=ComponentKind.PART,
                purpose="One audited library component",
            ),
        ),
        positive_solids=(
            PositiveSolid(
                id="body",
                name="Body",
                component_id="part",
                shape=LibraryCall(
                    source_path="utils/core/rounded_rectangle.scad",
                    module="rounded_rectangle",
                    arguments=(
                        VectorArgument(values=(10, 8, 2)),
                        NumberArgument(value=1),
                    ),
                ),
            ),
        ),
        negative_features=(
            NegativeFeature(
                id="audited-bore",
                name="Audited through bore",
                shape=Cylinder(radius=1, height=4),
                transform=Transform(translate=Vec3(x=5, y=4, z=-1)),
                intent=NegativeIntent.THROUGH_HOLE,
                rationale="Exercise component-scoped subtraction in the pinned worker.",
                target_component_ids=("part",),
            ),
        ),
    )
    generated = ScadGenerator(nopscad_root=settings.nopscad_root).generate(spec)
    assert "scoped_negative_id_audited_hbore" in generated.source
    compiled = engine.compile(generated.source, output_format="stl")
    assert len(compiled.content) > 1024
    analysis = MeshAnalyzer().analyze_stl(compiled.content, profile=spec.print_profile)
    watertight = next(
        measurement for measurement in analysis.measurements if measurement.name == "watertight"
    )
    assert watertight.value is True
