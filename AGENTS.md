# SeeCAD engineering contract

SeeCAD is an agent-native CAD reasoning and evidence system. Keep semantic design intent authoritative; generated SCAD, meshes, renders, and reports are reproducible derivatives.

## Invariants

- Every design declares millimetres explicitly. Never infer units.
- Build positive volume first, then apply one consolidated negative-space pass. Do not introduce alternating positive/negative boolean history.
- Name holes, clearances, access passages, and interfaces as semantic features.
- Every compile creates an immutable revision and content-addressed artifacts.
- Label checks as exact, bounded, or heuristic. Never present manufacturability or structural integrity as guaranteed.
- Run generated SCAD without network access, without host capabilities, with bounded CPU, memory, process count, output size, and wall time.
- Keep NopSCADlib's pinned upstream metadata and GPL notice with the vendored tree.
- Never commit `.envrc`, `.env*`, API keys, user designs, or generated artifacts.

## Assembly inspection routing (mandatory)

When a request asks to inspect, lint, error-check, inventory, identify fasteners in, or check
tool accessibility for an existing, imported, downloaded, or multi-part assembly, use the
standalone assembly-lint workflow in [docs/ASSEMBLY-LINT.md](docs/ASSEMBLY-LINT.md).
Before taking action, read that contract completely; this routing summary is not a substitute.

Do not force an existing assembly into `DesignSpec`, compile it, or substitute mesh topology
analysis for assembly linting. `DesignSpec.tool_access_channels` are component-scoped negative
features that remove material from a generated design. `AssemblyLintSpec.tool_access_cones` are
non-mutating driver approach envelopes checked against part AABBs. They are not interchangeable.

For every assembly-lint task:

1. Run `uv run seecad lint-schema` and use schema version `1.0` with `units: "mm"`.
2. Declare one `parts` record per physical instance. Expand repeated hardware into separate IDs;
   never hide instance count behind a quantity.
3. Give every part a conservative AABB in one shared assembled coordinate system.
4. Declare every fastener as `kind: "fastener"` with designation, drive, confidence, and evidence
   basis. Put uncertain source interpretation in `assumptions` and label it heuristic.
5. Give every fastener at least one linked tool cone with tip, outward approach axis, reach, tool
   diameter, clearance, half-angle, tool name, and rationale. Alternative approaches are separate
   cones.
6. Run `uv run seecad lint MANIFEST.json` for the machine-readable report and repeat with
   `--format text` for review. Use `--fail-on warning` when any possibly obstructed alternative
   must fail automation.
7. Treat enumeration and relationships as exact only with respect to the manifest. Treat cone
   accessibility as bounded and conservative. A `pass` or `clear` result is never proof of
   physical access, fit, thread engagement, preload, manufacturability, or structural integrity.

The checked reference is
[examples/6dof_robot_arm/assembly.json](examples/6dof_robot_arm/assembly.json). Preserve the
source/assumption separation demonstrated there, and never commit downloaded source CAD or lint
output.

For a single standalone mesh outside assembly scope, agents may use the read-only workflow in
[docs/MESH-LINT.md](docs/MESH-LINT.md). `mesh-lint` never satisfies an assembly inspection request:
disconnected shells are not a physical-instance inventory, and multi-instance scene files must be
routed to the assembly manifest workflow above.

For a request that only asks to open, display, orbit, or visually review imported OBJ/MTL geometry,
use the browser-local workflow in [docs/IMPORTING-ASSEMBLIES.md](docs/IMPORTING-ASSEMBLIES.md).
Keep source units undeclared until a human explicitly confirms millimetres. Treat OBJ objects,
materials, and mesh groups as visual source records only, never as a physical-instance inventory.
Do not flatten to STL or create a `DesignSpec` merely to make an imported assembly appear in the
generated-design workbench.

## Proof sheets (explicit mode only)

Use the workflow in [docs/PROOF-SHEETS.md](docs/PROOF-SHEETS.md) only when a user deliberately asks
for proof sheets or broad visual projection review of a compiled SeeCAD revision. Never generate
proof sheets implicitly during create, revise, compile, analyze, approval, mesh lint, or assembly
lint. Label the projection catalog as heuristic visual-review evidence. It never substitutes for
assembly lint, mesh lint, exact collision checks, fit verification, manufacturability analysis, or
structural analysis.

## Verification

Run `make check` for normal changes. Engine or container changes also require `make integration`. UI changes require `make web-check` and a browser screenshot review at desktop and mobile widths.
