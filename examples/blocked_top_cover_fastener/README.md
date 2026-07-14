# Blocked top-cover fastener problem fixture

This synthetic FDM sensor-pod assembly contains one M3 mounting screw. Its
only declared upward driver approach crosses the conservative envelope of the
installed `cable_bridge`, so the assembly linter should report the screw as
blocked.

The manifest is authoritative for this fixture. No source CAD or generated
lint report is checked in.

```sh
uv run seecad lint examples/blocked_top_cover_fastener/assembly.json
uv run seecad lint examples/blocked_top_cover_fastener/assembly.json --format text
```

Both commands should exit `1`. The report should contain a bounded
`tool_cone_possible_obstruction` warning naming `cable_bridge` and a bounded
`fastener_not_tool_accessible` error for `rear_mount_screw`.

This example does not test wall thickness or prove exact physical
interference. It exercises the bounded assembly tool-access check only.
