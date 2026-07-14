# Assembly linting contract

This is the required workflow for agents checking an existing or externally sourced assembly.
The semantic manifest is authoritative. Downloaded STEP/STL files, screenshots, renders, and lint
reports are evidence or derivatives; they are not a substitute for the manifest and do not belong
in source control.

## Choose the correct SeeCAD path

| Job | Use | Do not use as a substitute |
| --- | --- | --- |
| Generate or revise constructive geometry | `DesignSpec`, immutable revisions, compile, analyze | Assembly lint manifest |
| Inventory an existing assembly, identify fasteners, or check driver access | `seecad lint` and `AssemblyLintSpec` | `DesignSpec`, mesh component count, or SCAD compilation |
| Check a compiled mesh's topology or bounded DFM evidence | `seecad analyze` | Assembly lint |

Two similarly named concepts have different semantics:

- `DesignSpec.tool_access_channels` are component-targeted negative features. The SCAD generator
  intersects them with owned positive volume and subtracts them during the one consolidated
  negative-space pass.
- `AssemblyLintSpec.tool_access_cones` are non-mutating driver approach envelopes. The linter
  checks them against declared part AABBs and never creates or removes geometry.

Never convert one into the other implicitly.

## Thirty-second agent workflow

Start from the checked schema and reference rather than inventing fields:

```sh
uv run seecad lint-schema > /tmp/seecad-assembly-lint.schema.json
uv run seecad lint examples/6dof_robot_arm/assembly.json
uv run seecad lint examples/6dof_robot_arm/assembly.json --format text
```

For a new assembly:

1. Gather the source file list, assembly diagram, BOM, fastener labels, and tool information.
2. Create a manifest beside the maintained example or in the user-requested output location.
3. Expand every physical instance into its own `parts` record.
4. Record source-backed facts separately from inferred or assumed facts.
5. Add a conservative millimetre AABB for every instance in one assembled coordinate system.
6. Add fastener identity metadata and at least one linked tool cone for every fastener.
7. Run JSON output first. Fix schema errors, missing cones, and possible obstructions.
8. Read the text output once so the inventory and fastener/cone mapping are easy to audit.

The linter does not need the SeeCAD service, database, OpenAI key, Docker, or OpenSCAD. It does not
create revisions or generated artifacts.

## Minimum manifest

Every position, length, diameter, and clearance is in the explicitly declared `mm` unit; the
approach axis is dimensionless:

```json
{
  "schema_version": "1.0",
  "name": "Bracket inspection",
  "intent": "Inventory the bracket stack and check driver access.",
  "units": "mm",
  "parts": [
    {
      "id": "bracket",
      "name": "Printed bracket",
      "kind": "part",
      "purpose": "Support the cover",
      "source_file": "bracket.stl",
      "envelope": {
        "minimum": {"x": -20, "y": -15, "z": -5},
        "maximum": {"x": 20, "y": 15, "z": 0}
      }
    },
    {
      "id": "cover_screw_1",
      "name": "Cover screw 1",
      "kind": "fastener",
      "purpose": "Retain the cover",
      "part_number": "M3x10",
      "envelope": {
        "minimum": {"x": -1, "y": -1, "z": 0},
        "maximum": {"x": 1, "y": 1, "z": 5}
      },
      "fastener": {
        "designation": "M3x10 socket-head screw",
        "drive": "2.5 mm hex key",
        "confidence": "exact",
        "basis": "Specified by the assembly BOM."
      }
    }
  ],
  "tool_access_cones": [
    {
      "id": "cover_screw_1_driver",
      "name": "Cover screw 1 driver approach",
      "fastener_id": "cover_screw_1",
      "tip": {"x": 0, "y": 0, "z": 5},
      "axis": {"x": 0, "y": 0, "z": 1},
      "reach_mm": 50,
      "tool_diameter_mm": 5,
      "clearance_mm": 0.75,
      "approach_half_angle_degrees": 2,
      "tool": "2.5 mm hex key",
      "rationale": "Approach the exposed drive from above."
    }
  ],
  "assumptions": []
}
```

