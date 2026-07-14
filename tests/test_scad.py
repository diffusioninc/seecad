from __future__ import annotations

from pathlib import Path

import pytest

from seecad.errors import InvalidDesignError
from seecad.models import (
    AssemblyComponent,
    Box,
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
from seecad.scad import ScadGenerator, _library_provenance


def test_generator_is_deterministic_and_uses_one_negative_pass(simple_spec: DesignSpec) -> None:
    generator = ScadGenerator(nopscad_root=Path("vendor/NopSCADlib"))
    first = generator.generate(simple_spec)
    second = generator.generate(simple_spec)
    assert first == second
    assert first.source.count("difference()") == 1
    assert "module positive_volume()" in first.source
    assert "module negative_volume()" in first.source
    assert "module tool_access_id_driver_haccess()" in first.source
    assert first.manifest["units"] == "mm"
    assert first.manifest["boolean_strategy"] == (
        "single_component_scoped_negative_difference_pass"
    )
    assert first.manifest["assembly_validation"]["negative_scope_ownership"] == (
        "exact_by_construction"
    )


def test_module_encoding_is_injective() -> None:
    spec = DesignSpec(
        name="IDs",
        intent="Distinct named modules.",
        units="mm",
        components=(
            AssemblyComponent(
                id="body",
                name="Body",
                kind=ComponentKind.PART,
                purpose="One fused test component",
            ),
        ),
        positive_solids=(
            PositiveSolid(
                id="foo-bar",
                name="A",
                component_id="body",
                shape=Box(size=Vec3(x=1, y=1, z=1)),
            ),
            PositiveSolid(
                id="foo_bar",
                name="B",
                component_id="body",
                shape=Box(size=Vec3(x=1, y=1, z=1)),
            ),
        ),
    )
    source = ScadGenerator().generate(spec).source
    assert "positive_id_foo_hbar" in source
    assert "positive_id_foo_ubar" in source


def test_slot_scope_cannot_clip_touching_fastener_head() -> None:
    spec = DesignSpec(
        name="Scoped extrusion slot",
        intent="Keep an extrusion slot from cutting adjacent hardware.",
        units="mm",
        components=(
            AssemblyComponent(
                id="extrusion",
                name="Extrusion",
                kind=ComponentKind.STOCK,
                purpose="T-slot stock member",
            ),
            AssemblyComponent(
                id="screw",
                name="Screw head",
                kind=ComponentKind.FASTENER,
                purpose="Visible supported fastener head",
                must_contact=("extrusion",),
            ),
        ),
        positive_solids=(
            PositiveSolid(
                id="extrusion-solid",
                name="Extrusion solid",
                component_id="extrusion",
                shape=Box(size=Vec3(x=10, y=10, z=10)),
            ),
            PositiveSolid(
                id="screw-head-solid",
                name="Screw head solid",
                component_id="screw",
                shape=Cylinder(radius=2, height=2),
                transform=Transform(translate=Vec3(x=5, y=5, z=10)),
            ),
        ),
        negative_features=(
            NegativeFeature(
                id="extrusion-slot",
                name="Extrusion slot",
                shape=Cylinder(radius=1, height=14),
                transform=Transform(translate=Vec3(x=5, y=5, z=-1)),
                intent=NegativeIntent.CLEARANCE,
                rationale="Slot belongs only to the stock member.",
                target_component_ids=("extrusion",),
            ),
        ),
    )

    generated = ScadGenerator().generate(spec)
    scoped_module = generated.source.split(
        "module scoped_negative_id_extrusion_hslot() {", maxsplit=1
    )[1].split("\n}\n", maxsplit=1)[0]
    assert "component_positive_id_extrusion();" in scoped_module
    assert "component_positive_id_screw();" not in scoped_module
    assert generated.source.count("difference()") == 1
    assert generated.manifest["negative_targets"] == {"extrusion-slot": ["extrusion"]}


def test_legacy_designs_remain_readable_but_cannot_generate_new_scad() -> None:
    legacy = DesignSpec(
        schema_version="1.0",
        name="Legacy global boolean",
        intent="Read historical evidence without reproducing unsafe compilation.",
        units="mm",
        positive_solids=(
            PositiveSolid(
                id="body",
                name="Body",
                shape=Box(size=Vec3(x=1, y=1, z=1)),
            ),
        ),
    )
    serialized = legacy.model_dump(mode="json")
    assert "components" not in serialized
    assert "component_id" not in serialized["positive_solids"][0]
    with pytest.raises(InvalidDesignError, match=r"legacy schema 1\.0 designs are read-only"):
        ScadGenerator().generate(legacy)


def test_nopscad_call_is_pinned_allowlisted_and_signature_checked() -> None:
    call = LibraryCall(
        source_path="utils/core/rounded_rectangle.scad",
        module="rounded_rectangle",
        arguments=(
            VectorArgument(values=(10, 8, 2)),
            NumberArgument(value=1),
        ),
    )
    spec = DesignSpec(
        name="Nop primitive",
        intent="Use one audited rounded primitive.",
        units="mm",
        components=(
            AssemblyComponent(
                id="part",
                name="Part",
                kind=ComponentKind.PART,
                purpose="One audited library component",
            ),
        ),
        positive_solids=(PositiveSolid(id="body", name="Body", component_id="part", shape=call),),
    )
    generated = ScadGenerator(nopscad_root=Path("vendor/NopSCADlib")).generate(spec)
    assert "include <NopSCADlib/core.scad>;" in generated.source
    assert "rounded_rectangle([10, 8, 2], 1);" in generated.source
    assert generated.manifest["libraries"][0]["provenance_status"] == "pinned"
    assert generated.manifest["libraries"][0]["revision"] == (
        "c9baa0ed0faa23e849141c3d8c6728545d6af910"
    )


def test_nopscad_call_rejects_builtin_or_bad_signature() -> None:
    unsafe = LibraryCall(
        source_path="utils/core/rounded_rectangle.scad",
        module="import",
        arguments=(NumberArgument(value=1),),
    )
    spec = DesignSpec(
        name="Unsafe",
        intent="Must be rejected.",
        units="mm",
        components=(
            AssemblyComponent(
                id="part",
                name="Part",
                kind=ComponentKind.PART,
                purpose="Unsafe test component",
            ),
        ),
        positive_solids=(PositiveSolid(id="body", name="Body", component_id="part", shape=unsafe),),
    )
    with pytest.raises(InvalidDesignError):
        ScadGenerator(nopscad_root=Path("vendor/NopSCADlib")).generate(spec)


def test_nopscad_tree_digest_is_recomputed() -> None:
    provenance = _library_provenance(Path("vendor/NopSCADlib").resolve())
    assert provenance["tree_sha256"] == (
        "810daa212a1d6f17c489eb758926d57593020ba810e52eecbffbf445cd0cff53"
    )
