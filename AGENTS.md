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

## Verification

Run `make check` for normal changes. Engine or container changes also require `make integration`. UI changes require `make web-check` and a browser screenshot review at desktop and mobile widths.
