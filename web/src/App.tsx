import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BadgeCheck,
  Box,
  Braces,
  Check,
  ChevronDown,
  CircleDashed,
  Code2,
  Download,
  FileBox,
  FolderOpen,
  GitCompareArrows,
  HelpCircle,
  Menu,
  PanelBottomOpen,
  Play,
  Plus,
  RotateCcw,
  ScanLine,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  analyzeRevision,
  approveRevision,
  canExportRevision,
  compileRevision,
  createDesign,
  createRevision,
  createSpecRevision,
  DESIGN_ID_PATTERN,
  downloadExport,
  initialDesignId,
  loadWorkbench,
  mergeCompileResult,
  normalizeAnalysis,
  normalizeRevision,
} from "./api";
import { AssemblyPanel } from "./components/AssemblyPanel";
import { ConstraintsPanel } from "./components/ConstraintsPanel";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { PhaseTimeline } from "./components/PhaseTimeline";
import { RevisionsPanel } from "./components/RevisionsPanel";
import { SourceDrawer } from "./components/SourceDrawer";
import type {
  ConsoleEntry,
  ConstraintSet,
  ExportFormat,
  Revision,
  WorkbenchPayload,
} from "./types";

const VisionRig = lazy(() =>
  import("./components/VisionRig").then((module) => ({
    default: module.VisionRig,
  })),
);

