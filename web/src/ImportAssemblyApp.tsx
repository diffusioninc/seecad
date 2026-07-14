import {
  Boxes,
  ChevronLeft,
  FileArchive,
  Maximize,
  Ruler,
  ScanLine,
  Upload,
} from "lucide-react";
import { useCallback, useRef, useState, type DragEvent } from "react";

import {
  ImportedAssemblyRig,
  type ImportedAssemblyMetrics,
} from "./components/ImportedAssemblyRig";
import { openImportFiles, type ImportedArchive } from "./import-archive";

function bytesLabel(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KiB`;
}

function numberLabel(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function dimensionLabel(value: number, millimetres: boolean): string {
  const formatted = value >= 100 ? value.toFixed(1) : value.toFixed(2);
  return millimetres ? `${formatted} mm` : `${formatted} coord`;
}

export default function ImportAssemblyApp() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [archive, setArchive] = useState<ImportedArchive | null>(null);
  const [metrics, setMetrics] = useState<ImportedAssemblyMetrics | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [millimetres, setMillimetres] = useState(false);
  const [showEdges, setShowEdges] = useState(false);
  const [upAxis, setUpAxis] = useState<"z" | "y">("z");

  const onMetrics = useCallback(
    (next: ImportedAssemblyMetrics) => setMetrics(next),
    [],
  );
  const onRigError = useCallback((message: string) => setError(message), []);

  const openFiles = async (files: FileList | File[]) => {
    setLoading(true);
    setError("");
    try {
      const next = await openImportFiles(files);
      setArchive(next);
      setMetrics(null);
      setMillimetres(false);
    } catch (failure) {
      setArchive(null);
      setMetrics(null);
      setError(
        failure instanceof Error
          ? failure.message
          : "The selected files could not be opened.",
      );
    } finally {
      setLoading(false);
    }
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    void openFiles(event.dataTransfer.files);
  };

  return (
    <div className="import-shell">
      <header className="import-topbar">
        <a
          className="import-brand"
          href="/"
          aria-label="Return to SeeCAD workbench"
        >
          <span className="brand-mark" aria-hidden="true">
            <span />
            <i />
          </span>
          <span>
            <strong>SeeCAD</strong>
            <small>Local assembly intake</small>
          </span>
        </a>
        <div className="import-title">
          <FileArchive size={15} />
          <span>Imported assembly preview</span>
          <i>/</i>
          <strong>{archive?.name ?? "No source open"}</strong>
        </div>
        <div className="import-status">
          <span>
            <i /> read-only
          </span>
          <span>no revision</span>
        </div>
      </header>

      <main className="import-main">
        <aside
          className="import-rail"
          aria-label="Import source and evidence boundary"
        >
          <section className="import-intro">
            <span className="import-eyebrow">Source boundary</span>
            <h1>Open geometry without changing its authority.</h1>
            <p>
              ZIP, OBJ, MTL, and referenced image textures stay in this browser
              tab. SeeCAD does not create a design, revision, compile, analysis,
              or assembly manifest.
            </p>
          </section>

          <div
            className={`import-drop ${dragging ? "is-dragging" : ""}`}
            onDragEnter={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <Upload size={18} />
            <strong>
              {loading ? "Reading locally…" : "Open an assembly archive"}
            </strong>
            <span>One ZIP, or select OBJ + MTL + textures together</span>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={loading}
            >
              Choose files
            </button>
            <input
              ref={inputRef}
              type="file"
              accept=".zip,.obj,.mtl,.png,.jpg,.jpeg,.webp,.bmp"
              multiple
              onChange={(event) => {
                if (event.currentTarget.files)
                  void openFiles(event.currentTarget.files);
                event.currentTarget.value = "";
              }}
            />
          </div>

          {error && (
            <div className="import-error" role="alert">
              {error}
            </div>
          )}

          {archive && (
            <>
              <section
                className="import-facts"
                aria-label="Parsed source facts"
              >
                <div className="import-section-heading">
                  <span className="import-eyebrow">Parsed source</span>
                  <strong>Exact to the selected files</strong>
                </div>
                <dl>
                  <div>
                    <dt>Archive</dt>
                    <dd>{bytesLabel(archive.sourceBytes)}</dd>
                  </div>
                  <div>
                    <dt>Expanded</dt>
                    <dd>{bytesLabel(archive.expandedBytes)}</dd>
                  </div>
                  <div>
                    <dt>OBJ files</dt>
                    <dd>
                      {metrics?.objectFiles ?? archive.objectPaths.length}
                    </dd>
                  </div>
                  <div>
                    <dt>OBJ records</dt>
                    <dd>{metrics?.objectRecords ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Mesh groups</dt>
                    <dd>{metrics?.meshGroups ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Materials</dt>
                    <dd>{metrics?.materialGroups ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Triangles</dt>
                    <dd>{metrics ? numberLabel(metrics.triangles) : "—"}</dd>
                  </div>
                </dl>
                {metrics && (
                  <div className="import-envelope">
                    <span>Source-coordinate envelope</span>
                    <strong>
                      {dimensionLabel(metrics.sourceSize.x, millimetres)} ×{" "}
                      {dimensionLabel(metrics.sourceSize.y, millimetres)} ×{" "}
                      {dimensionLabel(metrics.sourceSize.z, millimetres)}
                    </strong>
                  </div>
                )}
              </section>

              <section
                className="import-controls"
                aria-label="Preview declarations and view controls"
              >
                <label className="import-check">
                  <input
                    type="checkbox"
                    checked={millimetres}
                    onChange={(event) =>
                      setMillimetres(event.currentTarget.checked)
                    }
                  />
                  <span>
                    <strong>Coordinates are millimetres</strong>
                    <small>
                      Human declaration; never inferred from scale or filename.
                    </small>
                  </span>
                </label>
                <label className="import-field">
                  <span>Preview up axis</span>
                  <select
                    value={upAxis}
                    onChange={(event) =>
                      setUpAxis(event.currentTarget.value as "z" | "y")
                    }
                  >
                    <option value="z">Z up · CAD heuristic</option>
                    <option value="y">Y up · alternate view</option>
                  </select>
                </label>
                <label className="import-check compact">
                  <input
                    type="checkbox"
                    checked={showEdges}
                    onChange={(event) =>
                      setShowEdges(event.currentTarget.checked)
                    }
                  />
                  <span>
                    <strong>Show feature edges</strong>
                  </span>
                </label>
              </section>
            </>
          )}

          <a className="import-back" href="/">
            <ChevronLeft size={13} /> Generated-design workbench
          </a>
        </aside>

        <section
          className="import-viewport"
          aria-label="Imported assembly viewport"
        >
          <div className="import-viewport-head">
            <div>
              <span className="import-eyebrow">Inspection viewport</span>
              <strong>
                {archive ? "Source geometry" : "Waiting for local files"}
              </strong>
            </div>
            <div className="import-view-state">
              <span>
                <ScanLine size={12} /> {upAxis.toUpperCase()} up
              </span>
              <span>
                <Ruler size={12} />{" "}
                {millimetres ? "mm declared" : "units undeclared"}
              </span>
              <span>
                <Boxes size={12} /> visual groups only
              </span>
            </div>
          </div>
          <div
            className="import-canvas-wrap"
            data-model-ready={archive && metrics ? "true" : "false"}
          >
            {archive ? (
              <ImportedAssemblyRig
                archive={archive}
                showEdges={showEdges}
                upAxis={upAxis}
                onMetrics={onMetrics}
                onError={onRigError}
              />
            ) : (
              <div className="import-empty">
                <Maximize size={34} />
                <strong>Local geometry appears here</strong>
                <span>Drag a ZIP onto the source rail or choose files.</span>
              </div>
            )}
          </div>
          <footer className="import-boundary">
            <strong>
              {millimetres
                ? "Millimetres declared for this preview."
                : "Source units remain undeclared."}
            </strong>
            <span>
              OBJ objects and material groups are display evidence, not a
              physical-instance inventory. Use an AssemblyLintSpec for
              inventory, fasteners, relationships, or tool access.
            </span>
          </footer>
        </section>
      </main>
    </div>
  );
}
