import { useEffect, useRef } from "react";
import * as THREE from "three";
import { MTLLoader } from "three/examples/jsm/loaders/MTLLoader.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import {
  archiveDirectory,
  decodeArchiveText,
  materialLibraryReferences,
  resolveArchiveReference,
  type ImportedArchive,
} from "../import-archive";

export interface ImportedAssemblyMetrics {
  objectFiles: number;
  objectRecords: number;
  meshGroups: number;
  materialGroups: number;
  triangles: number;
  sourceSize: { x: number; y: number; z: number };
}

interface ImportedAssemblyRigProps {
  archive: ImportedArchive;
  showEdges: boolean;
  upAxis: "z" | "y";
  onMetrics: (metrics: ImportedAssemblyMetrics) => void;
}

function mimeType(path: string): string {
  const extension = path.split(".").pop()?.toLowerCase();
  if (extension === "png") return "image/png";
  if (extension === "jpg" || extension === "jpeg") return "image/jpeg";
  if (extension === "webp") return "image/webp";
  if (extension === "bmp") return "image/bmp";
  return "application/octet-stream";
}

function blobBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

function cssColor(
  canvas: HTMLCanvasElement,
  property: string,
  fallback: string,
): THREE.Color {
  const value = getComputedStyle(canvas).getPropertyValue(property).trim();
  return new THREE.Color(value || fallback);
}

function disposeObject(object: THREE.Object3D): void {
  object.traverse((child) => {
    if (
      !(child instanceof THREE.Mesh) &&
      !(child instanceof THREE.LineSegments)
    )
      return;
    child.geometry.dispose();
    const materials = Array.isArray(child.material)
      ? child.material
      : [child.material];
    for (const material of materials) material.dispose();
  });
}

