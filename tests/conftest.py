from __future__ import annotations

from pathlib import Path

import pytest

from seecad.config import Settings
from seecad.models import (
    Box,
    Cylinder,
    DesignSpec,
    NegativeFeature,
    NegativeIntent,
    PositiveSolid,
    ToolAccessChannel,
    Transform,
    Vec3,
)


@pytest.fixture
def simple_spec() -> DesignSpec:
    return DesignSpec(
        name="Fixture bracket",
        intent="A block with a through hole and a deliberately long tool path.",
        units="mm",
        positive_solids=(
            PositiveSolid(
                id="main-body",
                name="Main body",
                shape=Box(size=Vec3(x=20, y=12, z=8)),
            ),
        ),
        negative_features=(
            NegativeFeature(
                id="mount_hole",
                name="Mount hole",
                shape=Cylinder(radius=2, height=12),
                transform=Transform(translate=Vec3(x=10, y=6, z=-2)),
                intent=NegativeIntent.THROUGH_HOLE,
                rationale="Fastener clearance.",
            ),
        ),
        tool_access_channels=(
            ToolAccessChannel(
                id="driver-access",
                name="Driver access",
                start=Vec3(x=-3, y=6, z=4),
                end=Vec3(x=23, y=6, z=4),
                tool_diameter=3,
                endpoint_overtravel=2,
                tool="3 mm driver",
                rationale="Keeps tool reach independent of wall edits.",
            ),
        ),
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "index.sqlite3",
        openscad_mode="docker",
        openscad_binary="definitely-not-installed-openscad",
        nopscad_root=Path("vendor/NopSCADlib"),
    )
