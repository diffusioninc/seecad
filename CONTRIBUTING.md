# Contributing

Use Python 3.12, `uv`, Node 24+, `pnpm`, and Docker. Run `make bootstrap` once and `make check` before submitting a change. Engine changes also require `make integration`.

Design changes must preserve the positive-volume / consolidated-negative-space invariant. New manufacturability checks need a declared trust level, machine-readable evidence, a remediation, and fixtures for both passing and failing geometry.

Generated files, local designs, API keys, and `.seecad` artifacts do not belong in Git.
