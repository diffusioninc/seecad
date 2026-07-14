# Blocked alternative approaches problem fixture

This synthetic CNC workholding assembly gives `clamp_bolt` two separately
declared service approaches. The straight hex-key approach meets the
`fixed_splash_guard`; the diagonal ball-end approach meets the `vise_column`.
Because every declared alternative is possibly obstructed, the fastener is
reported as blocked.

The manifest is authoritative for this fixture. No source CAD or generated
lint report is checked in.

```sh
uv run seecad lint examples/blocked_alternative_approaches/assembly.json
uv run seecad lint examples/blocked_alternative_approaches/assembly.json --format text
```

Both commands should exit `1`. The report should contain two bounded
`tool_cone_possible_obstruction` warnings and one bounded
`fastener_not_tool_accessible` error for `clamp_bolt`.

This example does not check minimum feature size or prove machining
feasibility. It exercises alternative assembly tool-access envelopes only.
