# G-code evidence adapter

G-code reasoning is a planned evidence source, not a substitute for geometric checks. The adapter boundary is defined now so slicer and motion evidence can join a revision without becoming the design authority.

## Proposed inputs

- immutable G-code artifact and SHA-256 digest;
- slicer name, version, profile digest, printer kinematics, nozzle, material, and layer height;
- source mesh digest that the slicer consumed;
- optional preview images and time/material estimates.

## First analyses

- parse motion, extrusion, temperatures, tool changes, comments, and layer boundaries;
- reconstruct per-layer paths and swept extrusion envelopes;
- flag travel through printed volume, unsupported starts, extreme bridges, retractions, tiny segments, and machine-bound violations;
- compare declared holes, clearances, and tool-access channels with sliced paths;
- render a layer contact sheet suitable for multimodal review.

## Trust boundary

G-code can reveal how a slicer interpreted a mesh, but it cannot prove adhesion, material quality, machine calibration, load capacity, or safe operation. Findings will be exact only for parsed commands, bounded for machine/profile constraints, and heuristic for print outcome.