const initialConsole: ConsoleEntry[] = [
  {
    id: "log-1",
    time: "—",
    level: "info",
    message: "No engine actions have been run in this browser session.",
  },
];

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function now(): string {
  return new Date().toLocaleTimeString([], {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function nextRevisionId(revisions: Revision[]): string {
  const next =
    Math.max(
      ...revisions.map(
        (revision) => Number(revision.id.replace(/\D/g, "")) || 0,
      ),
    ) + 1;
  return `r${String(next).padStart(2, "0")}`;
}

function Metric({
  label,
  value,
  unit,
  delta,
}: {
  label: string;
  value: string | number;
  unit?: string;
  delta?: string;
}) {
  return (
    <div className="metric">
      <dt>{label}</dt>
      <dd>
        {value}
        <span>{unit}</span>
      </dd>
      {delta && <small>{delta}</small>}
    </div>
  );
}

function LoadingWorkbench() {
  return (
    <main className="loading-workbench">
      <div className="loading-mark">
        <ScanLine size={30} />
      </div>
      <strong>Calibrating vision rig</strong>
      <span>Reading the current design and compiled artifacts…</span>
      <div className="loading-rule">
        <i />
      </div>
    </main>
  );
}

function ShortcutHelp({ onClose }: { onClose: () => void }) {
  const shortcuts = [
    ["1—6", "Select inspection view"],
    ["E", "Toggle fitted / exploded assembly"],
    ["V", "Run manufacturability analysis"],
    ["C", "Toggle revision overlay"],
    ["`", "Open source and console"],
    ["Esc", "Close drawer or this guide"],
  ];
  return (
    <div className="modal-scrim" role="presentation" onMouseDown={onClose}>
      <section
        className="shortcut-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcut-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span className="eyebrow">Workbench controls</span>
            <h2 id="shortcut-title">Keyboard map</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close keyboard map"
          >
            <X size={16} />
          </button>
        </header>
        <dl>
          {shortcuts.map(([key, action]) => (
            <div key={key}>
              <dt>
                <kbd>{key}</kbd>
              </dt>
              <dd>{action}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

function OpenDesignDialog({
  currentId,
  creating,
  onClose,
  onOpen,
  onCreate,
}: {
  currentId: string;
  creating: boolean;
  onClose: () => void;
  onOpen: (id: string) => void;
  onCreate: (prompt: string) => void;
}) {
  const [designId, setDesignId] = useState(
    DESIGN_ID_PATTERN.test(currentId) ? currentId : "",
  );
  const [prompt, setPrompt] = useState(
    "Design a small bridge plate assembly across two parallel E2020 rails with four accessible M4 clamping stacks.",
  );
  const validId = DESIGN_ID_PATTERN.test(designId);
  return (
    <div className="modal-scrim" role="presentation" onMouseDown={onClose}>
      <section
        className="open-design-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="open-design-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span className="eyebrow">Persistent engine history</span>
            <h2 id="open-design-title">Open or create a design</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close design picker"
          >
            <X size={16} />
          </button>
        </header>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (validId) onOpen(designId);
          }}
        >
          <label className="text-field">
            <span>Design ID</span>
            <input
              value={designId}
              placeholder="dsgn_000000000000000000000000"
              onChange={(event) =>
                setDesignId(event.currentTarget.value.trim())
              }
            />
          </label>
          <button type="submit" disabled={!validId}>
            <FolderOpen size={14} />
            Open design
          </button>
        </form>
        <div className="modal-divider">
          <span>or begin a new history</span>
        </div>
        <div className="new-design-form">
          <label>
            <span>Design intent</span>
            <textarea
              rows={4}
              value={prompt}
              onChange={(event) => setPrompt(event.currentTarget.value)}
            />
          </label>
          <button
            type="button"
            disabled={!prompt.trim() || creating}
            onClick={() => onCreate(prompt)}
          >
            {creating ? (
              <CircleDashed className="spin" size={14} />
            ) : (
              <Plus size={14} />
            )}
            {creating ? "Planning design…" : "Create design"}
          </button>
          <small>
            Planning can take several minutes. Closing this window does not
            cancel work already accepted by the engine.
          </small>
        </div>
      </section>
    </div>
  );
}

export default function App() {
  const queryClient = useQueryClient();
  const revisionInputRef = useRef<HTMLTextAreaElement>(null);
  const [designId, setDesignId] = useState(initialDesignId);
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["workbench", designId],
    queryFn: () => loadWorkbench(designId),
    staleTime: 20_000,
    retry: false,
  });

  const [constraints, setConstraints] = useState<ConstraintSet | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [baselineId, setBaselineId] = useState("");
  const [revisionPrompt, setRevisionPrompt] = useState(
    "Increase the bridge plate corner radius to 6 mm without moving the four M4 clearance axes.",
  );
  const [consoleEntries, setConsoleEntries] =
    useState<ConsoleEntry[]>(initialConsole);
  const [toast, setToast] = useState<{
    tone: "ok" | "warn";
    message: string;
  } | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [designPickerOpen, setDesignPickerOpen] = useState(false);
  const [mobileRail, setMobileRail] = useState<"brief" | "review" | null>(null);

  const project = data?.project;
  const activeRevision =
    project?.revisions.find(
      (revision) => revision.id === project.activeRevisionId,
    ) ?? project?.revisions[0];
  const baseline =
    project?.revisions.find((revision) => revision.id === baselineId) ??
    project?.revisions[1] ??
    project?.revisions[0];
  const currentConstraints = constraints ?? project?.constraints;

  const selectDesign = (nextId: string, replace = false) => {
    if (!DESIGN_ID_PATTERN.test(nextId)) return;
    const url = new URL(window.location.href);
    url.searchParams.set("design", nextId);
    window.history[replace ? "replaceState" : "pushState"](null, "", url);
    setConstraints(null);
    setBaselineId("");
    setComparing(false);
    setDesignId(nextId);
    setDesignPickerOpen(false);
  };

  useEffect(() => {
    const onPopState = () => {
      const nextId = initialDesignId();
      setConstraints(null);
      setBaselineId("");
      setDesignId(nextId);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (project && constraints === null) setConstraints(project.constraints);
    if (project && !baselineId)
      setBaselineId(project.revisions[1]?.id ?? project.revisions[0].id);
  }, [project, constraints, baselineId]);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const addLog = (level: ConsoleEntry["level"], message: string) => {
    setConsoleEntries((entries) => [
      ...entries,
      { id: crypto.randomUUID(), time: now(), level, message },
    ]);
  };

  const updateProject = (
    updater: (payload: WorkbenchPayload) => WorkbenchPayload,
  ) => {
    queryClient.setQueryData<WorkbenchPayload>(
      ["workbench", designId],
      (previous) => (previous ? updater(previous) : previous),
    );
  };

  const createNewDesign = useMutation({
    mutationFn: async (prompt: string) => {
      if (!currentConstraints)
        throw new Error("Print constraints are not loaded");
      addLog("info", "Submitting a new design history to the planner");
      return createDesign(prompt, currentConstraints);
    },
    onSuccess: (response) => {
      addLog("ok", `Created persistent design ${response.design_id}`);
      selectDesign(response.design_id);
      setToast({ tone: "ok", message: `Design ${response.design_id} created` });
    },
    onError: (failure) => {
      addLog(
        "error",
        failure instanceof Error ? failure.message : "Design creation failed",
      );
      setToast({
        tone: "warn",
        message: "Design creation failed · check the console",
      });
      setDrawerOpen(true);
    },
  });

  const generate = useMutation({
    mutationFn: async () => {
      if (!project || !activeRevision || !currentConstraints)
        throw new Error("No active design");
      addLog(
        "info",
        `Planning revision from ${activeRevision.id}: ${revisionPrompt}`,
      );
      if (data?.source === "demo") {
        await delay(1300);
        const id = nextRevisionId(project.revisions);
        return {
          ...structuredClone(activeRevision),
          id,
          parentId: activeRevision.id,
          createdAt: new Date().toISOString(),
          author: "SeeCAD + human",
          message: revisionPrompt,
          state: "draft" as const,
          checksum: crypto.randomUUID().slice(0, 7),
        };
      }
      const response = await createRevision(
        project.id,
        activeRevision.id,
        `${project.brief}\n\nRevision instruction: ${revisionPrompt}`,
        currentConstraints,
      );
      return normalizeRevision(response);
    },
    onSuccess: (revision) => {
      updateProject((payload) => ({
        ...payload,
        project: {
          ...payload.project,
          activeRevisionId: revision.id,
          revisions: [revision, ...payload.project.revisions],
        },
      }));
      setBaselineId(activeRevision?.id ?? "");
      setComparing(true);
      addLog(
        "ok",
        `Created immutable revision ${revision.id}; parent ${revision.parentId ?? "none"}`,
      );
      setToast({ tone: "ok", message: `Revision ${revision.id} created` });
      if (data?.source === "api")
        void queryClient.invalidateQueries({
          queryKey: ["workbench", designId],
        });
    },
    onError: (failure) => {
      addLog(
        "error",
        failure instanceof Error
          ? failure.message
          : "Revision generation failed",
      );
      setDrawerOpen(true);
      setToast({
        tone: "warn",
        message: "Revision generation failed · console opened",
      });
    },
  });

  const compile = useMutation({
    mutationFn: async () => {
      if (!project || !activeRevision) throw new Error("No active revision");
      addLog("info", `Compiling ${activeRevision.id} with OpenSCAD / CGAL`);
      if (data?.source === "demo") {
        await delay(1000);
        return activeRevision;
      }
      return mergeCompileResult(
        await compileRevision(project.id, activeRevision.id),
        activeRevision,
      );
    },
    onSuccess: (revision) => {
      updateProject((payload) => ({
        ...payload,
        project: {
          ...payload.project,
          activeRevisionId: revision.id,
          revisions: [
            revision,
            ...payload.project.revisions.filter(
              (candidate) => candidate.id !== revision.id,
            ),
          ],
        },
      }));
      addLog("ok", `Compile complete · immutable child ${revision.id}`);
      setToast({ tone: "ok", message: "STL compiled and checksummed" });
      if (revision.id !== activeRevision?.id)
        setBaselineId(activeRevision?.id ?? "");
      if (data?.source === "api")
        void queryClient.invalidateQueries({
          queryKey: ["workbench", designId],
        });
    },
    onError: (failure) => {
      addLog(
        "error",
        failure instanceof Error ? failure.message : "Compile failed",
      );
      setDrawerOpen(true);
    },
  });

  const analyze = useMutation({
    mutationFn: async () => {
      if (!project || !activeRevision || !currentConstraints)
        throw new Error("No active revision");
      addLog(
        "info",
        `Analyzing ${activeRevision.id} against the active print profile`,
      );
      if (data?.source === "demo") {
        await delay(1150);
        return activeRevision;
      }
      const response = await analyzeRevision(
        project.id,
        activeRevision.id,
        currentConstraints,
      );
      return normalizeAnalysis(response, activeRevision);
    },
    onSuccess: (revision) => {
      updateProject((payload) => ({
        ...payload,
        project: {
          ...payload.project,
          activeRevisionId: revision.id,
          revisions: [
            revision,
            ...payload.project.revisions.filter(
              (candidate) => candidate.id !== revision.id,
            ),
          ],
        },
      }));
      addLog(
        "ok",
        "Analysis complete · exact and heuristic evidence kept separate",
      );
      setToast({
        tone: "ok",
        message: "Analysis complete · review the physical-fit boundary",
      });
      if (revision.id !== activeRevision?.id)
        setBaselineId(activeRevision?.id ?? "");
      if (data?.source === "api")
        void queryClient.invalidateQueries({
          queryKey: ["workbench", designId],
        });
    },
    onError: (failure) => {
      addLog(
        "error",
        failure instanceof Error ? failure.message : "Analysis failed",
      );
      setDrawerOpen(true);
    },
  });

  const approve = useMutation({
    mutationFn: async () => {
      if (!project || !activeRevision) throw new Error("No active revision");
      if (data?.source !== "api")
        throw new Error("Approval requires a live analyzed revision");
      if (activeRevision.state !== "analyzed")
        throw new Error("Analyze the active live revision before approval");
      const response = await approveRevision(project.id, activeRevision.id);
      return {
        ...normalizeRevision(response),
        source: activeRevision.source,
        analysisProfile: activeRevision.analysisProfile,
        dimensions: activeRevision.dimensions,
        volumeCm3: activeRevision.volumeCm3,
        massG: activeRevision.massG,
        printMinutes: activeRevision.printMinutes,
        triangles: activeRevision.triangles,
        diagnostics: activeRevision.diagnostics,
        state: "approved" as const,
      };
    },
    onSuccess: (approved) => {
      updateProject((payload) => ({
        ...payload,
        project: {
          ...payload.project,
          activeRevisionId: approved.id,
          revisions: [
            approved,
            ...payload.project.revisions.filter(
              (candidate) => candidate.id !== approved.id,
            ),
          ],
        },
      }));
      addLog("ok", `${approved.id} persisted as an approved child revision`);
      setToast({
        tone: "ok",
        message: `${approved.id} approved and persisted`,
      });
      if (data?.source === "api")
        void queryClient.invalidateQueries({
          queryKey: ["workbench", designId],
        });
    },
    onError: (failure) => {
      addLog(
        "error",
        failure instanceof Error ? failure.message : "Approval failed",
      );
      setToast({ tone: "warn", message: "Approval was not persisted" });
    },
  });

  const restore = useMutation({
    mutationFn: async (revision: Revision) => {
      if (!project || !activeRevision) throw new Error("No active revision");
      if (data?.source === "demo") {
        await delay(400);
        return {
          ...structuredClone(revision),
          id: nextRevisionId(project.revisions),
          parentId: activeRevision.id,
          createdAt: new Date().toISOString(),
          author: "Human reviewer",
          message: `Restore geometry from ${revision.id}`,
          state: "draft" as const,
          checksum: crypto.randomUUID().slice(0, 7),
        };
      }
      if (!revision.spec)
        throw new Error(
          "Historical spec is unavailable; restore was not created",
        );
      const response = await createSpecRevision(
        project.id,
        activeRevision.id,
        revision.spec,
        {
          author: "Human reviewer",
          message: `Restore geometry from ${revision.id}`,
          restored_from_revision_id: revision.id,
        },
      );
      return normalizeRevision(response);
    },
    onSuccess: (restored) => {
      setBaselineId(activeRevision?.id ?? "");
      updateProject((payload) => ({
        ...payload,
        project: {
          ...payload.project,
          activeRevisionId: restored.id,
          revisions: [
            restored,
            ...payload.project.revisions.filter(
              (candidate) => candidate.id !== restored.id,
            ),
          ],
        },
      }));
      addLog(
        "ok",
        `Persisted ${restored.id} from immutable snapshot ${restored.parentId ?? "unknown"}`,
      );
      setToast({
        tone: "ok",
        message: `Created persistent revision ${restored.id}`,
      });
      if (data?.source === "api")
        void queryClient.invalidateQueries({
          queryKey: ["workbench", designId],
        });
    },
    onError: (failure) => {
      addLog(
        "error",
        failure instanceof Error ? failure.message : "Restore failed",
      );
      setToast({ tone: "warn", message: "Restore was not persisted" });
    },
  });

  const exportRevision = async (format: ExportFormat) => {
    if (!project || !activeRevision) return;
    setExportOpen(false);
    try {
      await downloadExport(project.id, activeRevision, format);
      addLog("info", `Export requested · ${activeRevision.id}.${format}`);
    } catch (failure) {
      addLog(
        "warn",
        failure instanceof Error ? failure.message : "Export is unavailable",
      );
      setToast({
        tone: "warn",
        message: `${format.toUpperCase()} is not present on this revision`,
      });
    }
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement ||
        event.target instanceof HTMLSelectElement
      )
        return;
      if (event.key === "`") setDrawerOpen((open) => !open);
      if (event.key.toLowerCase() === "c") setComparing((value) => !value);
      if (event.key.toLowerCase() === "v" && !analyze.isPending)
        analyze.mutate();
      if (event.key === "Escape") {
        setDrawerOpen(false);
        setHelpOpen(false);
        setExportOpen(false);
      }
      if (event.key === "?") setHelpOpen(true);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [analyze]);

  const dimensions = useMemo(
    () =>
      activeRevision?.dimensions
        ? `${activeRevision.dimensions.x} × ${activeRevision.dimensions.y} × ${activeRevision.dimensions.z}`
        : "Not measured",
    [activeRevision],
  );

  if (isLoading) return <LoadingWorkbench />;
  if (
    isError ||
    !data ||
    !project ||
    !activeRevision ||
    !baseline ||
    !currentConstraints
  ) {
    return (
      <main className="fatal-state">
        <AlertTriangle size={28} />
        <h1>Workbench data could not be loaded</h1>
        <p>
          {error instanceof Error
            ? error.message
            : "The design response was empty."}
        </p>
        <button
          type="button"
          onClick={() =>
            queryClient.invalidateQueries({ queryKey: ["workbench", designId] })
          }
        >
          <RotateCcw size={14} /> Retry
        </button>
      </main>
    );
  }

  return (
    <div className={`app-shell ${drawerOpen ? "drawer-open" : ""}`}>
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">
            <span />
            <i />
          </div>
          <div>
            <strong>SeeCAD</strong>
            <span>Human inspection workcell</span>
          </div>
        </div>
        <button
          className="job-crumbs"
          type="button"
          aria-label="Open another design"
          onClick={() => setDesignPickerOpen(true)}
        >
          <FolderOpen size={12} />
          <span>WORKCELL 01</span>
          <i>/</i>
          <strong>{project.id}</strong>
          <i>/</i>
          <span>{activeRevision.id}</span>
        </button>
        <div className="topbar-status">
          <span className={`connection-state connection-${data.source}`}>
            <i />
            {data.source === "api" ? "Engine online" : "Demo instrument"}
          </span>
          <span className={`revision-state state-${activeRevision.state}`}>
            {activeRevision.state}
          </span>
        </div>
        <div className="topbar-actions">
          <button
            className="icon-action mobile-only"
            type="button"
            aria-label="Open project rail"
            onClick={() =>
              setMobileRail(mobileRail === "brief" ? null : "brief")
            }
          >
            <Menu size={17} />
          </button>
          <button
            className={`icon-action ${comparing ? "is-active" : ""}`}
            type="button"
            onClick={() => setComparing((value) => !value)}
            title="Compare revisions (C)"
          >
            <GitCompareArrows size={16} />
          </button>
          <button
            className={`icon-action ${drawerOpen ? "is-active" : ""}`}
            type="button"
            onClick={() => setDrawerOpen((open) => !open)}
            title="Source and console (`)"
          >
            <PanelBottomOpen size={16} />
          </button>
          <button
            className="icon-action"
            type="button"
            onClick={() => setHelpOpen(true)}
            title="Keyboard map (?)"
          >
            <HelpCircle size={16} />
          </button>
          <div className="export-menu">
            <button
              className="secondary-action"
              type="button"
              onClick={() => setExportOpen((open) => !open)}
            >
              <Download size={14} />
              Export
              <ChevronDown size={12} />
            </button>
            {exportOpen && (
              <div className="export-popover">
                {(
                  ["stl", "3mf", "scad", "spec", "analysis"] as ExportFormat[]
                ).map((format) => {
                  const available = canExportRevision(activeRevision, format);
                  return (
                    <button
                      type="button"
                      key={format}
                      onClick={() => exportRevision(format)}
                      disabled={!available}
                      title={
                        available
                          ? `Export ${format.toUpperCase()}`
                          : `${format.toUpperCase()} is not present on this revision`
                      }
                    >
                      <FileBox size={13} />
                      <span>{format.toUpperCase()}</span>
                      <small>
                        {!available
                          ? "not on active revision"
                          : format === "analysis"
                            ? "evidence record"
                            : format === "spec"
                              ? "design contract"
                              : "revision artifact"}
                      </small>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          <button
            className="primary-action"
            type="button"
            onClick={() => revisionInputRef.current?.focus()}
          >
            <Sparkles size={14} />
            New revision
          </button>
        </div>
      </header>

      {data.source === "demo" && (
        <div className="demo-notice" role="status">
          <span>
            <Braces size={12} /> Reference assembly — local example
          </span>
          <p>
            The workbench is showing the checked SeeCAD library assembly.
            Approval and artifact export remain disabled until a live revision
            is opened.
          </p>
          <code>{data.apiMessage}</code>
          <button type="button" onClick={() => setDesignPickerOpen(true)}>
            <FolderOpen size={11} />
            Open real design
          </button>
        </div>
      )}

      <main className="workbench">
        <aside
          className={`left-rail ${mobileRail === "brief" ? "mobile-open" : ""}`}
        >
          <button
            className="mobile-rail-close mobile-only"
            type="button"
            onClick={() => setMobileRail(null)}
          >
            <X size={14} />
            Close
          </button>
          <section
            className="rail-section project-brief"
            aria-labelledby="project-title"
          >
            <div className="rail-heading">
              <span className="eyebrow">Current work order</span>
              <h2 id="project-title">{project.name}</h2>
            </div>
            <p>{project.brief}</p>
            <div className="datum-block">
              <span>Envelope / millimeters</span>
              <strong>{dimensions}</strong>
              <small>origin · center / build plate</small>
            </div>
            <dl className="metrics-grid">
              <Metric
                label="Volume"
                value={
                  activeRevision.volumeCm3 === null
                    ? "—"
                    : activeRevision.volumeCm3.toFixed(2)
                }
                unit={activeRevision.volumeCm3 === null ? undefined : " cm³"}
                delta={
                  activeRevision.volumeCm3 === null
                    ? "awaiting analysis"
                    : "exact plate mesh"
                }
              />
              <Metric
                label="Mass"
                value={
                  activeRevision.massG === null
                    ? "—"
                    : activeRevision.massG.toFixed(1)
                }
                unit={activeRevision.massG === null ? undefined : " g"}
                delta={
                  activeRevision.massG === null
                    ? "not measured"
                    : "PETG estimate"
                }
              />
              <Metric
                label="Print"
                value={
                  activeRevision.printMinutes === null
                    ? "—"
                    : `${Math.floor(activeRevision.printMinutes / 60)}h ${activeRevision.printMinutes % 60}m`
                }
                delta={
                  activeRevision.printMinutes === null
                    ? "not estimated"
                    : `rough · ${currentConstraints.layerHeight.toFixed(2)} mm layer`
                }
              />
              <Metric
                label="Triangles"
                value={
                  activeRevision.triangles === null
                    ? "—"
                    : (activeRevision.triangles / 1000).toFixed(1)
                }
                unit={activeRevision.triangles === null ? undefined : "k"}
                delta={
                  activeRevision.triangles === null
                    ? "count unavailable"
                    : "CGAL render"
                }
              />
            </dl>
          </section>
          <AssemblyPanel components={activeRevision.components} />
          <ConstraintsPanel
            value={currentConstraints}
            onChange={setConstraints}
          />
          <PhaseTimeline operations={activeRevision.operations} />
        </aside>

        <div className="center-stage">
          <Suspense
            fallback={
              <div className="rig-loading" role="status">
                <ScanLine size={24} />
                <span>Initializing WebGL inspection optics…</span>
              </div>
            }
          >
            <VisionRig
              revision={activeRevision}
              comparing={comparing}
              baseline={baseline}
              demoFallback={data.source === "demo"}
            />
          </Suspense>
          <section
            className="revision-command"
            aria-labelledby="revision-command-title"
          >
            <div className="command-index">Δ</div>
            <div className="command-copy">
              <span className="eyebrow">Human-directed revision</span>
              <h2 id="revision-command-title">Describe one geometric change</h2>
              <p>
                The engine preserves the locked positive body, then regenerates
                negative space as one coherent pass.
              </p>
            </div>
            <div className="command-input">
              <textarea
                ref={revisionInputRef}
                rows={2}
                value={revisionPrompt}
                onChange={(event) =>
                  setRevisionPrompt(event.currentTarget.value)
                }
                aria-label="Revision instruction"
              />
              <button
                type="button"
                onClick={() => generate.mutate()}
                disabled={generate.isPending || !revisionPrompt.trim()}
              >
                {generate.isPending ? (
                  <CircleDashed className="spin" size={15} />
                ) : (
                  <Play size={15} />
                )}
                {generate.isPending ? "Planning…" : "Generate revision"}
              </button>
            </div>
          </section>
          <div className="action-strip">
            <div className="artifact-readout">
              <code>sha256:{activeRevision.checksum}</code>
              <span>immutable</span>
            </div>
            <button
              type="button"
              className="strip-action"
              onClick={() => compile.mutate()}
              disabled={compile.isPending}
            >
              {compile.isPending ? (
                <CircleDashed className="spin" size={14} />
              ) : (
                <Code2 size={14} />
              )}
              {compile.isPending ? "Compiling…" : "Compile mesh"}
            </button>
            <button
              type="button"
              className="strip-action"
              onClick={() => analyze.mutate()}
              disabled={analyze.isPending}
            >
              {analyze.isPending ? (
                <CircleDashed className="spin" size={14} />
              ) : (
                <ShieldCheck size={14} />
              )}
              {analyze.isPending ? "Analyzing…" : "Analyze"}
            </button>
            <button
              type="button"
              className="approve-action"
              onClick={() => approve.mutate()}
              disabled={
                data.source !== "api" ||
                activeRevision.state !== "analyzed" ||
                approve.isPending
              }
              title={
                data.source !== "api"
                  ? "Approval requires live API evidence"
                  : activeRevision.state !== "analyzed"
                    ? "Analyze this revision before approval"
                    : "Create an immutable approval attestation"
              }
            >
              {approve.isPending ? (
                <CircleDashed className="spin" size={14} />
              ) : activeRevision.state === "approved" ? (
                <Check size={14} />
              ) : (
                <BadgeCheck size={14} />
              )}
              {approve.isPending
                ? "Persisting…"
                : activeRevision.state === "approved"
                  ? "Approved"
                  : data.source !== "api"
                    ? "Live evidence required"
                    : activeRevision.state !== "analyzed"
                      ? "Analyze to approve"
                      : "Approve revision"}
            </button>
          </div>
        </div>

        <aside
          className={`right-rail ${mobileRail === "review" ? "mobile-open" : ""}`}
        >
          <button
            className="mobile-rail-close mobile-only"
            type="button"
            onClick={() => setMobileRail(null)}
          >
            <X size={14} />
            Close
          </button>
          <DiagnosticsPanel
            diagnostics={activeRevision.diagnostics}
            validating={analyze.isPending}
            onValidate={() => analyze.mutate()}
          />
          <RevisionsPanel
            revisions={project.revisions}
            activeId={activeRevision.id}
            baselineId={baseline.id}
            comparing={comparing}
            onBaselineChange={(id) => {
              setBaselineId(id);
              setComparing(true);
            }}
            onCompareChange={setComparing}
            onRestore={(revision) => restore.mutate(revision)}
          />
        </aside>
        <button
          className="mobile-review-trigger mobile-only"
          type="button"
          onClick={() => setMobileRail("review")}
        >
          <ShieldCheck size={15} />
          Review evidence
        </button>
      </main>

      <SourceDrawer
        open={drawerOpen}
        source={activeRevision.source}
        entries={consoleEntries}
        onClose={() => setDrawerOpen(false)}
        onDownload={() => exportRevision("scad")}
        downloadAvailable={canExportRevision(activeRevision, "scad")}
      />
      {toast && (
        <div className={`toast toast-${toast.tone}`} role="status">
          {toast.tone === "ok" ? (
            <Check size={14} />
          ) : (
            <AlertTriangle size={14} />
          )}
          {toast.message}
        </div>
      )}
      {helpOpen && <ShortcutHelp onClose={() => setHelpOpen(false)} />}
      {designPickerOpen && (
        <OpenDesignDialog
          currentId={designId}
          creating={createNewDesign.isPending}
          onClose={() => setDesignPickerOpen(false)}
          onOpen={selectDesign}
          onCreate={(prompt) => createNewDesign.mutate(prompt)}
        />
      )}
    </div>
  );
}
