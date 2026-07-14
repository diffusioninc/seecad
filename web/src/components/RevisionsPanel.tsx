import { Check, GitCompareArrows, LockKeyhole, RotateCcw } from "lucide-react";
import type { Revision } from "../types";

interface RevisionsPanelProps {
  revisions: Revision[];
  activeId: string;
  baselineId: string;
  comparing: boolean;
  onBaselineChange: (id: string) => void;
  onCompareChange: (value: boolean) => void;
  onRestore: (revision: Revision) => void;
}

export function RevisionsPanel({
  revisions,
  activeId,
  baselineId,
  comparing,
  onBaselineChange,
  onCompareChange,
  onRestore,
}: RevisionsPanelProps) {
  const active =
    revisions.find((revision) => revision.id === activeId) ?? revisions[0];
  const baseline =
    revisions.find((revision) => revision.id === baselineId) ??
    revisions[1] ??
    revisions[0];
  const massDelta =
    active.massG !== null && baseline.massG !== null
      ? active.massG - baseline.massG
      : null;
  const heightDelta =
    active.dimensions && baseline.dimensions
      ? active.dimensions.z - baseline.dimensions.z
      : null;
  const printDelta =
    active.printMinutes !== null && baseline.printMinutes !== null
      ? active.printMinutes - baseline.printMinutes
      : null;

  return (
    <section className="revisions" aria-labelledby="revisions-title">
      <header className="revision-header">
        <div>
          <span className="eyebrow">
            <GitCompareArrows size={13} /> Immutable history
          </span>
          <h2 id="revisions-title">Revision compare</h2>
        </div>
        <label className="compare-switch">
          <input
            type="checkbox"
            checked={comparing}
            onChange={(event) => onCompareChange(event.currentTarget.checked)}
          />
          <span aria-hidden="true" />
          Overlay
        </label>
      </header>

      {comparing && (
        <div className="revision-delta">
          <div>
            <span>Baseline</span>
            <strong>{baseline.id}</strong>
            <code>{baseline.checksum}</code>
          </div>
          <div className="delta-arrow">→</div>
          <div>
            <span>Current</span>
            <strong>{active.id}</strong>
            <code>{active.checksum}</code>
          </div>
          <dl>
            <div>
              <dt>Mass</dt>
              <dd>
                {massDelta === null
                  ? "—"
                  : `${massDelta >= 0 ? "+" : ""}${massDelta.toFixed(1)} g`}
              </dd>
            </div>
            <div>
              <dt>Z height</dt>
              <dd>
                {heightDelta === null
                  ? "—"
                  : `${heightDelta >= 0 ? "+" : ""}${heightDelta.toFixed(1)} mm`}
              </dd>
            </div>
            <div>
              <dt>Print</dt>
              <dd>
                {printDelta === null
                  ? "—"
                  : `${printDelta >= 0 ? "+" : ""}${printDelta} min`}
              </dd>
            </div>
          </dl>
        </div>
      )}

      <div className="revision-list">
        {revisions.map((revision) => {
          const current = revision.id === activeId;
          const selected = revision.id === baselineId;
          return (
            <button
              className={`revision-row ${current ? "is-current" : ""} ${selected && comparing ? "is-baseline" : ""}`}
              key={revision.id}
              type="button"
              onClick={() => !current && onBaselineChange(revision.id)}
            >
              <span className="revision-rail">
                {current ? <Check size={11} /> : <span />}
              </span>
              <span className="revision-copy">
                <span>
                  <strong>{revision.id}</strong>
                  <code>{revision.checksum}</code>
                  {current && <em>current</em>}
                </span>
                <small>{revision.message}</small>
                <time>
                  {new Date(revision.createdAt).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}{" "}
                  · {revision.author}
                </time>
              </span>
              <LockKeyhole size={12} />
            </button>
          );
        })}
      </div>
      {comparing && baseline.id !== active.id && (
        <button
          className="restore-action"
          type="button"
          onClick={() => onRestore(baseline)}
        >
          <RotateCcw size={13} /> Create a new revision from {baseline.id}
        </button>
      )}
    </section>
  );
}
