# Standalone mesh linting

`seecad mesh-lint` gives agents a read-only topology and print-orientation preflight for one
triangle mesh. It is for an individual printable or machinable body whose unitless coordinate
values are millimetres or whose format carries explicit convertible unit metadata. The mesh remains
a derived representation; linting it does not create or replace semantic design intent.

This workflow must not be used to inspect an existing or multi-part assembly. Multiple mesh shells
do not reliably identify physical instances, fasteners, interfaces, or assembly relationships. Use
the mandatory [assembly-lint workflow](ASSEMBLY-LINT.md) for every assembly request.

## Agent workflow

1. Confirm that the input is one mesh. For unitless formats, confirm that coordinate values are
   millimetres. Do not infer units from scale or filename. Explicit embedded units such as GLB's
   metres are deterministically normalized and recorded by the report.
2. Produce a print-profile JSON file. The checked example is
   [`examples/mesh_lint/fdm-profile.json`](../examples/mesh_lint/fdm-profile.json); the current
   schema is available from `uv run seecad mesh-lint-profile-schema`.
3. Run the machine-readable report:

   ```bash
   uv run seecad mesh-lint MODEL.stl \
     --units mm \
     --profile examples/mesh_lint/fdm-profile.json
   ```

4. Repeat with `--format text` for review. Add `--fail-on warning` when topology warnings such as
   disconnected components or degenerate triangles must fail automation.
5. Treat an exit status of `0` as “no finding reached the selected threshold,” not as proof that
   the part can be manufactured. Exit `1` means a lint finding reached the threshold. Exit `2`
   means the mesh, profile, units declaration, scene scope, or CLI options were invalid.

The command accepts STL, OBJ, PLY, OFF, GLB, and 3MF files up to 128 MiB. It reads one local file
into memory and does not resolve network resources. A GLB or 3MF scene with multiple geometry
instances is rejected with an explicit route to `seecad lint`.

## Evidence returned

The JSON report binds every result to the input filename, byte size, format, and SHA-256 digest. It
records embedded units and the exact scale factor used to normalize the parsed representation to
millimetres. It includes the existing mesh measurements and findings plus the best requested
candidates from all 24 rigid axis-aligned rotations.

- Triangle counts, bounds, area, topology, and transformed axis-aligned extents are exact with
  respect to the parsed, millimetre-normalized triangle representation.
- Degenerate-triangle detection is bounded by the reported scale-relative numerical tolerance.
- Build-volume fit is bounded by the supplied profile and a specific reported orientation.
- The downward-overhang ratio is heuristic. It uses face normals and excludes faces lying on the
  candidate build plate, but it does not run a slicer or model bridges, support generation,
  cooling, adhesion, or variable-width extrusion.
- Minimum wall thickness remains unavailable. The command does not claim fit, manufacturability,
  structural integrity, or machine safety.

Candidate rotations are reported as `(x, y, z)` degrees, applied around X, then Y, then Z. The
ranking prefers candidates that fit the configured build volume, then lower heuristic overhang
burden, then lower build height. It never rotates, repairs, converts, or writes the source model.

## Scope boundaries

Use this command to answer questions such as:

- Is this one mesh watertight and consistently wound?
- Does it contain disconnected shells or bounded degenerate triangles?
- Does its current orientation fit a declared printer volume?
- Which axis-aligned orientations deserve slicer review first?

Do not use it to enumerate an assembly, identify fasteners, check tool access, infer source CAD
features, certify printability, simulate CNC motion, or repair geometry. Those require semantic
assembly data, slicer/CAM evidence, a machine model, or a source-authoritative design change.
