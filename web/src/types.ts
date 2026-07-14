export type EvidenceClass = "exact" | "bounded" | "heuristic" | "unavailable";
export type DiagnosticSeverity = "pass" | "caution" | "fail";
export type RevisionState = "draft" | "compiled" | "analyzed" | "approved";
export type ViewId = "iso" | "front" | "right" | "top" | "section" | "access";
export type ExportFormat = "spec" | "scad" | "stl" | "3mf" | "analysis";

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface Dimensions {
  x: number;
  y: number;
  z: number;
  unit: "mm";
}

export interface ConstraintSet {
  material: string;
  process: string;
  nozzleDiameter: number;
  layerHeight: number;
  minWall: number;
  minClearance: number;
  maxOverhang: number;
  buildVolume: Vec3;
  tolerance: number;
  infill: number;
  loadCase: string;
}

export interface ModelingOperation {
  id: string;
  phase: "positive" | "negative";
  label: string;
  primitive: string;
  detail: string;
  status: "complete" | "active" | "queued";
}

export interface Diagnostic {
  id: string;
  evidence: EvidenceClass;
  severity: DiagnosticSeverity;
  label: string;
  value: string;
  detail: string;
  source: string;
  location?: string;
}

export interface ArtifactRef {
  sha256: string;
  media_type?: string;
  size_bytes?: number;
  url?: string;
  filename?: string;
}

export interface Revision {
  id: string;
  parentId: string | null;
  createdAt: string;
  author: string;
  message: string;
  state: RevisionState;
  checksum: string;
  source: string;
  spec?: Record<string, unknown>;
  analysisProfile?: Record<string, unknown>;
  stlUrl?: string;
  dimensions: Dimensions | null;
  volumeCm3: number | null;
  massG: number | null;
  printMinutes: number | null;
  triangles: number | null;
  operations: ModelingOperation[];
  diagnostics: Diagnostic[];
  artifacts: Record<string, ArtifactRef>;
}

export interface Project {
  id: string;
  name: string;
  brief: string;
  activeRevisionId: string;
  constraints: ConstraintSet;
  revisions: Revision[];
}

export interface WorkbenchPayload {
  project: Project;
  source: "api" | "demo";
  apiMessage?: string;
}

export interface BackendRevisionResponse {
  design_id: string;
  revision_id: string;
  parent_revision_id?: string | null;
  created_at: string;
  spec?: Record<string, unknown>;
  artifacts?: Record<string, ArtifactRef>;
  metadata?: Record<string, unknown>;
}

export interface BackendHistoryResponse {
  design_id?: string;
  revisions?: BackendRevisionResponse[];
  latest_revision_id?: string;
  [key: string]: unknown;
}

export interface BackendAnalysisResponse {
  revision: BackendRevisionResponse;
  analysis: {
    schema_version?: string;
    mesh_sha256?: string;
    print_profile?: Record<string, unknown>;
    print_profile_sha256?: string;
    analyzed_at?: string;
    measurements?: Array<{
      name: string;
      value: number | boolean | number[] | null;
      unit?: string | null;
      confidence: EvidenceClass;
      basis: string;
    }>;
    findings?: Array<{
      code: string;
      severity: "info" | "warning" | "error";
      message: string;
      confidence: EvidenceClass;
      evidence?: Record<string, unknown>;
    }>;
    printable?: boolean | null;
    summary?: string;
  };
}

export interface BackendComparisonResponse {
  [key: string]: unknown;
}

export interface ConsoleEntry {
  id: string;
  time: string;
  level: "info" | "ok" | "warn" | "error";
  message: string;
}