export function ImportedAssemblyRig({
  archive,
  showEdges,
  upAxis,
  onMetrics,
}: ImportedAssemblyRigProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const scene = new THREE.Scene();
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    renderer.setClearColor(cssColor(canvas, "--carbon", "#0d1214"), 1);

    const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 5000);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.075;
    controls.screenSpacePanning = true;

    scene.add(new THREE.HemisphereLight(0xf5fbfa, 0x314044, 2.2));
    const keyLight = new THREE.DirectionalLight(0xffffff, 3.4);
    keyLight.position.set(6, 9, 7);
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight(0x9bd7e1, 1.5);
    fillLight.position.set(-7, 4, -5);
    scene.add(fillLight);

    const loadingManager = new THREE.LoadingManager();
    const objectUrls = new Map<string, string>();
    for (const [path, bytes] of archive.entries) {
      if (/\.(png|jpe?g|webp|bmp)$/i.test(path)) {
        objectUrls.set(
          path,
          URL.createObjectURL(
            new Blob([blobBuffer(bytes)], { type: mimeType(path) }),
          ),
        );
      }
    }
    loadingManager.setURLModifier((url) => {
      if (/^(blob:|data:|https?:)/i.test(url)) return url;
      let decoded = url;
      try {
        decoded = decodeURIComponent(url);
      } catch {
        // Keep the loader's original URL when it is not percent encoded.
      }
      return objectUrls.get(decoded.replace(/^\.\//, "")) ?? url;
    });

    const assembly = new THREE.Group();
    assembly.name = "imported-assembly-preview";
    let objectRecords = 0;
    for (const objectPath of archive.objectPaths) {
      const objectText = decodeArchiveText(archive, objectPath);
      objectRecords += [...objectText.matchAll(/^o\s+.+$/gim)].length;
      const loader = new OBJLoader(loadingManager);
      const materialPath = materialLibraryReferences(objectText)
        .map((reference) => resolveArchiveReference(objectPath, reference))
        .find((candidate) => archive.entries.has(candidate));
      if (materialPath) {
        const materialText = decodeArchiveText(archive, materialPath);
        const materials = new MTLLoader(loadingManager).parse(
          materialText,
          archiveDirectory(materialPath),
        );
        materials.preload();
        loader.setMaterials(materials);
      }
      const object = loader.parse(objectText);
      object.name = objectPath;
      assembly.add(object);
    }

    const sourceBounds = new THREE.Box3().setFromObject(assembly);
    if (sourceBounds.isEmpty())
      throw new Error("OBJ files contain no displayable triangle geometry.");
    const sourceCenter = sourceBounds.getCenter(new THREE.Vector3());
    const sourceSize = sourceBounds.getSize(new THREE.Vector3());
    assembly.position.copy(sourceCenter).multiplyScalar(-1);
    if (upAxis === "z") assembly.rotation.x = -Math.PI / 2;

    let meshGroups = 0;
    let triangles = 0;
    const materialIds = new Set<string>();
    assembly.traverse((child) => {
      if (!(child instanceof THREE.Mesh)) return;
      meshGroups += 1;
      const geometry = child.geometry;
      triangles += Math.floor(
        (geometry.index?.count ?? geometry.attributes.position.count) / 3,
      );
      const materials = Array.isArray(child.material)
        ? child.material
        : [child.material];
      for (const material of materials) {
        material.side = THREE.DoubleSide;
        material.needsUpdate = true;
        materialIds.add(material.uuid);
      }
      if (showEdges) {
        const edgeLines = new THREE.LineSegments(
          new THREE.EdgesGeometry(geometry, 32),
          new THREE.LineBasicMaterial({
            color: cssColor(canvas, "--polymer", "#f3f5f4"),
            transparent: true,
            opacity: 0.42,
          }),
        );
        edgeLines.name = "preview-edges";
        child.add(edgeLines);
      }
    });
    scene.add(assembly);

    assembly.updateMatrixWorld(true);
    const displayBounds = new THREE.Box3().setFromObject(assembly);
    const displaySize = displayBounds.getSize(new THREE.Vector3());
    const radius = Math.max(displaySize.length() * 0.5, 1);
    const grid = new THREE.GridHelper(
      Math.max(displaySize.x, displaySize.z, radius) * 1.7,
      20,
      cssColor(canvas, "--cyan-dark", "#087f94"),
      cssColor(canvas, "--line-dark", "#334044"),
    );
    grid.position.y = displayBounds.min.y;
    scene.add(grid);

    const fitView = () => {
      camera.near = Math.max(radius / 250, 0.05);
      camera.far = radius * 50;
      camera.position
        .set(1.35, 1.02, 1.48)
        .normalize()
        .multiplyScalar(radius * 2.4);
      camera.updateProjectionMatrix();
      controls.target.set(0, 0, 0);
      controls.minDistance = radius * 0.3;
      controls.maxDistance = radius * 12;
      controls.update();
    };
    fitView();

    onMetrics({
      objectFiles: archive.objectPaths.length,
      objectRecords: objectRecords || archive.objectPaths.length,
      meshGroups,
      materialGroups: materialIds.size,
      triangles,
      sourceSize: { x: sourceSize.x, y: sourceSize.y, z: sourceSize.z },
    });

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const width = Math.max(parent.clientWidth, 1);
      const height = Math.max(parent.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const resizeObserver = new ResizeObserver(resize);
    if (canvas.parentElement) resizeObserver.observe(canvas.parentElement);
    resize();

    let frame = 0;
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(render);
    };
    render();

    return () => {
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      controls.dispose();
      disposeObject(assembly);
      grid.geometry.dispose();
      const gridMaterials = Array.isArray(grid.material)
        ? grid.material
        : [grid.material];
      for (const material of gridMaterials) material.dispose();
      renderer.dispose();
      for (const url of objectUrls.values()) URL.revokeObjectURL(url);
    };
  }, [archive, onMetrics, showEdges, upAxis]);

  return (
    <canvas
      ref={canvasRef}
      aria-label="Interactive read-only imported assembly preview. Drag to orbit and use the wheel or pinch gesture to zoom."
    />
  );
}
