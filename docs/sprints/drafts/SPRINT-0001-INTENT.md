# Sprint 0001 Intent: Imported Geometry Spatial Evidence Loop

## Seed

Turn the Printables organizer vet into a concrete first sprint toward making SeeCAD the definitive agentic "thinking in 3D" system. Preserve every improvement idea from the review, but separate the immediately implementable foundation from later fit, motion, manufacturing, and closed-loop design capabilities.

## Orientation

- SeeCAD already has strong semantic authorities (`DesignSpec` and `AssemblyLintSpec`), immutable revisions and content-addressed artifacts, bounded execution, explicit confidence labels, mesh linting, and proof-sheet concepts.
- The largest missing capability is imported-geometry ingestion and interpretation: SeeCAD can check a supplied manifest or mesh, but cannot yet turn source files, listing claims, images, and documentation into a traceable spatial model that an agent can interrogate.
- The CLI exposes assembly lint and mesh lint, while the MCP server does not yet provide equivalent agent-facing tools.
- Several decisive checks from the organizer vet—passage count, physical-instance count, per-side clearance, absence of a rear stop, and contradiction of the listing's modularity claim—required ad hoc mesh inspection outside SeeCAD.
- Wall-thickness/process reasoning remains incomplete, and slicer/G-code analysis is planned rather than an authoritative current capability.

## Pyramid Index

- **L0 — Goal:** Give agents a trustworthy, inspectable bridge from arbitrary 3D source material to semantic spatial reasoning and evidence-backed conclusions.
- **L1 — Foundation:** Immutable source ingestion, a non-authoritative Spatial Evidence Graph, agent/API parity for existing checks, structured claims, and draft assembly manifests.
- **L2 — Expansion:** Fit and motion checks, process evidence, evidence-to-design iteration, and benchmarked spatial-reasoning quality.

## Semantic Index

Not configured at the user's direction. Planning proceeds directly from the repository and the completed organizer vet.

## Chapter Context

No chapter is configured for this repository. This sprint should stand alone while leaving a clean boundary for a future multi-sprint chapter.

## Recent Sprint Context

This is the first repository sprint document. There is no prior SeeCAD sprint ledger entry to inherit.

## Required Capability Direction

The plan must preserve this full progression, even if only the first layers are implementation scope for Sprint 0001:

### P0 — Agent and ingestion foundation

- Add MCP parity for assembly lint and mesh lint so agents do not need shell-only escape hatches for existing capabilities.
- Introduce an immutable, content-addressed `SourceBundle` for local source files and source metadata. Treat remote acquisition as a separate bounded adapter; parsers and analyzers remain offline, resource-limited, and capability-free.
- Record source license, origin, retrieval metadata, hashes, units declarations, coordinate-frame decisions, and parser/tool versions without committing downloaded user or third-party CAD artifacts.

### P1 — Spatial Evidence Graph

- Add a non-authoritative intermediate representation between raw source material and semantic authorities. It must describe observations and hypotheses without silently becoming `DesignSpec` or `AssemblyLintSpec`.
- Represent reusable part definitions separately from explicit physical occurrences. A drafted assembly manifest must still expand every physical instance, as required by the assembly-lint contract.
- Give every claim traceable evidence: artifact and region, algorithm and version, coordinate frame, units, confidence (`exact`, `bounded`, or `heuristic`), assumptions/tolerances, and contradictions.
- Provide primitives conceptually equivalent to `observe_geometry`, `find_passages`, `measure_clearance`, `infer_interfaces`, `find_stops`, `reconcile_claims`, and `render_evidence`.
- Draft—but never silently approve—an `AssemblyLintSpec` from imported evidence, with explicit source/assumption separation and human review before it becomes authoritative input.
- Reconcile external claims against observed geometry, such as advertised dimensions, compartment count, modularity, part count, and license/provenance.

### P2 — Fit and motion reasoning

- Add clearance and interference checks that state their tolerance model and whether a reported gap is normal, radial, axial, or bounding-box-only.
- Model insertion paths, swept volumes, open/closed configurations, retention, end stops, and accessible approach paths.
- Support evidence views for sections, exploded assemblies, collision regions, clearance heatmaps, and motion envelopes.

### P3 — Process evidence

- Add wall-thickness, unsupported-span, overhang, minimum-feature, orientation, and process-envelope observations with exact/bounded/heuristic labels.
- Integrate slicer and G-code-derived evidence without presenting manufacturability, strength, fit, or print success as guaranteed.

### P4 — Evidence-to-design loop

- Let an agent convert approved evidence and contradictions into proposed semantic design changes, regenerate derivatives, and compare the new revision against the original claims and acceptance checks.
- Keep semantic intent authoritative and make every generated SCAD, mesh, render, report, and comparison reproducible.

### P5 — Spatial-reasoning benchmarks

