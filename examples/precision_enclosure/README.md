# Precision enclosure reference fixture

This fixture is a complete, parameterised OpenSCAD enclosure for a nominal
54 x 32 mm sensor/controller board. It demonstrates SeeCAD's intended modelling
discipline: semantic material features are built in `positive_volume()`, named
holes and access passages are collected in `negative_space()`, and one final
`difference()` applies all negative space at once.

The model uses the vendored NopSCADlib for rounded plates, corrected printable
holes, support-free horizontal teardrops, slots, and the `F1BM3` heat-set insert
profile. `intent.json` is the authoritative reviewable description of purpose,
dimensions, features, evidence classes, and non-guarantees.

## Parts

- `part="base"` (default): printable enclosure body.
- `part="lid"`: printable lid, automatically flipped onto its broad face.
- `part="assembly"`: fitted design view; set `explode` in millimetres to lift
  the lid for inspection.
- `part="print_layout"`: base and flipped lid next to each other on the bed.

## Bounded compile commands

The commands below use the prebuilt `seecad-openscad:local` image, keep the
source read-only, disable networking and capabilities, bound runtime resources,
and write derivatives only to `/tmp`.

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
  -o /out/precision-enclosure-base.stl \
  -D 'part="base"' \
  /src/examples/precision_enclosure/precision_enclosure.scad
```

Replace the last output and selector with
`-o /out/precision-enclosure-lid.stl -D 'part="lid"'` for the lid.

For an exploded evidence render:

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
  -o /out/precision-enclosure-assembly.png \
  --imgsize=1200,900 \
  --viewall \
  --autocenter \
  --projection=ortho \
  --colorscheme=Tomorrow \
  -D 'part="assembly"' \
  -D 'explode=12' \
  /src/examples/precision_enclosure/precision_enclosure.scad
```

STL compilation proves that OpenSCAD accepted and rendered the CSG. It does not
prove fit, strength, printability, ingress protection, thermal performance, or
electrical safety. Those remain bounded or heuristic checks as labelled in
`intent.json`.
