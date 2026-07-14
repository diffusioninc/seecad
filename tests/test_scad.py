from __future__ import annotations

from pathlib import Path

import pytest

from seecad.errors import InvalidDesignError
from seecad.models import (
    Box,
    DesignSpec,
    LibraryCall,
    NumberArgument,
    PositiveSolid,
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
    assert first.manifest["boolean_strategy"] == "single_negative_difference_pass"


def test_module_encoding_is_injective() -> None:
    spec = DesignSpec(
        name="IDs",
        intent="Distinct named modules.",
        units="mm",
        positive_solids=(
            PositiveSolid(id="foo-bar", name="A", shape=Box(size=Vec3(x=1, y=1, z=1))),
            PositiveSolid(id="foo_bar", name="B", shape=Box(size=Vec3(x=1, y=1, z=1))),
        ),
    )
    source = ScadGenerator().generate(spec).source
    assert "positive_id_foo_hbar" in source
    assert "positive_id_foo_ubar" in source


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
        positive_solids=(PositiveSolid(id="body", name="Body", shape=call),),
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
        positive_solids=(PositiveSolid(id="body", name="Body", shape=unsafe),),
    )
    with pytest.raises(InvalidDesignError):
        ScadGenerator(nopscad_root=Path("vendor/NopSCADlib")).generate(spec)


def test_nopscad_tree_digest_is_recomputed() -> None:
    provenance = _library_provenance(Path("vendor/NopSCADlib").resolve())
    assert provenance["tree_sha256"] == (
        "810daa212a1d6f17c489eb758926d57593020ba810e52eecbffbf445cd0cff53"
    )
