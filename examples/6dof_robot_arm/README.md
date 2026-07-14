# 6DoF robot-arm assembly lint fixture

This fixture turns the published module illustration for
[6DoF robot arm | modular | cheap | educational](https://www.printables.com/model/971320-6dof-robot-arm-modular-cheap-educational)
into a semantic assembly register that can be checked without downloading or
executing source CAD. It is the reference implementation of the
[assembly linting contract](../../docs/ASSEMBLY-LINT.md).

All coordinates and dimensions are explicitly millimetres. `assembly.json` is
the semantic authority. It declares one physical instance per `parts` entry,
groups repeated instances by `part_number` or `source_file` in the report, and
links each fastener instance to a finite tool cone.

The source illustration identifies these module fasteners:

- Base: one M2.5x20 fastener.
- Small drive: two M3x10 servo fasteners and one M2.5x16 rotor fastener.
- Big drive: two M4x10 and two M4x18 servo fasteners, plus one M3x20 rotor
  fastener.
- Module connections: additional M3 fasteners of varying lengths, mostly
  M3x10.

It also describes each intermediate drive module as two printed parts, one
20x32x7 mm bearing, one MG90S or MG996R servo, and bolts; the base uses two
bearings. The download contains nine STEP files. The shifted straight-connector
STL is treated as a print-layout variant, not another physical part.

The page does not publish a machine-readable fitted assembly or identify the
fastener drive tools. This fixture therefore covers one base module, one small
drive module, one big drive module, and the illustrated connector set rather
than claiming to be the exact pictured 6DoF build BOM. The AABBs are deliberately
simple inspection proxies. Hex-key sizes and approach directions are labeled
heuristic assumptions in the manifest.

Run the agent-oriented JSON report:

```sh
uv run seecad lint examples/6dof_robot_arm/assembly.json
```

Or render the same complete report for a human:

```sh
uv run seecad lint examples/6dof_robot_arm/assembly.json --format text
```

Exit status is `0` when no errors are found, `1` when the selected lint
threshold is reached, and `2` for an unreadable or schema-invalid manifest.
Tool accessibility is a bounded, conservative envelope check. It does not prove
physical access, fit, thread engagement, manufacturability, or structural
integrity.
