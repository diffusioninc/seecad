import { unzipSync } from "fflate/browser";

export const MAX_ARCHIVE_BYTES = 50 * 1024 * 1024;
export const MAX_ENTRY_BYTES = 64 * 1024 * 1024;
export const MAX_EXPANDED_BYTES = 128 * 1024 * 1024;
export const MAX_ARCHIVE_ENTRIES = 256;

const ZIP_EOCD_SIGNATURE = 0x06054b50;
const ZIP_CENTRAL_SIGNATURE = 0x02014b50;
const ZIP64_SENTINEL_16 = 0xffff;
const ZIP64_SENTINEL_32 = 0xffffffff;

export interface ImportedArchive {
  name: string;
  sourceBytes: number;
  expandedBytes: number;
  entries: Map<string, Uint8Array>;
  objectPaths: string[];
}

interface ZipDirectoryEntry {
  path: string;
  uncompressedBytes: number;
}

const textDecoder = new TextDecoder();

function importError(message: string): Error {
  return new Error(message);
}

export function normalizeArchivePath(path: string): string {
  const normalized = path.replaceAll("\\", "/").replace(/^\.\//, "");
  if (
    !normalized ||
    normalized.startsWith("/") ||
    /^[a-zA-Z]:\//.test(normalized)
  ) {
    throw importError(`Archive entry has an unsafe path: ${path || "(empty)"}`);
  }
  const segments = normalized.split("/");
  if (segments.some((segment) => segment === ".." || segment === "")) {
    throw importError(`Archive entry has an unsafe path: ${path}`);
  }
  return segments.filter((segment) => segment !== ".").join("/");
}

function findEndOfCentralDirectory(bytes: Uint8Array): number {
  const minimum = Math.max(0, bytes.length - 65_557);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let offset = bytes.length - 22; offset >= minimum; offset -= 1) {
    if (view.getUint32(offset, true) === ZIP_EOCD_SIGNATURE) return offset;
  }
  throw importError("The selected ZIP has no readable central directory.");
}

