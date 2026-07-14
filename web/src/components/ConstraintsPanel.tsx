import { ChevronDown, SlidersHorizontal } from "lucide-react";
import type { ConstraintSet } from "../types";

interface ConstraintsPanelProps {
  value: ConstraintSet;
  onChange: (next: ConstraintSet) => void;
}

function Slider({
  label,
  unit,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  unit: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  const fill = ((value - min) / (max - min)) * 100;
  return (
    <label className="constraint-slider">
      <span>
        <span>{label}</span>
        <output>
          {value}
          {unit}
        </output>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        style={{ "--range-fill": `${fill}%` } as React.CSSProperties}
        onChange={(event) => onChange(Number(event.currentTarget.value))}
      />
    </label>
  );
}

export function ConstraintsPanel({ value, onChange }: ConstraintsPanelProps) {
  const patch = <K extends keyof ConstraintSet>(
    key: K,
    next: ConstraintSet[K],
  ) => onChange({ ...value, [key]: next });
  const patchBuildVolume = (axis: "x" | "y" | "z", next: number) =>
    patch("buildVolume", { ...value.buildVolume, [axis]: next });
  const patchProcess = (next: string) => {
    const nozzle = next.match(/([0-9.]+) mm nozzle/i);
    const nozzleDiameter = nozzle ? Number(nozzle[1]) : value.nozzleDiameter;
    onChange({
      ...value,
      process: next,
      nozzleDiameter,
      layerHeight: next.startsWith("FDM")
        ? Math.min(value.layerHeight, nozzleDiameter)
        : value.layerHeight,
    });
  };
  return (
    <section
      className="rail-section constraints"
      aria-labelledby="constraints-title"
    >
      <div className="rail-heading rail-heading-inline">
        <div>
          <span className="eyebrow">Print profile</span>
          <h2 id="constraints-title">Constraints</h2>
        </div>
        <SlidersHorizontal size={16} />
      </div>
      <label className="select-field">
        <span>Material</span>
        <select
          value={value.material}
          onChange={(event) => patch("material", event.currentTarget.value)}
        >
          <option>PETG · Prusament</option>
          <option>PA-CF · Polymaker</option>
          <option>ASA · Polymaker</option>
          <option>PLA · Generic</option>
        </select>
        <ChevronDown size={13} />
      </label>
      <label className="select-field">
        <span>Process</span>
        <select
          value={value.process}
          onChange={(event) => patchProcess(event.currentTarget.value)}
        >
          <option>FDM · 0.4 mm nozzle</option>
          <option>FDM · 0.6 mm nozzle</option>
          <option>SLA · Tough resin</option>
          <option>SLS · PA12</option>
        </select>
        <ChevronDown size={13} />
      </label>
      <div className="constraint-grid">
        <Slider
          label="Layer"
          unit=" mm"
          value={value.layerHeight}
          min={0.05}
          max={value.process.startsWith("FDM") ? value.nozzleDiameter : 0.6}
          step={0.05}
          onChange={(next) => patch("layerHeight", next)}
        />
        <Slider
          label="Wall floor"
          unit=" mm"
          value={value.minWall}
          min={0.8}
          max={5}
          step={0.2}
          onChange={(next) => patch("minWall", next)}
        />
        <Slider
          label="Clearance"
          unit=" mm"
          value={value.minClearance}
          min={0.1}
          max={1}
          step={0.05}
          onChange={(next) => patch("minClearance", next)}
        />
        <Slider
          label="Overhang"
          unit="°"
          value={value.maxOverhang}
          min={25}
          max={70}
          step={1}
          onChange={(next) => patch("maxOverhang", next)}
        />
        <Slider
          label="Tolerance"
          unit=" mm"
          value={value.tolerance}
          min={0}
          max={1}
          step={0.05}
          onChange={(next) => patch("tolerance", next)}
        />
        <Slider
          label="Infill"
          unit="%"
          value={value.infill}
          min={10}
          max={100}
          step={5}
          onChange={(next) => patch("infill", next)}
        />
      </div>
      <fieldset className="build-volume-field">
        <legend>Build volume / mm</legend>
        {(["x", "y", "z"] as const).map((axis) => (
          <label key={axis}>
            <span>{axis.toUpperCase()}</span>
            <input
              type="number"
              min="1"
              max="1000000"
              step="1"
              value={value.buildVolume[axis]}
              onChange={(event) =>
                patchBuildVolume(axis, Number(event.currentTarget.value))
              }
            />
          </label>
        ))}
      </fieldset>
      <label className="text-field compact-field">
        <span>Load case</span>
        <input
          value={value.loadCase}
          onChange={(event) => patch("loadCase", event.currentTarget.value)}
        />
      </label>
    </section>
  );
}
