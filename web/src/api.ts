import { demoProject, defaultConstraints, DEMO_DESIGN_ID } from "./demo";
import type {
  AssemblyComponentSummary,
  ArtifactRef,
  BackendAnalysisResponse,
  BackendComparisonResponse,
  BackendHistoryResponse,
  BackendRevisionResponse,
  ConstraintSet,
  Diagnostic,
  EvidenceClass,
  ExportFormat,
  ModelingOperation,
  Project,
  Revision,
  WorkbenchPayload,
} from "./types";

const API_ROOT = (
  import.meta.env.VITE_API_URL ??
  import.meta.env.VITE_API_BASE_URL ??
  ""
).replace(/\/$/, "");
const PREFIX = `${API_ROOT}/v1`;
const allowDemoFallback = import.meta.env.VITE_DEMO_FALLBACK !== "false";
export const DESIGN_ID_PATTERN = /^dsgn_[a-f0-9]{24}$/;
export const PLANNER_REQUEST_TIMEOUT_MS = 540_000;
const SOURCE_PENDING =
  "// OpenSCAD source is stored as an immutable artifact.\n// Source preview is unavailable for this revision; use Export → SCAD to retrieve it.";

export function initialDesignId(): string {
  const selected = new URL(window.location.href).searchParams.get("design");
  if (selected && DESIGN_ID_PATTERN.test(selected)) return selected;
  const configured = import.meta.env.VITE_DESIGN_ID;
  if (configured && DESIGN_ID_PATTERN.test(configured)) return configured;
  return DEMO_DESIGN_ID;
}

export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 12_000,
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${PREFIX}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
    if (!response.ok) {
      const rawBody = await response.text();
      let body: unknown = rawBody;
      try {
        body = JSON.parse(rawBody) as unknown;
      } catch {
        /* Keep non-JSON error text. */
      }
      const message =
        typeof body === "object" && body && "error" in body
          ? String(
              (body as { error?: { message?: string } }).error?.message ??
                response.statusText,
            )
          : response.statusText;
      throw new ApiError(
        message || `Request failed (${response.status})`,
        response.status,
        body,
      );
    }
    return (await response.json()) as T;
  } finally {
    window.clearTimeout(timeout);
  }
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
}

