# Source observation

`seecad observe` is the first-pass orientation tool for local 3D source files. It answers
agent questions such as “what geometry records are in this bundle?”, “what are the parsed scene
nodes and transformed bounds?”, and “which SeeCAD workflow should I use next?” without creating a
design, compiling CAD, normalizing units, or writing derived geometry.

Use it before choosing between the browser preview, standalone mesh linting, and the assembly-lint
manifest workflow. It is intentionally weaker than all three: it observes source records, but it
does not decide physical meaning.

## Agent workflow

1. Run the machine-readable observation report on one or more local files or directories:

   ```bash
   uv run seecad observe SOURCE_OR_DIRECTORY
   uv run seecad observe SOURCE_OR_DIRECTORY --recursive
   ```

2. If a human or source package explicitly says the coordinate values are millimetres, record that
   declaration:

   ```bash
   uv run seecad observe SOURCE_OR_DIRECTORY --units mm
   ```

   Do not infer millimetres from filename, apparent scale, object type, or application of origin.
   If embedded source metadata conflicts with `--units mm`, the report flags a unit conflict and
   keeps the bounds labeled as `source coordinates`.

3. Repeat with `--format text` for a compact review:

   ```bash
   uv run seecad observe SOURCE_OR_DIRECTORY --format text
   ```

4. Follow the `summary.route_hint`:

   | Route hint | Meaning | Usual next step |
   | --- | --- | --- |
   | `mesh_lint_candidate` | Exactly one observed file and one parsed geometry instance. | If units are explicit millimetres, run [`seecad mesh-lint`](MESH-LINT.md). |
   | `assembly_evidence_review` | More than one observed file or parsed geometry instance. | Visually preview if needed, then draft/review an `AssemblyLintSpec` before [`seecad lint`](ASSEMBLY-LINT.md). |
   | `no_supported_geometry` | No supported geometry was parsed. | Find a supported source file or use an external CAD conversion/review step. |

The command accepts the same triangle source formats as mesh linting: STL, OBJ, PLY, OFF, GLB, and
3MF. Files are read locally, bounded to 128 MiB each, and never resolved through network resources.
Directory inputs are shallow by default; add `--recursive` deliberately. The default file limit is
64 and can be adjusted with `--file-limit`.

The MCP surface exposes the same report shape through `observe_source_payloads`. MCP callers pass
an array of objects with `filename` and base64 `content_base64` fields, plus optional
`declared_units: "mm"`. It intentionally does not accept arbitrary server-side paths. This keeps
remote agents explicit about the bytes being observed while preserving the CLI's convenient local
path workflow.

## Evidence returned

The JSON report includes one record per local file considered. Supported files include the local
path, byte size, SHA-256 digest, parsed format, unit evidence, and every parsed geometry instance.
Unsupported files are still named, sized, and hashed when they fit the byte limit, but no geometry
claims are made for them.

For each geometry instance, the report includes:

- scene node and geometry names when the parser exposes them;
- the 4 x 4 parsed scene transform;
- triangle and vertex counts;
- transformed source-coordinate AABB minimums, maximums, and extents.

These facts are exact only with respect to the parsed triangle representation and scene graph. The
bounds become millimetre bounds only when source units are explicitly declared or embedded metadata
provides that label. The command does not scale, rotate, repair, combine, or export the source.

## Scope boundaries

Use `seecad observe` to move quickly from an opaque source pack to a small evidence map:

- Which files are supported by SeeCAD's local parsers?
- Does this GLB or 3MF contain one visible mesh instance or several scene nodes?
- What source-coordinate AABBs should I copy into a reviewed assembly manifest?
- Is a single-file input likely ready for mesh lint once millimetres are explicit?

Do not use it to enumerate physical parts, identify fasteners, infer mating interfaces, check tool
access, claim assembly fit, or produce a bill of materials. OBJ objects, material groups, scene
nodes, geometry records, and disconnected shells are not a physical-instance inventory. When the
user asks for assembly inspection, fastener identification, error checking, or tool accessibility,
create a reviewed schema-`1.0` `AssemblyLintSpec` and run the mandatory assembly-lint workflow.

`seecad observe` also does not substitute for topology linting. If the source is one standalone
mesh with explicit millimetres, `seecad mesh-lint` is still the tool that checks watertightness,
winding, disconnected components, degenerate triangles, bounded build-volume fit, and heuristic
orientation candidates.
