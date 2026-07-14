# Assembly geometry safety

## Failure closed by schema 1.1

Schema 1.0 flattened an assembly into one positive union and one global negative union. That
made valid CSG possible even when the physical assembly was wrong. In the observed 2020 frame,
extrusion T-slot negatives crossed the whole design, carving gusset brackets and visible screw
heads. Two orthogonal gussets also occupied the same corner volume. The resulting mesh was
watertight, but watertightness only established closed mesh topology.

Schema 1.1 closes the failure at the semantic boundary:

- Every positive solid names one declared physical component.
- Every negative feature and tool-access channel names one or more target components.
- The compiler intersects each negative with the positive volume of its targets before the one
  consolidated design-level subtraction. Negative ownership is exact by construction.
- Conservative transformed AABBs for distinct component solids may touch but may not overlap by
  positive volume beyond the 0.000001 mm modeling tolerance. A crossed gusset pair is rejected
  before SCAD exists.
- Connector components declare at least two required component contacts. Fastener components
  declare at least one. Each required relationship must have bounded AABB face contact, rejecting
  obvious floating or edge-only hardware placement.
- Historical schema 1.0 revisions remain readable, but the service refuses to compile, analyze,
  or approve them again. They must first be revised into schema 1.1.
- Schema 1.1 analysis records exact negative-scope ownership, bounded component non-interference,
  and bounded required face-contact measurements, then adds an unavailable finding for physical
  fit, bearing support, preload, thread engagement, load transfer, and structural integrity.

## Trust boundary

Negative ownership is an exact semantic/compiler property. Component non-interference and contact
are bounded checks over conservative transformed AABBs. They can reject valid close-fitting curved
assemblies, and face contact does not prove actual bearing area, preload, thread engagement,
clearance, load transfer, manufacturability, or structural integrity. Those properties remain
unavailable unless a later solver reports them with its assumptions and provenance.

The conservative restriction is intentional: a multi-component assembly using a library primitive
whose bounds are not part of the audited signature is rejected. Use core primitives with known
bounds or extend the library registry with an audited bounds contract before accepting that part in
an assembly.

## Regression contract

Tests preserve the original failure shape:

- an extrusion slot geometrically crossing a touching screw head is scoped only to the extrusion;
- two crossed gusset component envelopes are rejected;
- unscoped negative space is rejected;
- a fastener lacking bounded face contact with its declared support is rejected; and
- legacy schema 1.0 geometry remains readable but cannot generate new SCAD.
