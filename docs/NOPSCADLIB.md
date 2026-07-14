# Vendored NopSCADlib

The complete upstream tracked tree is stored at `vendor/NopSCADlib`. See
`vendor/NopSCADlib.UPSTREAM.json` for the pinned commit and fetch date. NopSCADlib remains
GPL-3.0-or-later, and the upstream `COPYING` file is preserved unchanged. See
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) for the boundary between SeeCAD's
MIT-licensed code and vendored third-party components.

SeeCAD exposes the library to OpenSCAD through `OPENSCADPATH=/opt/libraries`, so generated sources can use paths such as:

```scad
include <NopSCADlib/core.scad>
use <NopSCADlib/utils/rounded_cylinder.scad>
```

Do not edit vendored files in place. Update by replacing the complete tree from a reviewed upstream revision, then update the provenance record and run the engine integration suite.

Human and API-authored `DesignSpec` values may use the audited `library_call` model. The
OpenAI planner has a narrower surface: it can select only the semantic
`nop_rounded_rectangle`, `nop_rounded_cylinder`, `nop_poly_cylinder`, `nop_teardrop`,
`nop_teardrop_plus`, and `nop_tearslot` shape kinds. SeeCAD deterministically maps those
kinds to fixed audited paths, modules, and signatures; the model never supplies library
paths, module names, argument lists, or raw SCAD.
