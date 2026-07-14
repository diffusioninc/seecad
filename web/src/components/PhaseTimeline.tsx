import { Check, CircleDot, LockKeyhole, Minus, Plus } from "lucide-react";
import type { ModelingOperation } from "../types";

interface PhaseTimelineProps {
  operations: ModelingOperation[];
}

function Phase({
  phase,
  index,
  operations,
}: {
  phase: "positive" | "negative";
  index: string;
  operations: ModelingOperation[];
}) {
  const positive = phase === "positive";
  return (
    <div className={`phase phase-${phase}`}>
      <div className="phase-heading">
        <span className="phase-index">{index}</span>
        <span className="phase-mark">
          {positive ? <Plus size={14} /> : <Minus size={14} />}
        </span>
        <div>
          <strong>{positive ? "Positive volume" : "Negative space"}</strong>
          <small>
            {positive
              ? "Establish the load-bearing body"
              : "Subtract passages and access"}
          </small>
        </div>
      </div>
      <ol className="operation-list">
        {operations.map((operation) => (
          <li
            key={operation.id}
            className={`operation operation-${operation.status}`}
          >
            <span className="operation-node">
              {operation.status === "complete" ? (
                <Check size={11} />
              ) : (
                <CircleDot size={11} />
              )}
            </span>
            <div>
              <strong>{operation.label}</strong>
              <span>{operation.detail}</span>
            </div>
            <code>{operation.primitive}</code>
          </li>
        ))}
      </ol>
      {positive && (
        <div className="phase-gate">
          <LockKeyhole size={12} /> Body locked before subtraction
        </div>
      )}
    </div>
  );
}

export function PhaseTimeline({ operations }: PhaseTimelineProps) {
  return (
    <section
      className="rail-section phase-timeline"
      aria-labelledby="build-sequence-title"
    >
      <div className="rail-heading">
        <span className="eyebrow">Constructive sequence</span>
        <h2 id="build-sequence-title">Build intent</h2>
      </div>
      <Phase
        phase="positive"
        index="01"
        operations={operations.filter(
          (operation) => operation.phase === "positive",
        )}
      />
      <div className="phase-handoff">
        <span>Difference boundary</span>
      </div>
      <Phase
        phase="negative"
        index="02"
        operations={operations.filter(
          (operation) => operation.phase === "negative",
        )}
      />
    </section>
  );
}