`uv run seecad lint-schema` is the normative field/type reference. This document explains how an
agent must populate those fields.

## Part inventory rules

- One record means one physical instance. Four identical screws require four IDs and four part
  records. There is intentionally no quantity field.
- IDs are stable semantic handles. Use names such as `shoulder_screw_1`, not source-list positions
  such as `item_7`.
- `kind` is one of `part`, `stock`, `connector`, or `fastener`.
- `part_number` identifies a purchased or repeated family. `source_file` identifies the source CAD
  family. The report groups families by `part_number`, then `source_file`, then `name`.
- `minimum` and `maximum` are a conservative axis-aligned bounding box in the shared assembled
  coordinate system. Every maximum must exceed its minimum.
- The envelope must contain the whole instance. An undersized envelope can create a false clear;
  a deliberately conservative envelope can create a false obstruction.
- Print-layout variants, duplicate file formats, and shifted copies of the same source geometry are
  not additional physical instances unless the assembly actually contains another part.

The report's inventory and family counts are exact with respect to these declarations. They do not
prove that the source CAD was completely or correctly transcribed.

## Fastener identity rules

Every part with `kind: "fastener"` must contain:

- `designation`: thread and length when known, such as `M3x10 socket-head screw`;
- `drive`: the required tool or an explicitly marked assumption;
- `confidence`: `exact`, `bounded`, `heuristic`, or `unavailable`; and
- `basis`: the BOM, drawing label, measurement, source image, or inference supporting the claim.

Do not silently turn common hardware convention into source fact. For example, if an illustration
labels `M3x10` but does not state the drive, record `2.5 mm hex key (assumed)`, use `heuristic`, and
explain the split in `basis` and top-level `assumptions`.

## Tool cone rules

A tool cone describes the swept driver envelope for one approach:

- `fastener_id` links to exactly one declared fastener.
- `tip` is the drive engagement point or plane in assembly coordinates.
- `axis` points outward from the fastener along the tool's approach. It need not be normalized, but
  it must be non-zero; the linter normalizes it.
- `reach_mm` is the finite approach length to check.
- `tool_diameter_mm` is the working tool envelope at the tip.
- `clearance_mm` adds radial handling clearance.
- `approach_half_angle_degrees` expands the envelope with distance to represent angular approach
  freedom or handle/wrist sweep.
- `tool` names the driver, socket, wrench, probe, or other service tool.
- `rationale` explains why this approach is intended to work.

Every fastener needs at least one valid cone. Declare alternative approaches as separate cones.
The target fastener itself is excluded from its cone check; every other declared part and fastener
is eligible to be a blocker. There is no broad ignore list that can silently hide interference.

## Accessibility algorithm and trust level

For each cone, the linter:

1. normalizes the declared axis;
2. finds each part AABB's axial overlap with the finite cone;
3. computes the maximum cone radius across that overlap from tool radius, clearance, and half-angle;
4. conservatively tests the overlapped axis segment against the expanded AABB; and
5. reports every possibly intersecting part ID.

This is a bounded, conservative test over semantic AABB proxies. It is designed to prefer a false
obstruction over accepting an obvious blocked path. It does not inspect holes, pockets, exact
curved surfaces, flexible tools, assembly sequence, or motion through changing joint poses.

`clear` means only: no non-target declared envelope possibly intersected this declared cone under
the bounded proxy test. It does not mean physical access is guaranteed.

## Report and exit contract

JSON is the default because it is the agent/automation surface. It contains:

- `parts`: the complete instance register, including envelopes and fastener metadata;
- `part_families`: grouped family keys, instance IDs, and counts;
- `fasteners`: identity, confidence/basis, linked cones, and aggregate accessibility;
- `tool_access_cones`: complete cone geometry/tool metadata, status, blockers, and check basis;
- `diagnostics`: stable codes, severity, confidence, message, and structured evidence;
- `assumptions` and `limitations`; and
- `summary`: pass/fail and all inventory/accessibility/diagnostic counts.

