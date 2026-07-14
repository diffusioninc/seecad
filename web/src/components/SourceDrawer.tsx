import {
  Check,
  ChevronDown,
  Clipboard,
  Code2,
  Download,
  TerminalSquare,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { ConsoleEntry } from "../types";

interface SourceDrawerProps {
  open: boolean;
  source: string;
  entries: ConsoleEntry[];
  onClose: () => void;
  onDownload: () => void;
  downloadAvailable: boolean;
}

export function SourceDrawer({
  open,
  source,
  entries,
  onClose,
  onDownload,
  downloadAvailable,
}: SourceDrawerProps) {
  const [tab, setTab] = useState<"source" | "console">("source");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timeout = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timeout);
  }, [copied]);

  const copy = async () => {
    await navigator.clipboard.writeText(source);
    setCopied(true);
  };

  return (
    <aside
      className={`source-drawer ${open ? "is-open" : ""}`}
      aria-hidden={!open}
      aria-label="Source and build console"
    >
      <header className="drawer-header">
        <div className="drawer-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "source"}
            className={tab === "source" ? "is-active" : ""}
            onClick={() => setTab("source")}
          >
            <Code2 size={14} /> OpenSCAD source
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "console"}
            className={tab === "console" ? "is-active" : ""}
            onClick={() => setTab("console")}
          >
            <TerminalSquare size={14} /> Build console{" "}
            <span>{entries.length}</span>
          </button>
        </div>
        <div className="drawer-actions">
          {tab === "source" && (
            <>
              <button type="button" onClick={copy}>
                {copied ? <Check size={13} /> : <Clipboard size={13} />}
                {copied ? "Copied" : "Copy"}
              </button>
              <button
                type="button"
                onClick={onDownload}
                disabled={!downloadAvailable}
                title={
                  downloadAvailable
                    ? "Save this revision's SCAD artifact"
                    : "SCAD is not present on this revision"
                }
              >
                <Download size={13} />
                Save .scad
              </button>
            </>
          )}
          <button
            className="drawer-close"
            type="button"
            onClick={onClose}
            aria-label="Close drawer"
          >
            <X size={15} />
          </button>
        </div>
      </header>
      <div className="drawer-body">
        {tab === "source" ? (
          <div className="source-view">
            <div className="line-numbers" aria-hidden="true">
              {source.split("\n").map((_, index) => (
                <span key={index}>{index + 1}</span>
              ))}
            </div>
            <pre>
              <code>{source}</code>
            </pre>
          </div>
        ) : (
          <div className="console-view">
            {entries.map((entry) => (
              <div
                className={`console-entry console-${entry.level}`}
                key={entry.id}
              >
                <time>{entry.time}</time>
                <span>{entry.level.toUpperCase()}</span>
                <p>{entry.message}</p>
              </div>
            ))}
            <div className="console-prompt">
              <ChevronDown size={12} /> build idle — waiting for revision action
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
