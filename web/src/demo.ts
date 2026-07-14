import type {
  AssemblyComponentSummary,
  ConstraintSet,
  Diagnostic,
  ModelingOperation,
  Project,
  Revision,
} from "./types";

export const DEMO_DESIGN_ID = "SC-A01";

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
  loadCase: "Demonstration only · no rated load",
};

const components: AssemblyComponentSummary[] = [
  {
    id: "bridge-plate",
    name: "Bridge plate",
    kind: "part",
    quantity: 1,
    detail: "PETG · 80 × 70 × 4 mm",
  },
  {
    id: "e2020-rails",
    name: "E2020 extrusion",
    kind: "stock",
    quantity: 2,
    detail: "20 × 20 profile · 100 mm",
    libraryRef: "NopSCADlib E2020",
  },
  {
    id: "m4-cap-screws",
    name: "M4 cap screw + washer",
    kind: "fastener",
    quantity: 4,
    detail: "12 mm nominal length",
    libraryRef: "NopSCADlib M4_cap_screw",
  },
  {
    id: "m4-t-nuts",
    name: "M4 sliding T-nut",
    kind: "fastener",
    quantity: 4,
    detail: "Upper rail slot placement",
    libraryRef: "NopSCADlib M4_sliding_t_nut",
  },
];

const operations: ModelingOperation[] = [
  {
    id: "op-01",
    phase: "positive",
    label: "Bridge plate material",
    primitive: "rounded_rectangle",
    detail: "80 × 70 × 4 mm · R4 corners",
    status: "complete",
  },
  {
    id: "op-02",
    phase: "negative",
    label: "M4 clearance pattern",
    primitive: "poly_cylinder × 4",
    detail: "60 × 50 mm pitch · plate target only",
    status: "complete",
  },
];

const diagnostics: Diagnostic[] = [
  {
    id: "dx-watertight",
    evidence: "exact",
    severity: "pass",
    label: "Plate topology",
    value: "Watertight",
    detail: "The compiled plate mesh is watertight with consistent winding.",
    source: "OpenSCAD CGAL + Trimesh readback",
    location: "bridge plate mesh",
  },
  {
    id: "dx-envelope",
    evidence: "exact",
    severity: "pass",
    label: "Plate envelope",
    value: "80 × 70 × 4 mm",
    detail: "Exact bounds read from the compiled STL derivative.",
    source: "triangle bounds",
    location: "bridge plate mesh",
  },
  {
    id: "dx-scope",
    evidence: "exact",
    severity: "pass",
    label: "Negative ownership",
    value: "Plate only",
    detail:
      "All four clearance holes are collected in one named subtraction and do not cut the library hardware or rails.",
    source: "semantic source contract",
    location: "four M4 clearances",
  },
  {
    id: "dx-contact",
    evidence: "bounded",
    severity: "pass",
    label: "Rail bearing faces",
    value: "2 aligned",
    detail:
      "The nominal plate underside is coincident with both extrusion top faces.",
    source: "declared component transforms",
    location: "plate / rail interfaces",
  },
  {
    id: "dx-clearance",
    evidence: "bounded",
    severity: "pass",
    label: "Fastener alignment",
    value: "4 / 4 axes",
    detail:
      "The four clearance axes share the two upper extrusion-slot centrelines at Y ±25 mm.",
    source: "nominal feature coordinates",
    location: "clamping pattern",
  },
  {
    id: "dx-overhang",
    evidence: "heuristic",
    severity: "pass",
    label: "Plate orientation",
    value: "Broad face down",
    detail:
      "The print-layout selector places the bridge plate on its broad face; slicer review is still required.",
    source: "reference print-layout orientation",
    location: "bridge plate",
  },
  {
    id: "dx-wall",
    evidence: "unavailable",
    severity: "caution",
    label: "Minimum wall",
    value: "Not measured",
    detail: "No volumetric minimum-wall solve was run for this fixture.",
    source: "measurement unavailable",
    location: "bridge plate",
  },
  {
    id: "dx-fit",
    evidence: "unavailable",
    severity: "caution",
    label: "Physical engagement",
    value: "Bench test required",
    detail:
      "T-nut fit, thread engagement, preload, load transfer, and structural integrity are not established.",
    source: "solver boundary",
    location: "four clamping stacks",
  },
];

export const demoSource = `// SeeCAD reference fixture · SC-A01 / r03
// Units: millimetres. Semantic authority: intent.json.
include <NopSCADlib/core.scad>
include <NopSCADlib/vitamins/extrusions.scad>
include <NopSCADlib/vitamins/screws.scad>

unit_system = "millimetres";
rail_type = E2020;
rail_length = 100;
rail_spacing = 50;
plate_size = [80, 70, 4];
fastener_type = M4_cap_screw;
rail_nut_type = M4_sliding_t_nut;

module at_fastener_positions() {
  for (x = [-30, 30], y = [-25, 25])
    translate([x, y, 0]) children();
}

module positive_volume() {
  rounded_rectangle(plate_size, 4, center = false, xy_center = true);
}

module negative_space() {
  at_fastener_positions()
    translate([0, 0, -2])
      poly_cylinder(r = screw_clearance_radius(fastener_type), h = 8);
}

module bridge_plate() {
  difference() {
    positive_volume();
    negative_space();
  }
}

module assembly() {
  for (y = [-25, 25])
    translate([0, y, 10]) rotate([0, 90, 0])
      extrusion(rail_type, rail_length, center = true);

  at_fastener_positions() translate([0, 0, 20])
    sliding_t_nut(rail_nut_type);

  color("DodgerBlue") translate([0, 0, 20]) bridge_plate();

  at_fastener_positions() translate([0, 0, 24])
    screw_and_washer(fastener_type, 12);
}

assembly();`;

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
      id === "r03" ? "2026-07-13T22:32:00-07:00" : "2026-07-13T22:18:00-07:00",
    author: id === "r03" ? "SeeCAD + human" : "SeeCAD",
    message,
    state: id === "r03" ? "analyzed" : "compiled",
    checksum:
      id === "r03" ? "22a1f0b8" : id === "r02" ? "183cbad4" : "a2190d31",
    source: demoSource,
    dimensions: { x: 100, y: 70, z: id === "r01" ? 20 : 24, unit: "mm" },
    volumeCm3: id === "r03" ? 22.091 : id === "r02" ? 22.091 : 0,
    massG: id === "r03" ? 28.1 : id === "r02" ? 28.1 : 0,
    printMinutes: id === "r03" ? 74 : id === "r02" ? 74 : 0,
    triangles: id === "r01" ? null : 412,
    components,
    operations,
    diagnostics,
    artifacts: {},
    ...overrides,
  };
}

export const demoProject: Project = {
  id: DEMO_DESIGN_ID,
  name: "Two-rail bridge assembly",
  brief:
    "Fasten one printable bridge plate across two parallel E2020 rails with four M4 screw, washer, and sliding T-nut stacks.",
  activeRevisionId: "r03",
  constraints: defaultConstraints,
  revisions: [
    makeRevision("r03", "r02", "Verify plate mesh and label solver boundaries"),
    makeRevision(
      "r02",
      "r01",
      "Add bridge plate and scoped M4 clearance pattern",
    ),
    makeRevision("r01", null, "Place two 100 mm E2020 datum rails"),
  ],
};
