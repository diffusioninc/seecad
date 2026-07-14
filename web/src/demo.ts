import type {
  ConstraintSet,
  Diagnostic,
  ModelingOperation,
  Project,
  Revision,
} from "./types";

export const DEMO_DESIGN_ID = "SC-042";

export const defaultConstraints: ConstraintSet = {
  material: "PETG · Prusament",
  process: "FDM · 0.4 mm nozzle",
  nozzleDiameter: 0.4,
  layerHeight: 0.2,
  minWall: 2.4,
  minClearance: 0.35,
  maxOverhang: 45,
  buildVolume: { x: 220, y: 220, z: 250 },
  tolerance: 0.2,
  infill: 35,
  loadCase: "18 kg static, vertical",
};

const operations: ModelingOperation[] = [
  {
    id: "op-01",
    phase: "positive",
    label: "Mounting envelope",
    primitive: "rounded_cuboid",
    detail: "84 × 56 × 8 mm datum body",
    status: "complete",
  },
  {
    id: "op-02",
    phase: "positive",
    label: "Cable boss",
    primitive: "rounded_cylinder",
    detail: "Ø28 × 14 mm, concentric to X/Y",
    status: "complete",
  },
  {
    id: "op-03",
    phase: "positive",
    label: "Load ribs",
    primitive: "hull × 4",
    detail: "2.8 mm radial gussets",
    status: "complete",
  },
  {
    id: "op-04",
    phase: "negative",
    label: "Cable passage",
    primitive: "teardrop_bore",
    detail: "Ø16.4 mm through, print-safe crown",
    status: "complete",
  },
  {
    id: "op-05",
    phase: "negative",
    label: "Fastener pattern",
    primitive: "polyhole × 4",
    detail: "M4 clearance, 68 × 40 mm pitch",
    status: "complete",
  },
  {
    id: "op-06",
    phase: "negative",
    label: "Driver corridors",
    primitive: "tool_access × 4",
    detail: "Ø11 × 32 mm approach cylinders",
    status: "complete",
  },
];

const diagnostics: Diagnostic[] = [
  {
    id: "dx-watertight",
    evidence: "exact",
    severity: "pass",
    label: "Closed mesh",
    value: "2-manifold",
    detail: "Every edge is shared by exactly two faces.",
    source: "CGAL mesh topology",
    location: "whole body",
  },
  {
    id: "dx-wall",
    evidence: "unavailable",
    severity: "caution",
    label: "Minimum wall",
    value: "Not measured",
    detail: "The demo does not include a volumetric wall-thickness solve.",
    source: "synthetic demo · measurement unavailable",
    location: "whole body",
  },
  {
    id: "dx-clearance",
    evidence: "exact",
    severity: "pass",
    label: "Hole allowance",
    value: "+0.40 mm",
    detail: "M4 polyholes include calibrated FDM allowance.",
    source: "nominal geometry",
    location: "4 mounting holes",
  },
  {
    id: "dx-overhang",
    evidence: "heuristic",
    severity: "pass",
    label: "Unsupported angle",
    value: "38.2°",
    detail: "Below the configured 45° support threshold.",
    source: "synthetic demo · face-normal heuristic",
    location: "boss underside",
  },
  {
    id: "dx-tool",
    evidence: "heuristic",
    severity: "pass",
    label: "Driver access",
    value: "4 / 4 clear",
    detail:
      "A 10 mm driver envelope reaches each fastener without intersecting the part.",
    source: "tool corridor simulation",
    location: "mounting pattern",
  },
  {
    id: "dx-load",
    evidence: "heuristic",
    severity: "caution",
    label: "Load path",
    value: "Review advised",
    detail:
      "Ribs appear continuous to the bolt pattern; deformation was not solved by FEA.",
    source: "geometry reasoning",
    location: "upper rib pair",
  },
  {
    id: "dx-assembly",
    evidence: "heuristic",
    severity: "pass",
    label: "Assembly order",
    value: "Unblocked",
    detail:
      "Cable can be routed before the four mounting fasteners are torqued.",
    source: "assembly sequence model",
    location: "cable passage",
  },
];

export const demoSource = `// SeeCAD generated · SC-042 / r07
// Strategy: establish all positive volume, then subtract all negative space.
include <NopSCADlib/core.scad>
include <NopSCADlib/utils/rounded_cylinder.scad>
include <NopSCADlib/utils/horiholes.scad>

$fn = 72;

module positive_volume() {
  union() {
    rounded_rectangle([84, 56, 8], 4, center = true);
    translate([0, 0, 8]) rounded_cylinder(r = 14, h = 14, r2 = 2);

    // Radial load ribs stay in the positive pass.
    for (a = [45, 135, 225, 315])
      rotate([0, 0, a])
        hull() {
          translate([12, 0, 5]) cube([18, 2.8, 10], center = true);
          translate([25, 0, 2]) cube([2, 2.8, 4], center = true);
        }
  }
}

module negative_space() {
  // Functional bore: teardrop crown avoids trapped support.
  translate([0, 0, -5]) teardrop_plus(r = 8.2, h = 28, center = false);

  // Fastener holes and deliberately long tool corridors.
  for (x = [-34, 34], y = [-20, 20]) {
    translate([x, y, -10]) poly_cylinder(r = 2.2, h = 30, center = false);
    translate([x, y, 4]) cylinder(d = 11, h = 32, center = false);
  }
}

difference() {
  positive_volume();
  negative_space();
}`;

function makeRevision(
  id: string,
  parentId: string | null,
  message: string,
  overrides: Partial<Revision> = {},
): Revision {
  return {
    id,
    parentId,
    createdAt:
      id === "r07" ? "2026-07-13T16:22:00-07:00" : "2026-07-13T15:40:00-07:00",
    author: id === "r07" ? "SeeCAD + human" : "SeeCAD",
    message,
    state: id === "r07" ? "analyzed" : "compiled",
    checksum: id === "r07" ? "7f29a6c" : id === "r06" ? "0b7d192" : "9ce340b",
    source: demoSource,
    dimensions: { x: 84, y: 56, z: id === "r05" ? 21 : 22, unit: "mm" },
    volumeCm3: id === "r07" ? 31.82 : id === "r06" ? 30.94 : 29.88,
    massG: id === "r07" ? 40.6 : id === "r06" ? 39.4 : 38.1,
    printMinutes: id === "r07" ? 104 : 99,
    triangles: 18432,
    operations,
    diagnostics,
    artifacts: {},
    ...overrides,
  };
}

export const demoProject: Project = {
  id: DEMO_DESIGN_ID,
  name: "Cable bulkhead bracket",
  brief:
    "Wall-mounted cable pass-through. Carry 18 kg static load, accept M4 hardware, and preserve straight driver access after the cable is routed.",
  activeRevisionId: "r07",
  constraints: defaultConstraints,
  revisions: [
    makeRevision("r07", "r06", "Lengthen driver corridors; lock positive body"),
    makeRevision("r06", "r05", "Add teardrop crown and calibrated polyholes"),
    makeRevision("r05", null, "Initial constrained volume"),
  ],
};