function finite(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function finiteOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function text(value: unknown, fallback: string): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function evidence(value: unknown): EvidenceClass {
  return value === "bounded" || value === "heuristic" || value === "unavailable"
    ? value
    : "exact";
}

function artifactUrl(
  artifacts: Record<string, ArtifactRef>,
  role: string,
): string | undefined {
  const artifact = artifacts[role];
  if (!artifact) return undefined;
  if (artifact.url)
    return artifact.url.startsWith("http")
      ? artifact.url
      : `${API_ROOT}${artifact.url}`;
  if (artifact.sha256) return `${PREFIX}/artifacts/${artifact.sha256}`;
  return undefined;
}

function primitiveDetail(shapeValue: unknown): string {
  const shape = record(shapeValue);
  const kind = text(shape.kind, "primitive");
  if (kind === "box" || kind === "rounded_box") {
    const size = record(shape.size);
    return `${finite(size.x, 0)} × ${finite(size.y, 0)} × ${finite(size.z, 0)} mm`;
  }
  if (kind === "cylinder")
    return `Ø${(finite(shape.radius, 0) * 2).toFixed(1)} × ${finite(shape.height, 0)} mm`;
  if (kind === "library_call")
    return `${text(shape.module, "module")} · NopSCADlib`;
  return kind.replaceAll("_", " ");
}

function operationsFromSpec(specValue: unknown): ModelingOperation[] {
  const spec = record(specValue);
  const positive = Array.isArray(spec.positive_solids)
    ? spec.positive_solids
    : [];
  const negative = Array.isArray(spec.negative_features)
    ? spec.negative_features
    : [];
  const channels = Array.isArray(spec.tool_access_channels)
    ? spec.tool_access_channels
    : [];
  return [
    ...positive.map((value, index): ModelingOperation => {
      const solid = record(value);
      const shape = record(solid.shape);
      return {
        id: text(solid.id, `positive-${index}`),
        phase: "positive",
        label: text(solid.name, `Positive solid ${index + 1}`),
        primitive: text(shape.kind, "primitive"),
        detail: text(solid.purpose, primitiveDetail(shape)),
        status: "complete",
      };
    }),
    ...negative.map((value, index): ModelingOperation => {
      const feature = record(value);
      const shape = record(feature.shape);
      return {
        id: text(feature.id, `negative-${index}`),
        phase: "negative",
        label: text(feature.name, `Negative feature ${index + 1}`),
        primitive: text(shape.kind, "primitive"),
        detail: text(feature.rationale, primitiveDetail(shape)),
        status: "complete",
      };
    }),
    ...channels.map((value, index): ModelingOperation => {
      const channel = record(value);
      const diameter =
        finite(channel.tool_diameter, 0) +
        finite(channel.radial_clearance, 0) * 2;
      return {
        id: text(channel.id, `access-${index}`),
        phase: "negative",
        label: text(channel.name, `Tool corridor ${index + 1}`),
        primitive: "tool_access",
        detail: `${text(channel.tool, "tool")} · Ø${diameter.toFixed(1)} mm clear passage`,
        status: "complete",
      };
    }),
  ];
}

function componentsFromSpec(specValue: unknown): AssemblyComponentSummary[] {
  const spec = record(specValue);
  const components = Array.isArray(spec.components) ? spec.components : [];
  return components.map((value, index) => {
    const component = record(value);
    const kind = component.kind;
    const safeKind: AssemblyComponentSummary["kind"] =
      kind === "stock" || kind === "connector" || kind === "fastener"
        ? kind
        : "part";
    return {
      id: text(component.id, `component-${index}`),
      name: text(component.name, `Component ${index + 1}`),
      kind: safeKind,
      quantity: 1,
      detail: text(component.purpose, "No component purpose recorded"),
    };
  });
}

function constraintsFromSpec(specValue: unknown): ConstraintSet {
  const spec = record(specValue);
  const profile = record(spec.print_profile);
  const process = text(profile.process, "fdm").toUpperCase();
  const nozzle = finite(
    profile.nozzle_diameter,
    defaultConstraints.nozzleDiameter,
  );
  return {
    ...defaultConstraints,
    material: text(profile.material, defaultConstraints.material),
    process: `${process} · ${nozzle.toFixed(1)} mm nozzle`,
    nozzleDiameter: nozzle,
    layerHeight: finite(profile.layer_height, defaultConstraints.layerHeight),
    minWall: finite(profile.minimum_wall, defaultConstraints.minWall),
    minClearance: finite(
      profile.minimum_clearance,
      defaultConstraints.minClearance,
    ),
    maxOverhang: finite(
      profile.maximum_unsupported_overhang_degrees,
      defaultConstraints.maxOverhang,
    ),
    buildVolume: {
      x: finite(
        record(profile.build_volume).x,
        defaultConstraints.buildVolume.x,
      ),
      y: finite(
        record(profile.build_volume).y,
        defaultConstraints.buildVolume.y,
      ),
      z: finite(
        record(profile.build_volume).z,
        defaultConstraints.buildVolume.z,
      ),
    },
  };
}

export function requestedProfileFromConstraints(constraints: ConstraintSet) {
  const process = constraints.process.toLowerCase().startsWith("sla")
    ? "sla"
    : constraints.process.toLowerCase().startsWith("sls")
      ? "sls"
      : constraints.process.toLowerCase().startsWith("fdm")
        ? "fdm"
        : "unknown";
  return {
    process,
    material: constraints.material,
    nozzle_diameter: constraints.nozzleDiameter,
    layer_height: constraints.layerHeight,
    minimum_wall: constraints.minWall,
    minimum_clearance: constraints.minClearance,
    maximum_unsupported_overhang_degrees: constraints.maxOverhang,
    build_volume: constraints.buildVolume,
  };
}

function stateFrom(payload: BackendRevisionResponse): Revision["state"] {
  const metadata = record(payload.metadata);
  const event = metadata.event;
  if (metadata.approved === true || event === "approved") return "approved";
  if (payload.artifacts?.analysis || event === "analyzed") return "analyzed";
  if (
    payload.artifacts?.stl ||
    payload.artifacts?.["3mf"] ||
    event === "compiled"
  )
    return "compiled";
  return "draft";
}

export function normalizeRevision(
  payload: BackendRevisionResponse,
  index = 0,
): Revision {
  const metadata = record(payload.metadata);
  const artifacts = payload.artifacts ?? {};
  const digest =
    artifacts.analysis?.sha256 ??
    artifacts.stl?.sha256 ??
    artifacts.scad?.sha256 ??
    artifacts.spec?.sha256;
  return {
    id: payload.revision_id,
    parentId: payload.parent_revision_id ?? null,
    createdAt: payload.created_at,
    author: text(metadata.author, "SeeCAD"),
    message: text(
      metadata.message,
      text(
        metadata.event,
        index === 0 ? "Latest generated revision" : "Generated revision",
      ),
    ),
    state: stateFrom(payload),
    checksum: digest?.slice(0, 8) ?? payload.revision_id.slice(-8),
    source: SOURCE_PENDING,
    spec: payload.spec,
    stlUrl: artifactUrl(artifacts, "stl"),
    dimensions: null,
    volumeCm3: null,
    massG: null,
    printMinutes: null,
    triangles: null,
    components: componentsFromSpec(payload.spec),
    operations: operationsFromSpec(payload.spec),
    diagnostics: [],
    artifacts,
  };
}

export function mergeCompileResult(
  response: BackendRevisionResponse,
  base: Revision,
): Revision {
  const revision = normalizeRevision(response);
  return {
    ...revision,
    source: base.source,
    analysisProfile: base.analysisProfile,
    dimensions: base.dimensions,
    volumeCm3: base.volumeCm3,
    massG: base.massG,
    printMinutes: base.printMinutes,
    triangles: base.triangles,
    diagnostics: base.diagnostics,
  };
}

function measurementValue(
  value: number | boolean | number[] | null,
  unit?: string | null,
): string {
  if (value === null) return "Not measured";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value))
    return `${value.map((part) => Number(part.toFixed(2))).join(" × ")}${unit ? ` ${unit}` : ""}`;
  const rendered = Number.isInteger(value)
    ? String(value)
    : String(Number(value.toFixed(4)));
  return `${rendered}${unit ? ` ${unit}` : ""}`;
}

