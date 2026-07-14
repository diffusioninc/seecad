# Mixed service-panel access problem fixture

This synthetic gearbox panel expands two identical M4 screws into separate
physical instances. The `installed_cable_tray` obstructs the left screw's
declared approach while the right screw retains a clear bounded approach. The
assembly still fails because one required fastener is inaccessible.

The manifest is authoritative for this fixture. No source CAD or generated
lint report is checked in.

```sh
uv run seecad lint examples/mixed_service_panel_access/assembly.json
uv run seecad lint examples/mixed_service_panel_access/assembly.json --format text
```

Both commands should exit `1`. The report should show one accessible and one
blocked fastener, name `installed_cable_tray` as the bounded blocker, and emit
`tool_cone_possible_obstruction` plus `fastener_not_tool_accessible`.

The clear right-side approach is not proof of physical access, fit, preload,
manufacturability, or structural integrity.
