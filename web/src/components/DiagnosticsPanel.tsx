import {
  AlertTriangle,
  Check,
  ChevronRight,
  CircleDashed,
  Ruler,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";
import type { Diagnostic, EvidenceClass } from "../types";

interface DiagnosticsPanelProps {
  diagnostics: Diagnostic[];
  validating: boolean;
  onValidate: () => void;
}

const tabs: Array<{ id: EvidenceClass; label: string }> = [
  { id: "exact", label: "Exact" },
  { id: "bounded", label: "Bounded" },
  { id: "heuristic", label: "Heuristic" },
  { id: "unavailable", label: "Unavailable" },
];

export function DiagnosticsPanel({
  diagnostics,
  validating,
  onValidate,
}: DiagnosticsPanelProps) {
  const [tab, setTab] = useState<EvidenceClass>("exact");
  const visible = diagnostics.filter(
    (diagnostic) => diagnostic.evidence === tab,
  );
  const counts = diagnostics.reduce<Record<EvidenceClass, number>>(
    (result, diagnostic) => {
      result[diagnostic.evidence] += 1;
      return result;
    },
    { exact: 0, bounded: 0, heuristic: 0, unavailable: 0 },
  );
  const passCount = diagnostics.filter(
    (diagnostic) => diagnostic.severity === "pass",
  ).length;

  return (
    <section className="diagnostics" aria-labelledby="diagnostics-title">
      <header className="diagnostics-header">
        <div>
          <span className="eyebrow">
            <ShieldCheck size={13} /> Manufacturability
          </span>
          <h2 id="diagnostics-title">
            {passCount}/{diagnostics.length} checks clear
          </h2>
        </div>
        <button
          className="text-action"
          type="button"
          onClick={onValidate}
          disabled={validating}
        >
          {validating ? (
            <CircleDashed className="spin" size={14} />
          ) : (
            <Ruler size={14} />
          )}
          {validating ? "Measuring…" : "Run analysis"}
        </button>
      </header>
      <div className="evidence-note">
        <span className={`evidence-key evidence-${tab}`}>{tab}</span>
        {tab === "exact" && "Computed directly from the compiled mesh."}
        {tab === "bounded" && "Verified within a stated numerical bound."}
        {tab === "heuristic" &&
          "Reasoned from geometry; requires human judgment."}
        {tab === "unavailable" &&
          "The current toolchain did not prove this property."}
      </div>
      <div
        className="diagnostic-tabs"
        role="tablist"
        aria-label="Evidence class"
      >
        {tabs.map((candidate) => (
          <button
            key={candidate.id}
            type="button"
            role="tab"
            aria-selected={tab === candidate.id}
            className={tab === candidate.id ? "is-active" : ""}
            onClick={() => setTab(candidate.id)}
          >
            {candidate.label}
            <span>{counts[candidate.id]}</span>
          </button>
        ))}
      </div>
      <div className="diagnostic-list">
        {visible.length ? (
          visible.map((diagnostic) => (
            <details
              className={`diagnostic diagnostic-${diagnostic.severity}`}
              key={diagnostic.id}
            >
              <summary>
                <span className="diagnostic-icon">
                  {diagnostic.severity === "pass" ? (
                    <Check size={12} />
                  ) : (
                    <AlertTriangle size={12} />
                  )}
                </span>
                <span>
                  <strong>{diagnostic.label}</strong>
                  <small>{diagnostic.location}</small>
                </span>
                <code>{diagnostic.value}</code>
                <ChevronRight className="detail-chevron" size={14} />
              </summary>
              <div className="diagnostic-detail">
                <p>{diagnostic.detail}</p>
                <span>Evidence source · {diagnostic.source}</span>
              </div>
            </details>
          ))
        ) : (
          <div className="diagnostic-empty">
            <CircleDashed size={18} /> No {tab} checks returned for this
            analysis.
          </div>
        )}
      </div>
    </section>
  );
}