const measurementLabels: Record<string, string> = {
  bounds_extents: "Mesh envelope",
  surface_area: "Surface area",
  volume: "Closed volume",
  watertight: "Watertight topology",
  winding_consistent: "Face winding",
  connected_components: "Connected bodies",
  triangle_count: "Triangle count",
  vertex_count: "Vertex count",
  degenerate_triangle_count: "Degenerate triangles",
  fits_configured_build_volume_current_orientation: "Build-volume fit",
  downward_overhang_area_ratio: "Downward area ratio",
  minimum_wall_thickness: "Minimum wall",
};

function measurementSeverity(
  name: string,
  value: number | boolean | number[] | null,
  confidence: EvidenceClass,
): Diagnostic["severity"] {
  if (confidence === "unavailable" || value === null) return "caution";
  if (
    name === "watertight" ||
    name === "winding_consistent" ||
    name === "fits_configured_build_volume_current_orientation"
  )
    return value === true ? "pass" : "fail";
  if (name === "connected_components") return value === 1 ? "pass" : "caution";
  if (name === "degenerate_triangle_count")
    return value === 0 ? "pass" : "caution";
  if (name === "downward_overhang_area_ratio" && typeof value === "number")
    return value > 0.02 ? "caution" : "pass";
  return "pass";
}