- Establish a corpus of synthetic and legally usable fixtures with known answers for counting, dimensions, fit, motion, accessibility, provenance, and claim reconciliation.
- Measure correctness, calibration, evidence completeness, deterministic replay, runtime/resource bounds, and regression quality—not only whether a command exits successfully.

## Suggested Agent Surface

The plan should evaluate a coherent CLI and MCP vocabulary around:

- `seecad ingest`
- `seecad observe`
- `seecad draft-assembly`
- `seecad reconcile`
- `seecad fit-check`
- `seecad motion-check`

Names may change if the repository's existing conventions suggest a clearer API, but CLI and MCP operations should share the same service-layer implementation and schemas.

## Acceptance Fixture

Use the modular-honeycomb desktop-organizer vet as the behavioral target:

- Distinguish one shell definition, one drawer definition, and eight physical occurrences (one shell plus seven drawers).
- Observe seven passages/compartments and flag a conflicting source claim of six.
- Recover or verify millimetre dimensions and the claimed 0.2 mm per-side clearance with a declared tolerance model.
- Identify that the shell is monolithic rather than composed of attachable modules.
- Find the lack of a positive rear stop or retention feature and distinguish that observation from a guaranteed real-world failure.
- Preserve the source license and provenance, and avoid committing downloaded source CAD or derived artifacts.

Because the downloaded model is third-party and licensed CC BY-NC-ND 4.0, the committed automated fixture should be a purpose-built synthetic analogue with known geometry and claims. The real model may be used only in an ephemeral, documented manual proof if its license and terms allow that use.

## Relevant Repository Surfaces

- `src/seecad/cli.py`
- `src/seecad/mcp_server.py`
- `src/seecad/models.py`
- `src/seecad/analysis.py`
- `src/seecad/assembly_lint.py`
- `src/seecad/mesh_lint.py`
- service, store, worker, API, and artifact/provenance modules adjacent to those files
- `docs/ARCHITECTURE.md`
- `docs/ASSEMBLY-LINT.md`
- `docs/MESH-LINT.md`
- `docs/PROOF-SHEETS.md`
- `docs/GCODE.md`
- `docs/SECURITY.md`
- existing unit, CLI, MCP, security, and integration tests

## Constraints

- Every units field and spatial result must explicitly use millimetres; never infer units silently.
- Imported or existing assemblies must stay on the standalone assembly-lint path and must not be coerced into `DesignSpec` or compiled.
- Keep `DesignSpec`, `AssemblyLintSpec`, and future user-approved semantic specifications authoritative. The Spatial Evidence Graph is evidence and hypothesis only.
- Preserve the positive-volume-then-consolidated-negative-space invariant for generated designs.
- Name holes, passages, clearances, stops, interfaces, and access paths as semantic features when they enter an authoritative design.
- Make every compile and analysis run immutable and content-addressed, with replayable inputs and tool versions.
- Label each result exact, bounded, or heuristic. Never imply guaranteed fit, access, thread engagement, preload, manufacturability, strength, or print success.
- Run untrusted geometry parsers and generated code offline with bounded CPU, memory, process count, output size, and wall time.
- Do not commit `.env*`, secrets, downloaded/user designs, source packs, or generated artifacts.
- Maintain NopSCADlib upstream metadata and GPL notices if work touches the vendored tree.
- Preserve one manifest record per physical occurrence even if the evidence model deduplicates shared geometry definitions.

## Success Criteria for the Plan

- Define a bounded Sprint 0001 implementation slice and explicitly retain later priorities as follow-on work rather than silently dropping them.
- Identify schemas, service boundaries, CLI/MCP contracts, migrations/versioning, artifact/provenance behavior, security bounds, and tests in enough detail for implementation without architectural guesswork.
- Include a synthetic organizer-like acceptance fixture and machine-checkable expected observations/contradictions.
- Require deterministic, evidence-linked outputs and honest confidence classifications.
- Require `make check`; add `make integration` if engine/container execution changes; add `make web-check` and desktop/mobile screenshot review only if UI work is included.
- Include documentation updates and sprint-ledger synchronization.

## Planner Questions

1. Is Sprint 0001 best bounded to P0 plus the minimal P1 vertical slice, with P2–P5 preserved as a sequenced roadmap?
2. What exact distinction and versioning boundary should exist among `SourceBundle`, `SpatialEvidenceGraph`, and an approved `AssemblyLintSpec`?
3. Which geometry observations can be deterministic in the first slice without introducing a heavyweight geometry kernel?
4. How should local-file ingestion, optional remote acquisition, parser sandboxing, and content-addressed artifacts share responsibility?
5. What CLI/MCP names and result schemas make each reasoning step composable by an agent while avoiding tools that claim more certainty than they can support?
6. What is the smallest synthetic fixture that faithfully exercises the organizer conclusions without storing or adapting the third-party model?
