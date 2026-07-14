# Proof sheets

Proof sheets are an explicit visual-review mode for a compiled SeeCAD revision. They pre-compute a
large, deterministic catalog of orthographic 2D projections so a reviewer can scan the same mesh
from broadly distributed points of view and look for possible unintended interactions.

They never run during create, revise, compile, or analyze. A person or agent must deliberately call
the proof-sheet operation.

## Scope and routing

Proof sheets operate on the STL derivative of one semantic `DesignSpec` revision. The design still
declares `units: "mm"`, and the manifest records `units: "mm"` without inferring or rescaling the
mesh.

Proof sheets do not replace either inspection workflow:

- Existing, downloaded, imported, or multi-part assemblies must use
  [assembly lint](ASSEMBLY-LINT.md). A fused STL projection cannot recover physical instances,
  fastener identity, relationships, or conservative tool envelopes.
- One standalone imported mesh may use [mesh lint](MESH-LINT.md). Proof sheets are available only
  on a compiled SeeCAD revision; they are not an alternate mesh-ingest path.

## Invocation

The default invocation renders 2,048 projections at 96 by 96 pixels and groups them into 32 review
sections of 64 views:

```bash
uv run seecad proof-sheets DESIGN_ID REVISION_ID
```

The command may compile an STL child first. Disable that behavior when automation must require an
already compiled input:

```bash
uv run seecad proof-sheets DESIGN_ID REVISION_ID --no-auto-compile
```

The API operation is similarly explicit:

```bash
curl --fail-with-body -X POST \
  http://localhost:8000/v1/designs/DESIGN_ID/revisions/REVISION_ID/proof-sheets \
  -H 'content-type: application/json' \
  -d '{"auto_compile":true,"view_count":2048,"resolution_px":96,"views_per_sheet":64}'
```

The workbench exposes `Generate proof sheets` as a separate action. After generation the action
becomes `Review proof sheets`; it does not turn proof sheets into a compile or analysis default.

## Deterministic viewpoint catalog

The first 26 projections are the six datum axes, eight corners, and twelve edge diagonals. Remaining
camera directions use a deterministic spherical Fibonacci distribution. Cameras are orthographic
with a fixed roll convention. Allowed requests are bounded to 1,024 through 4,096 views, 64 through
192 pixels per projection, and review-section sizes divisible by eight.

The renderer parses the already compiled STL without executing source CAD, making network calls, or
mutating the mesh. It projects a deterministic, bounded surface sample into a depth image. That
keeps the operation reproducible and output-bounded, but it also makes the visual evidence
heuristic: small, internal, occluded, or sub-pixel interactions can be missed.

## Immutable outputs

One invocation creates an immutable child revision with three content-addressed roles:

| Role | File | Purpose |
| --- | --- | --- |
| `proof_sheet_manifest` | `proof-sheet-manifest.json` | View directions, projection hashes, renderer bounds, mesh digest, and limitations. |
| `proof_sheets` | `proof-sheets.html` | Self-contained human review surface with every projection embedded. |
| `proof_sheet_archive` | `proof-sheets.zip` | Offline index, manifest, and individual PNG projections. |

The manifest binds every projection to the compiled STL SHA-256. Repeating the same operation on the
same mesh and configuration returns the existing matching child rather than creating mutable state.
Generated proof-sheet artifacts are derivatives and must not be committed.

## Evidence boundary

The camera vectors, projection count, file bytes, and hashes are exact with respect to the recorded
algorithm and mesh. The interpretation of the images is heuristic. Proof sheets can reveal a reason
to inspect or revise geometry; they cannot establish the absence of an interaction.

A clear-looking projection is never proof of collision clearance, assembly fit, tool access, thread
engagement, preload, manufacturability, or structural integrity. Generating sheets also does not
record that a human reviewed them. Human approval remains a separate immutable operation with its
own statement and evidence chain.
