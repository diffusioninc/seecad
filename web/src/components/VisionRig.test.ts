import { describe, expect, it } from "vitest";
import { deriveSharedMeshTransform } from "./VisionRig";

describe("deriveSharedMeshTransform", () => {
  it("derives one transform from the active mesh without normalizing the baseline", () => {
    const transform = deriveSharedMeshTransform({
      min: { x: 10, y: -2, z: 4 },
      max: { x: 30, y: 8, z: 9 },
    });

    expect(transform.scale).toBeCloseTo(0.24);
    expect(transform.position).toEqual([-4.8, -0.72, -1.56]);

    // Both meshes receive this exact group transform, so a baseline vertex at
    // x=40 remains visibly displaced instead of being independently centered.
    expect(40 * transform.scale + transform.position[0]).toBeCloseTo(4.8);
  });
});
