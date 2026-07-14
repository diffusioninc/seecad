import { Boxes, Check, Library, Printer } from "lucide-react";
import type { AssemblyComponentSummary } from "../types";

interface AssemblyPanelProps {
  components: AssemblyComponentSummary[];
}

const kindLabels: Record<AssemblyComponentSummary["kind"], string> = {
  part: "Printed part",
  stock: "Stock",
  connector: "Connector",
  fastener: "Fastener",
};

export function AssemblyPanel({ components }: AssemblyPanelProps) {
  const total = components.reduce(
    (quantity, component) => quantity + component.quantity,
    0,
  );
  const libraryCount = components.reduce(
    (quantity, component) =>
      quantity + (component.libraryRef ? component.quantity : 0),
    0,
  );

  return (
    <section
      className="rail-section assembly-panel"
      aria-labelledby="assembly-title"
    >
      <div className="rail-heading rail-heading-inline">
        <div>
          <span className="eyebrow">
            <Boxes size={13} /> Physical register
          </span>
          <h2 id="assembly-title">Assembly</h2>
        </div>
        <span className="assembly-total">{total} pcs</span>
      </div>
      {components.length ? (
        <ol className="assembly-list">
          {components.map((component) => (
            <li key={component.id}>
              <span className="assembly-quantity">
                {component.quantity}
                <small>×</small>
              </span>
              <span className="assembly-part-copy">
                <strong>{component.name}</strong>
                <span>{component.detail}</span>
                <small>{kindLabels[component.kind]}</small>
              </span>
              <span
                className={`assembly-origin ${component.libraryRef ? "is-library" : "is-custom"}`}
                title={component.libraryRef ?? "Custom semantic part"}
              >
                {component.libraryRef ? (
                  <Library size={11} />
                ) : (
                  <Printer size={11} />
                )}
                {component.libraryRef ? "Library" : "Custom"}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="assembly-empty">No component register was recorded.</p>
      )}
      <div className="assembly-summary">
        <Check size={12} /> {libraryCount} library-backed pieces ·{" "}
        {total - libraryCount} custom
      </div>
    </section>
  );
}