export function normalizeAnalysis(
  response: BackendAnalysisResponse,
  base?: Revision,
): Revision {
  const revision = normalizeRevision(response.revision);
  const measurements = response.analysis.measurements ?? [];
  const findings = response.analysis.findings ?? [];
  const bounds = measurements.find(
    (measurement) => measurement.name === "bounds_extents",
  )?.value;
  const volume = measurements.find(
    (measurement) => measurement.name === "volume",
  )?.value;
  const triangleCount = measurements.find(
    (measurement) => measurement.name === "triangle_count",
  )?.value;
  const diagnostics: Diagnostic[] = [
    ...measurements.map((measurement): Diagnostic => {
      const confidence = evidence(measurement.confidence);
      return {
        id: `measurement-${measurement.name}`,
        evidence: confidence,
        severity: measurementSeverity(
          measurement.name,
          measurement.value,
          confidence,
        ),
        label:
          measurementLabels[measurement.name] ??
          measurement.name.replaceAll("_", " "),
        value: measurementValue(measurement.value, measurement.unit),
        detail: measurement.basis,
        source: "compiled mesh measurement",
        location: "current mesh",
      };
    }),
    ...findings.map((finding, index): Diagnostic => ({
      id: `finding-${finding.code}-${index}`,
      evidence: evidence(finding.confidence),
      severity:
        finding.severity === "error"
          ? "fail"
          : finding.severity === "warning" ||
              finding.confidence === "unavailable"
            ? "caution"
            : "pass",
      label: finding.code.replaceAll("_", " "),
      value:
        finding.severity === "error"
          ? "Blocking"
          : finding.severity === "warning"
            ? "Review"
            : "Recorded",
      detail: finding.message,
      source: Object.keys(finding.evidence ?? {}).length
        ? `mesh evidence · ${JSON.stringify(finding.evidence)}`
        : "mesh analysis finding",
      location: "current mesh",
    })),
  ];
  return {
    ...revision,
    source: base?.source ?? revision.source,
    analysisProfile: response.analysis.print_profile ?? base?.analysisProfile,
    dimensions:
      Array.isArray(bounds) && bounds.length >= 3
        ? {
            x: Number(bounds[0]),
            y: Number(bounds[1]),
            z: Number(bounds[2]),
            unit: "mm",
          }
        : (base?.dimensions ?? null),
    volumeCm3:
      typeof volume === "number" ? volume / 1000 : (base?.volumeCm3 ?? null),
    massG: base?.massG ?? null,
    printMinutes: base?.printMinutes ?? null,
    triangles:
      typeof triangleCount === "number"
        ? triangleCount
        : (base?.triangles ?? null),
    diagnostics,
    state: revision.state === "approved" ? "approved" : "analyzed",
  };
}

async function readArtifact(
  artifact: ArtifactRef | undefined,
  asJson: false,
): Promise<string | null>;
async function readArtifact(
  artifact: ArtifactRef | undefined,
  asJson: true,
): Promise<unknown | null>;
async function readArtifact(
  artifact: ArtifactRef | undefined,
  asJson: boolean,
): Promise<unknown | string | null> {
  if (!artifact?.sha256 && !artifact?.url) return null;
  const url = artifact.url
    ? artifact.url.startsWith("http")
      ? artifact.url
      : `${API_ROOT}${artifact.url}`
    : `${PREFIX}/artifacts/${artifact.sha256}`;
  try {
    const response = await fetch(url, {
      headers: { Accept: asJson ? "application/json" : "text/plain" },
    });
    if (!response.ok) return null;
    return asJson ? await response.json() : await response.text();
  } catch {
    return null;
  }
}

async function normalizeHistory(
  payload: BackendHistoryResponse,
  designId: string,
): Promise<Project> {
  const rawRevisions = Array.isArray(payload.revisions)
    ? [...payload.revisions].sort(
        (left, right) =>
          Date.parse(right.created_at) - Date.parse(left.created_at),
      )
    : [];
  if (rawRevisions.length === 0)
    throw new ApiError("Design has no revisions", 404, payload);

  const revisions = await Promise.all(
    rawRevisions.map(async (raw, index) => {
      let revision = normalizeRevision(raw, index);
      const [source, analysis] = await Promise.all([
        readArtifact(raw.artifacts?.scad, false),
        readArtifact(raw.artifacts?.analysis, true),
      ]);
      if (source) revision = { ...revision, source };
      if (analysis)
        revision = normalizeAnalysis(
          {
            revision: raw,
            analysis: record(analysis) as BackendAnalysisResponse["analysis"],
          },
          revision,
        );
      return revision;
    }),
  );

  const latestRaw = rawRevisions[0];
  const latestSpec = record(latestRaw.spec);
  const latestConstraintSource = revisions[0].analysisProfile
    ? { print_profile: revisions[0].analysisProfile }
    : latestSpec;
  return {
    id: text(payload.design_id, designId),
    name: text(latestSpec.name, "Generated mechanical part"),
    brief: text(
      latestSpec.intent,
      "No design intent was recorded for this revision.",
    ),
    activeRevisionId: revisions[0].id,
    constraints: constraintsFromSpec(latestConstraintSource),
    revisions,
  };
}

export async function loadWorkbench(
  designId = initialDesignId(),
): Promise<WorkbenchPayload> {
  try {
    const payload = await request<BackendHistoryResponse>(
      `/designs/${encodeURIComponent(designId)}`,
    );
    return {
      project: await normalizeHistory(payload, designId),
      source: "api",
    };
  } catch (error) {
    if (!allowDemoFallback) throw error;
    const message = error instanceof Error ? error.message : "API unavailable";
    return {
      project: structuredClone(demoProject),
      source: "demo",
      apiMessage: message,
    };
  }
}