export function inspectZipDirectory(bytes: Uint8Array): ZipDirectoryEntry[] {
  if (bytes.byteLength > MAX_ARCHIVE_BYTES) {
    throw importError("ZIP exceeds the 50 MiB compressed import limit.");
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const eocd = findEndOfCentralDirectory(bytes);
  const entryCount = view.getUint16(eocd + 10, true);
  const centralSize = view.getUint32(eocd + 12, true);
  const centralOffset = view.getUint32(eocd + 16, true);
  if (
    entryCount === ZIP64_SENTINEL_16 ||
    centralSize === ZIP64_SENTINEL_32 ||
    centralOffset === ZIP64_SENTINEL_32
  ) {
    throw importError(
      "ZIP64 archives are not accepted by the bounded preview importer.",
    );
  }
  if (entryCount > MAX_ARCHIVE_ENTRIES) {
    throw importError(`ZIP contains more than ${MAX_ARCHIVE_ENTRIES} entries.`);
  }
  if (centralOffset + centralSize > bytes.byteLength) {
    throw importError(
      "ZIP central directory points outside the selected file.",
    );
  }

  const entries: ZipDirectoryEntry[] = [];
  const seen = new Set<string>();
  let total = 0;
  let offset = centralOffset;
  for (let index = 0; index < entryCount; index += 1) {
    if (
      offset + 46 > bytes.byteLength ||
      view.getUint32(offset, true) !== ZIP_CENTRAL_SIGNATURE
    ) {
      throw importError("ZIP central directory is truncated or malformed.");
    }
    const flags = view.getUint16(offset + 8, true);
    const uncompressedBytes = view.getUint32(offset + 24, true);
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const next = offset + 46 + nameLength + extraLength + commentLength;
    if (next > bytes.byteLength)
      throw importError("ZIP entry metadata is truncated.");
    if ((flags & 0x1) !== 0)
      throw importError("Encrypted ZIP entries are not supported.");
    if (uncompressedBytes === ZIP64_SENTINEL_32) {
      throw importError(
        "ZIP64 entries are not accepted by the bounded preview importer.",
      );
    }
    const rawPath = textDecoder.decode(
      bytes.subarray(offset + 46, offset + 46 + nameLength),
    );
    if (!rawPath.endsWith("/")) {
      const path = normalizeArchivePath(rawPath);
      if (seen.has(path))
        throw importError(`ZIP contains a duplicate path: ${path}`);
      if (uncompressedBytes > MAX_ENTRY_BYTES) {
        throw importError(`Archive entry exceeds the 64 MiB limit: ${path}`);
      }
      seen.add(path);
      total += uncompressedBytes;
      if (total > MAX_EXPANDED_BYTES) {
        throw importError("ZIP expands beyond the 128 MiB preview limit.");
      }
      entries.push({ path, uncompressedBytes });
    }
    offset = next;
  }
  return entries;
}

function finalizeArchive(
  name: string,
  sourceBytes: number,
  rawEntries: Iterable<readonly [string, Uint8Array]>,
): ImportedArchive {
  const entries = new Map<string, Uint8Array>();
  let expandedBytes = 0;
  for (const [rawPath, value] of rawEntries) {
    if (rawPath.replaceAll("\\", "/").endsWith("/")) continue;
    const path = normalizeArchivePath(rawPath);
    if (value.byteLength > MAX_ENTRY_BYTES) {
      throw importError(`Import entry exceeds the 64 MiB limit: ${path}`);
    }
    if (entries.has(path))
      throw importError(`Import contains a duplicate path: ${path}`);
    expandedBytes += value.byteLength;
    if (expandedBytes > MAX_EXPANDED_BYTES) {
      throw importError("Import expands beyond the 128 MiB preview limit.");
    }
    entries.set(path, value);
  }
  if (entries.size > MAX_ARCHIVE_ENTRIES) {
    throw importError(
      `Import contains more than ${MAX_ARCHIVE_ENTRIES} files.`,
    );
  }
  const objectPaths = [...entries.keys()]
    .filter((path) => path.toLowerCase().endsWith(".obj"))
    .sort((left, right) => left.localeCompare(right));
  if (objectPaths.length === 0) {
    throw importError(
      "No OBJ geometry was found. Open a ZIP containing OBJ/MTL or select OBJ files.",
    );
  }
  return { name, sourceBytes, expandedBytes, entries, objectPaths };
}

export function extractZipArchive(
  name: string,
  bytes: Uint8Array,
): ImportedArchive {
  const directory = inspectZipDirectory(bytes);
  const inflated = unzipSync(bytes);
  const archive = finalizeArchive(
    name,
    bytes.byteLength,
    Object.entries(inflated),
  );
  const directorySizes = new Map(
    directory.map((entry) => [entry.path, entry.uncompressedBytes]),
  );
  for (const [path, value] of archive.entries) {
    if (directorySizes.get(path) !== value.byteLength) {
      throw importError(
        `Expanded ZIP size does not match its directory record: ${path}`,
      );
    }
  }
  return archive;
}

export async function openImportFiles(
  files: FileList | File[],
): Promise<ImportedArchive> {
  const selected = Array.from(files);
  if (selected.length === 0)
    throw importError("Choose a ZIP or one or more OBJ/MTL files.");
  const zipFiles = selected.filter((file) =>
    file.name.toLowerCase().endsWith(".zip"),
  );
  if (zipFiles.length > 0) {
    if (selected.length !== 1)
      throw importError(
        "Open one ZIP at a time; do not mix it with loose files.",
      );
    const file = zipFiles[0];
    if (file.size > MAX_ARCHIVE_BYTES)
      throw importError("ZIP exceeds the 50 MiB import limit.");
    return extractZipArchive(
      file.name,
      new Uint8Array(await file.arrayBuffer()),
    );
  }

  let sourceBytes = 0;
  const entries: Array<readonly [string, Uint8Array]> = [];
  for (const file of selected) {
    sourceBytes += file.size;
    if (sourceBytes > MAX_EXPANDED_BYTES) {
      throw importError("Selected files exceed the 128 MiB preview limit.");
    }
    entries.push([file.name, new Uint8Array(await file.arrayBuffer())]);
  }
  return finalizeArchive(
    selected.map((file) => file.name).join(", "),
    sourceBytes,
    entries,
  );
}

export function decodeArchiveText(
  archive: ImportedArchive,
  path: string,
): string {
  const bytes = archive.entries.get(path);
  if (!bytes) throw importError(`Archive entry is missing: ${path}`);
  return textDecoder.decode(bytes);
}

export function archiveDirectory(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash === -1 ? "" : path.slice(0, slash + 1);
}

export function resolveArchiveReference(
  basePath: string,
  reference: string,
): string {
  const candidate = `${archiveDirectory(basePath)}${reference.trim()}`;
  const segments: string[] = [];
  for (const segment of candidate.replaceAll("\\", "/").split("/")) {
    if (!segment || segment === ".") continue;
    if (segment === "..") {
      if (segments.length === 0)
        throw importError(`Archive reference escapes its root: ${reference}`);
      segments.pop();
    } else {
      segments.push(segment);
    }
  }
  return normalizeArchivePath(segments.join("/"));
}

export function materialLibraryReferences(objText: string): string[] {
  return [...objText.matchAll(/^mtllib\s+(.+?)\s*$/gim)].map(
    (match) => match[1],
  );
}
