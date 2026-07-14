import { afterEach, describe, expect, it, vi } from "vitest";
import {
  canExportRevision,
  createDesign,
  mergeCompileResult,
  normalizeAnalysis,
  normalizeRevision,
  PLANNER_REQUEST_TIMEOUT_MS,
} from "./api";
import { defaultConstraints, demoProject } from "./demo";

afterEach(() => vi.restoreAllMocks());

describe("normalizeRevision", () => {
  it("maps the stable backend envelope into the workbench model", () => {
    const revision = normalizeRevision({
      design_id: "design-1",
      revision_id: "rev-7",
      parent_revision_id: "rev-6",
      created_at: "2026-07-13T12:00:00Z",
      artifacts: { stl: { sha256: "abc123", media_type: "model/stl" } },
      spec: {
        name: "Tool bracket",
        positive_solids: [
          {
            id: "body",
            name: "Body",
            purpose: "primary load path",
            shape: { kind: "box", size: { x: 10, y: 20, z: 30 } },
          },
        ],
        negative_features: [
          {
            id: "bore",
            name: "Bore",
            rationale: "cable passage",
            shape: { kind: "cylinder", radius: 2, height: 30 },
          },
        ],
      },
      metadata: {
        message: "Longer tool passages",
      },
    });

    expect(revision.id).toBe("rev-7");
    expect(revision.parentId).toBe("rev-6");
    expect(revision.dimensions).toBeNull();
    expect(revision.volumeCm3).toBeNull();
    expect(revision.operations.map((operation) => operation.phase)).toEqual([
      "positive",
      "negative",
    ]);
    expect(revision.source).toContain("unavailable");
    expect(revision.stlUrl).toContain("/v1/artifacts/abc123");
  });

  it("maps live mesh analysis without inserting demo measurements", () => {
    const base = normalizeRevision({
      design_id: "design-1",
      revision_id: "rev-7",
      created_at: "2026-07-13T12:00:00Z",
      spec: {},
      artifacts: {},
    });
    const revision = normalizeAnalysis(
      {
        revision: {
          design_id: "design-1",
          revision_id: "rev-8",
          parent_revision_id: "rev-7",
          created_at: "2026-07-13T12:01:00Z",
          spec: {},
          artifacts: { analysis: { sha256: "def456" } },
        },
        analysis: {
          print_profile: {
            process: "fdm",
            material: "PETG",
            minimum_wall: 2.4,
          },
          measurements: [
            {
              name: "bounds_extents",
              value: [10, 20, 30],
              unit: "mm",
              confidence: "exact",
              basis: "triangle bounds",
            },
            {
              name: "volume",
              value: 12_500,
              unit: "mm^3",
              confidence: "exact",
              basis: "watertight volume",
            },
            {
              name: "minimum_wall_thickness",
              value: null,
              unit: "mm",
              confidence: "unavailable",
              basis: "not solved",
            },
          ],
          findings: [],
        },
      },
      base,
    );

    expect(revision.dimensions).toEqual({ x: 10, y: 20, z: 30, unit: "mm" });
    expect(revision.volumeCm3).toBe(12.5);
    expect(revision.diagnostics.at(-1)?.evidence).toBe("unavailable");
    expect(revision.parentId).toBe("rev-7");
    expect(revision.analysisProfile?.minimum_wall).toBe(2.4);
  });
});

