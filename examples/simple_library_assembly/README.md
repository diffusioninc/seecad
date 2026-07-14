# Simple library assembly

This example is a small bridge plate fastened across two parallel 100 mm
lengths of 20 x 20 mm T-slot extrusion. It deliberately stays simple while
showing how a SeeCAD design can combine one custom printable part with standard
parts from the pinned NopSCADlib tree.

All dimensions are millimetres. `intent.json` is the semantic authority;
`simple_library_assembly.scad` is a reproducible reference realisation.

## Library parts

- Two `E2020` aluminium extrusions.
- Four `M4_cap_screw` fasteners with standard M4 washers.
- Four `M4_sliding_t_nut` nuts in the upper extrusion slots.
- NopSCADlib `rounded_rectangle()` and `poly_cylinder()` geometry for the
  printable bridge plate and its M4 clearance holes.

The T-nut locations are nominal visual placements. Slot engagement, screw
length, preload, fit, load transfer, manufacturability, and structural integrity
are not guaranteed and require physical review.

## Selectors

- `part="assembly"` (default): fitted assembly.
- `part="plate"`: printable bridge plate only.
- `part="print_layout"`: the bridge plate placed on the print bed.
- `separation=12`: exploded assembly view, with the plate and screws lifted by
  the requested distance in millimetres.

## Bounded render

Build the pinned worker with `make worker`, then render an exploded inspection
view without network access or host capabilities:

```sh
docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 64 \
  --memory 512m \
  --cpus 2 \
  --ulimit fsize=134217728:134217728 \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --tmpfs /home/seecad:rw,noexec,nosuid,size=16m,uid=10001,gid=10001 \
  --mount type=bind,src="$PWD",dst=/src,readonly \
  --mount type=bind,src=/tmp,dst=/out \
  seecad-openscad:local \
  -o /out/simple-library-assembly.png \
  --imgsize=1200,900 \
  --viewall \
  --autocenter \
  --projection=ortho \
  --colorscheme=Tomorrow \
  -D 'part="assembly"' \
  -D 'separation=12' \
  /src/examples/simple_library_assembly/simple_library_assembly.scad
```

OpenSCAD acceptance and a clean render show that the CSG and library calls are
valid. They do not establish physical fit, strength, printability, or safe use.