Fastener accessibility is aggregated across alternatives:

- `clear`: at least one valid cone is clear;
- `blocked`: all valid cones have possible obstructions; and
- `unchecked`: the fastener has no valid linked cone.

| Condition | Diagnostic | Severity / confidence |
| --- | --- | --- |
| Cone references an unknown part | `tool_cone_unknown_fastener` | error / exact |
| Cone references a non-fastener | `tool_cone_target_not_fastener` | error / exact |
| Cone may intersect another envelope | `tool_cone_possible_obstruction` | warning / bounded |
| Fastener has no valid cone | `fastener_missing_tool_cone` | error / exact |
| All valid approaches may be blocked | `fastener_not_tool_accessible` | error / bounded |

Exit codes are stable:

- `0`: no diagnostic reached the configured threshold;
- `1`: at least one error, or any warning with `--fail-on warning`; and
- `2`: unreadable/schema-invalid input or an invalid CLI option.

A report may have overall `pass` with a warning when one approach is possibly blocked but another
approach is clear. Use `--fail-on warning` when that should stop automation.

## Reference fixture

[The 6DoF robot-arm manifest](../examples/6dof_robot_arm/assembly.json) is the checked example. Its
[fixture notes](../examples/6dof_robot_arm/README.md) explain which facts come from the source and
which tool/placement details are heuristic. It demonstrates:

- repeated physical instances with separate IDs;
- family grouping without quantity fields;
- purchased bearings and servos alongside printed parts;
- explicit M2.5, M3, and M4 fastener records;
- one linked cone per fastener; and
- a passing report that remains explicitly bounded rather than guaranteed.

## Deliberate problem fixtures

Three checked synthetic manifests exercise supported failure modes without
committing source CAD or generated lint reports:

- [Blocked top-cover fastener](../examples/blocked_top_cover_fastener/README.md) has one FDM
  sensor-pod screw whose only declared approach may intersect a cable bridge.
- [Blocked alternative approaches](../examples/blocked_alternative_approaches/README.md) gives a
  CNC fixture bolt two approaches; both may intersect separately named installed hardware.
- [Mixed service-panel access](../examples/mixed_service_panel_access/README.md) expands two
  repeated screws and shows that one clear instance does not hide its blocked sibling.

Each manifest is schema-valid, declares millimetres, expands every physical
instance, and gives every fastener at least one cone. Their expected failures
are bounded tool-access findings. They are not minimum-wall examples: the mesh
analyzer currently labels minimum wall thickness `unavailable`, and the
assembly manifest does not model manufacturing process or local wall geometry.

## Agent definition of done

Before claiming an assembly-lint task complete, verify all of the following:

- [ ] The manifest declares schema `1.0` and `units: "mm"`.
- [ ] Every physical instance has its own stable part ID and conservative envelope.
- [ ] Repeated parts and fasteners are expanded, not represented by quantity.
- [ ] Every fastener has designation, drive, confidence, and evidence basis.
- [ ] Every fastener has at least one valid linked tool cone.
- [ ] Cone axes point outward and all tool dimensions are explicit millimetres.
- [ ] Source facts, inferences, and assumptions are visibly separated.
- [ ] Default JSON output was inspected and its exit code recorded.
- [ ] Text output was read for inventory and mapping sanity.
- [ ] `clear`/`pass` is described as bounded, never as physical proof.
- [ ] No downloaded CAD, source PDF/image, user design, or generated lint output was committed.
- [ ] Repo changes pass `make check`; engine/container and UI gates apply only if those areas changed.

Implementation lives in `src/seecad/assembly_lint.py`, CLI routing in `src/seecad/cli.py`, and the
regression contract in `tests/test_assembly_lint.py`.
