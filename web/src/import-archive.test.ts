// @vitest-environment node

import { strToU8, zipSync } from "fflate/browser";
import { describe, expect, it } from "vitest";

import {
  extractZipArchive,
  materialLibraryReferences,
  normalizeArchivePath,
  resolveArchiveReference,
} from "./import-archive";

describe("import archive", () => {
  it("extracts OBJ and material entries without changing source bytes", () => {
    const compressed = zipSync({
      "assembly/model.obj": strToU8("mtllib model.mtl\no bracket\nv 0 0 0\n"),
      "assembly/model.mtl": strToU8("newmtl steel\nKd 0.5 0.5 0.5\n"),
    });
    const archive = extractZipArchive("assembly.zip", compressed);

    expect(archive.objectPaths).toEqual(["assembly/model.obj"]);
    expect(archive.entries.get("assembly/model.mtl")).toEqual(
      strToU8("newmtl steel\nKd 0.5 0.5 0.5\n"),
    );
  });

  it("rejects traversal and duplicate normalized paths", () => {
    expect(() => normalizeArchivePath("../outside.obj")).toThrow("unsafe path");
    expect(() => normalizeArchivePath("/absolute.obj")).toThrow("unsafe path");
  });

  it("resolves companion files inside the archive root", () => {
    expect(
      resolveArchiveReference("models/body.obj", "../materials/body.mtl"),
    ).toBe("materials/body.mtl");
    expect(() => resolveArchiveReference("body.obj", "../outside.mtl")).toThrow(
      "escapes its root",
    );
  });

  it("reads OBJ material-library declarations", () => {
    expect(
      materialLibraryReferences("mtllib color set.mtl\no sorter\n"),
    ).toEqual(["color set.mtl"]);
  });
});