export async function createDesign(
  prompt: string,
  constraints: ConstraintSet,
): Promise<BackendRevisionResponse> {
  return request(
    "/designs",
    {
      method: "POST",
      body: JSON.stringify({
        prompt,
        requested_profile: requestedProfileFromConstraints(constraints),
        load_case: constraints.loadCase,
        dimensional_tolerance: constraints.tolerance,
        infill_percent: constraints.infill,
        metadata: { surface: "seecad-workbench" },
      }),
    },
    PLANNER_REQUEST_TIMEOUT_MS,
  );
}

export async function createRevision(
  designId: string,
  parentRevisionId: string,
  prompt: string,
  constraints: ConstraintSet,
): Promise<BackendRevisionResponse> {
  return request(
    `/designs/${encodeURIComponent(designId)}/revisions`,
    {
      method: "POST",
      body: JSON.stringify({
        parent_revision_id: parentRevisionId,
        prompt,
        requested_profile: requestedProfileFromConstraints(constraints),
        load_case: constraints.loadCase,
        dimensional_tolerance: constraints.tolerance,
        infill_percent: constraints.infill,
        metadata: { surface: "seecad-workbench" },
      }),
    },
    PLANNER_REQUEST_TIMEOUT_MS,
  );
}

export async function createSpecRevision(
  designId: string,
  parentRevisionId: string,
  spec: Record<string, unknown>,
  metadata: Record<string, unknown>,
): Promise<BackendRevisionResponse> {
  return request(
    `/designs/${encodeURIComponent(designId)}/revisions`,
    {
      method: "POST",
      body: JSON.stringify({
        parent_revision_id: parentRevisionId,
        spec,
        metadata: { surface: "seecad-workbench", ...metadata },
      }),
    },
    30_000,
  );
}

export async function compileRevision(
  designId: string,
  revisionId: string,
  format: "stl" | "3mf" = "stl",
): Promise<BackendRevisionResponse> {
  return request(
    `/designs/${encodeURIComponent(designId)}/revisions/${encodeURIComponent(revisionId)}/compile`,
    {
      method: "POST",
      body: JSON.stringify({ format }),
    },
    180_000,
  );
}

export async function analyzeRevision(
  designId: string,
  revisionId: string,
  constraints: ConstraintSet,
): Promise<BackendAnalysisResponse> {
  return request(
    `/designs/${encodeURIComponent(designId)}/revisions/${encodeURIComponent(revisionId)}/analyze`,
    {
      method: "POST",
      body: JSON.stringify({
        auto_compile: true,
        profile: requestedProfileFromConstraints(constraints),
      }),
    },
    180_000,
  );
}

export async function approveRevision(
  designId: string,
  revisionId: string,
): Promise<BackendRevisionResponse> {
  return request(
    `/designs/${encodeURIComponent(designId)}/revisions/${encodeURIComponent(revisionId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({
        attestor: "Human reviewer",
        statement:
          "Reviewed the exact compiled mesh and analysis evidence for this revision.",
      }),
    },
    30_000,
  );
}

export async function compareRevisions(
  leftRevisionId: string,
  rightRevisionId: string,
): Promise<BackendComparisonResponse> {
  return request("/compare", {
    method: "POST",
    body: JSON.stringify({
      left_revision_id: leftRevisionId,
      right_revision_id: rightRevisionId,
    }),
  });
}

export function exportUrl(
  designId: string,
  revisionId: string,
  format: ExportFormat,
): string {
  return `${PREFIX}/designs/${encodeURIComponent(designId)}/revisions/${encodeURIComponent(revisionId)}/export?format=${format}`;
}

export function canExportRevision(
  revision: Revision,
  format: ExportFormat,
): boolean {
  const role = format === "spec" ? "spec" : format;
  return Boolean(revision.artifacts[role]);
}

export async function downloadExport(
  designId: string,
  revision: Revision,
  format: ExportFormat,
): Promise<void> {
  if (!canExportRevision(revision, format))
    throw new ApiError(
      `${format.toUpperCase()} is not present on the active revision`,
      409,
    );
  window.open(
    exportUrl(designId, revision.id, format),
    "_blank",
    "noopener,noreferrer",
  );
}