describe("workbench evidence contracts", () => {
  it("keeps the browser planner window above the 480 second backend budget", () => {
    expect(PLANNER_REQUEST_TIMEOUT_MS).toBe(540_000);
    expect(PLANNER_REQUEST_TIMEOUT_MS).toBeGreaterThan(480_000);
  });

  it("sends every editable manufacturing and load constraint as planner input", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          design_id: "dsgn_000000000000000000000000",
          revision_id: "rev_000000000000000000000000",
          created_at: "2026-07-13T12:00:00Z",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    const constraints = {
      ...defaultConstraints,
      material: "PA-CF · Polymaker",
      process: "FDM · 0.6 mm nozzle",
      nozzleDiameter: 0.6,
      layerHeight: 0.25,
      minWall: 2.2,
      minClearance: 0.4,
      maxOverhang: 42,
      buildVolume: { x: 350, y: 350, z: 400 },
      tolerance: 0.2,
      infill: 45,
      loadCase: "18 kg vertical static",
    };

    await createDesign("Make a bracket", constraints);
    const init = fetch.mock.calls[0][1];
    const payload = JSON.parse(String(init?.body)) as Record<string, unknown>;

    expect(payload.requested_profile).toEqual({
      process: "fdm",
      material: "PA-CF · Polymaker",
      nozzle_diameter: 0.6,
      layer_height: 0.25,
      minimum_wall: 2.2,
      minimum_clearance: 0.4,
      maximum_unsupported_overhang_degrees: 42,
      build_volume: { x: 350, y: 350, z: 400 },
    });
    expect(payload.load_case).toBe("18 kg vertical static");
    expect(payload.dimensional_tolerance).toBe(0.2);
    expect(payload.infill_percent).toBe(45);
  });

  it("only enables exports backed by artifacts on the active revision", () => {
    const revision = normalizeRevision({
      design_id: "design-1",
      revision_id: "rev-1",
      created_at: "2026-07-13T12:00:00Z",
      artifacts: {
        spec: { sha256: "a".repeat(64) },
        scad: { sha256: "b".repeat(64) },
      },
      spec: {},
    });

    expect(canExportRevision(revision, "spec")).toBe(true);
    expect(canExportRevision(revision, "scad")).toBe(true);
    expect(canExportRevision(revision, "stl")).toBe(false);
    expect(canExportRevision(revision, "analysis")).toBe(false);
  });

  it("keeps approved state and evidence across no-op compile and analysis calls", () => {
    const approvedPayload = {
      design_id: "design-1",
      revision_id: "rev-approved",
      parent_revision_id: "rev-analyzed",
      created_at: "2026-07-13T12:02:00Z",
      spec: {},
      artifacts: {
        stl: { sha256: "a".repeat(64) },
        analysis: { sha256: "b".repeat(64) },
        approval: { sha256: "c".repeat(64) },
      },
      metadata: { event: "approved" },
    };
    const base = {
      ...normalizeRevision(approvedPayload),
      source: "// approved source",
      dimensions: { x: 10, y: 20, z: 30, unit: "mm" as const },
      volumeCm3: 12.5,
      triangles: 240,
      diagnostics: [
        {
          id: "mesh-check",
          evidence: "exact" as const,
          severity: "pass" as const,
          label: "Watertight",
          value: "Yes",
          detail: "edge incidence",
          source: "analysis",
        },
      ],
    };

    const compiled = mergeCompileResult(approvedPayload, base);
    expect(compiled.state).toBe("approved");
    expect(compiled.diagnostics).toEqual(base.diagnostics);
    expect(compiled.dimensions).toEqual(base.dimensions);
    expect(compiled.artifacts.approval?.sha256).toBe("c".repeat(64));

    const analyzed = normalizeAnalysis(
      {
        revision: approvedPayload,
        analysis: {
          measurements: [
            {
              name: "watertight",
              value: true,
              confidence: "exact",
              basis: "edge incidence",
            },
          ],
          findings: [],
        },
      },
      base,
    );
    expect(analyzed.state).toBe("approved");
    expect(analyzed.diagnostics).toHaveLength(1);
    expect(analyzed.diagnostics[0].value).toBe("Yes");
    expect(analyzed.artifacts.approval?.sha256).toBe("c".repeat(64));

    const newAnalysisChild = normalizeAnalysis(
      {
        revision: {
          ...approvedPayload,
          revision_id: "rev-new-analysis",
          parent_revision_id: "rev-approved",
          metadata: { event: "analyzed" },
        },
        analysis: { measurements: [], findings: [] },
      },
      base,
    );
    expect(newAnalysisChild.state).toBe("analyzed");
  });

  it("keeps synthetic demo wall evidence unavailable and overhang heuristic", () => {
    const active = demoProject.revisions.find(
      (revision) => revision.id === demoProject.activeRevisionId,
    );
    const wall = active?.diagnostics.find(
      (diagnostic) => diagnostic.id === "dx-wall",
    );
    const overhang = active?.diagnostics.find(
      (diagnostic) => diagnostic.id === "dx-overhang",
    );

    expect(wall?.evidence).toBe("unavailable");
    expect(wall?.value).toBe("Not measured");
    expect(overhang?.evidence).toBe("heuristic");
  });
});
