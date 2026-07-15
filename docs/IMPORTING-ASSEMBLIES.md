# Imported assembly preview

SeeCAD's imported assembly preview opens local OBJ geometry for visual review without converting it
into semantic design intent. Open `/import.html` in the running workbench and choose one ZIP, or
choose an OBJ together with its MTL and image textures. The files are decompressed and parsed in
the browser tab; they are not uploaded, persisted, compiled, analyzed, or added to revision history.

## Agent routing heuristic

Classify the request by the authority the user needs, not by the file extension:

| User intent | Route | Trust boundary |
| --- | --- | --- |
| Orient around a local source pack before choosing a workflow | [`seecad observe`](SOURCE-OBSERVATION.md) | Read-only source records, parsed scene nodes, AABBs, unit evidence, and route hints |
| Open, display, orbit, or visually review an existing OBJ assembly | `/import.html` | Read-only visual preview; source units may remain undeclared |
| Inventory an assembly, identify fasteners, lint relationships, or check tool access | [`seecad lint`](ASSEMBLY-LINT.md) | Exact to the manifest; tool cones are bounded |
| Check topology or print orientation for one standalone mesh | [`seecad mesh-lint`](MESH-LINT.md) | Exact/bounded/heuristic mesh evidence with explicit units |
| Generate or revise authoritative constructive geometry | `DesignSpec` and immutable revisions | Semantic design intent is authoritative |

Use `seecad observe` first when an agent needs a quick source-file inventory, parsed scene-node
list, transformed AABBs, or next-route hint. Use the preview path when the request is only to open
or display downloaded CAD. Do not ask for units merely to render it. Keep the coordinate values
unitless in labels and show
`source units undeclared`. If the human explicitly confirms that the source coordinates are
millimetres, the preview may label the same unscaled values as millimetres. That declaration applies
only to the current preview; it does not create a design, manifest, or analysis record.

Never infer units from scale, filename, application of origin, or apparent object type. Never use
an OBJ object record, material group, disconnected shell, or mesh component as a physical-instance
inventory. Those groups are exact only with respect to parsing the selected files.

## Why this path wins

The import path was chosen after comparing the practical alternatives:

| Attempt | Result | Decision |
| --- | --- | --- |
| Standalone OBJ-to-GLB viewer | Preserved the visual result and material colors, but lived outside SeeCAD and duplicated workbench behavior | Useful fallback, not the product path |
| Flatten OBJ to STL and open the compiled-mesh rig | Displayed triangles but discarded material groups and assembly separation; also looked like a generated SeeCAD artifact | Do not use as the default |
| Force imported geometry into `DesignSpec` | Would invent semantic intent, constructive history, units, and revision provenance | Prohibited |
| Run `mesh-lint` on the assembly | Requires an explicit unit declaration and cannot establish physical instances or relationships | Wrong workflow |
| Browser-local OBJ/MTL preview inside SeeCAD | Preserves source colors and visual grouping, makes no authority claims, creates no repo artifact, and needs no server upload | Preferred |

The preview defaults to a labeled `Z up · CAD heuristic` viewing transform because OBJ does not
carry an up-axis convention. A reviewer can switch to Y-up without modifying the source. This is a
display transform only; source-coordinate bounds are computed before it and remain unchanged.

## Safety and scope

The browser importer accepts one ZIP up to 50 MiB compressed, at most 256 entries, at most 64 MiB
per entry, and at most 128 MiB expanded. It rejects encrypted files, ZIP64, duplicate normalized
paths, absolute paths, and path traversal before decompression. Imported source and generated
preview state remain ephemeral and must not be committed.

The preview does not prove physical instances, fit, access, thread engagement, preload,
manufacturability, or structural integrity. When a display request turns into an inspection
request, stop using visual groups as evidence and route to the assembly manifest workflow.

## Operator checklist

1. Start the workbench with `make web` and open `http://localhost:5173/import.html`.
2. Choose the local ZIP or the related OBJ, MTL, and texture files together.
3. Confirm the source name, parsed visual-group counts, triangle count, and unit status.
4. Use the default Z-up view only as a labeled heuristic; switch to Y-up if the orientation is wrong.
5. Leave millimetres unchecked unless the source or human explicitly declares them.
6. If the user asks for inventory, fasteners, relationships, errors, or tool access, read
   `docs/ASSEMBLY-LINT.md` completely and create the required manifest instead.
