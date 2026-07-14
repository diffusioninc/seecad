import {
  GizmoHelper,
  GizmoViewport,
  Grid,
  OrbitControls,
} from "@react-three/drei";
import { Canvas, useFrame, useLoader, useThree } from "@react-three/fiber";
import {
  Box,
  Boxes,
  Crosshair,
  Maximize2,
  MoveUp,
  Rotate3D,
  ScanLine,
} from "lucide-react";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import type { Revision, ViewId } from "../types";

type InspectMode = "solid" | "xray" | "negative";

const cameraPositions: Record<ViewId, [number, number, number]> = {
  iso: [7.2, 6.2, 7.5],
  front: [0, 1.1, 10],
  right: [10, 1.1, 0],
  top: [0, 10, 0.01],
  section: [6.4, 2.6, 0.01],
  access: [-6.5, 5.8, 6.5],
};

const views: Array<{
  id: ViewId;
  index: string;
  label: string;
  datum: string;
}> = [
  { id: "iso", index: "V1", label: "Isometric", datum: "XYZ" },
  { id: "front", index: "V2", label: "Front", datum: "XY" },
  { id: "right", index: "V3", label: "Right", datum: "ZY" },
  { id: "top", index: "V4", label: "Top", datum: "XZ" },
  { id: "section", index: "V5", label: "Section A", datum: "X–X" },
  { id: "access", index: "V6", label: "Tool access", datum: "Ø10" },
];

interface VisionRigProps {
  revision: Revision;
  comparing: boolean;
  baseline?: Revision;
  demoFallback?: boolean;
}

function CameraController({ view }: { view: ViewId }) {
  const { camera } = useThree();
  useEffect(() => {
    camera.position.set(...cameraPositions[view]);
    camera.lookAt(0, 0.45, 0);
    camera.updateProjectionMatrix();
  }, [camera, view]);
  return null;
}

function makeBridgePlateGeometry(): THREE.ExtrudeGeometry {
  const width = 4;
  const depth = 3.5;
  const radius = 0.2;
  const shape = new THREE.Shape();
  shape.moveTo(-width / 2 + radius, -depth / 2);
  shape.lineTo(width / 2 - radius, -depth / 2);
  shape.quadraticCurveTo(width / 2, -depth / 2, width / 2, -depth / 2 + radius);
  shape.lineTo(width / 2, depth / 2 - radius);
  shape.quadraticCurveTo(width / 2, depth / 2, width / 2 - radius, depth / 2);
  shape.lineTo(-width / 2 + radius, depth / 2);
  shape.quadraticCurveTo(-width / 2, depth / 2, -width / 2, depth / 2 - radius);
  shape.lineTo(-width / 2, -depth / 2 + radius);
  shape.quadraticCurveTo(
    -width / 2,
    -depth / 2,
    -width / 2 + radius,
    -depth / 2,
  );
  shape.closePath();

  const holes: Array<[number, number]> = [
    [-1.5, -1.25],
    [1.5, -1.25],
    [-1.5, 1.25],
    [1.5, 1.25],
  ];
  holes.forEach(([x, y]) => {
    const hole = new THREE.Path();
    hole.absarc(x, y, 0.11, 0, Math.PI * 2, true);
    shape.holes.push(hole);
  });
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: 0.2,
    bevelEnabled: true,
    bevelSegments: 2,
    steps: 1,
    bevelSize: 0.025,
    bevelThickness: 0.025,
    curveSegments: 32,
  });
  geometry.center();
  return geometry;
}

function AnimatedLift({
  lift,
  children,
}: {
  lift: number;
  children: React.ReactNode;
}) {
  const group = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (!group.current) return;
    group.current.position.y = THREE.MathUtils.damp(
      group.current.position.y,
      lift,
      9,
      delta,
    );
  });
  return <group ref={group}>{children}</group>;
}

function ExtrusionRail({ opacity }: { opacity: number }) {
  const lobePositions: Array<[number, number]> = [
    [-0.34, -0.34],
    [-0.34, 0.34],
    [0.34, -0.34],
    [0.34, 0.34],
  ];
  return (
    <group>
      <mesh castShadow receiveShadow>
        <boxGeometry args={[5, 0.34, 0.34]} />
        <meshStandardMaterial
          color="#9ca7a9"
          metalness={0.82}
          roughness={0.28}
          transparent={opacity < 1}
          opacity={opacity}
        />
      </mesh>
      {lobePositions.map(([y, z]) => (
        <mesh key={`${y}-${z}`} position={[0, y, z]} castShadow receiveShadow>
          <boxGeometry args={[5, 0.28, 0.28]} />
          <meshStandardMaterial
            color="#c2c9c9"
            metalness={0.86}
            roughness={0.24}
            transparent={opacity < 1}
            opacity={opacity}
          />
        </mesh>
      ))}
      <mesh position={[0, 0.505, 0]}>
        <boxGeometry args={[5.02, 0.018, 0.16]} />
        <meshBasicMaterial color="#1d2527" transparent opacity={opacity} />
      </mesh>
    </group>
  );
}

function TNut({ x, z, opacity }: { x: number; z: number; opacity: number }) {
  return (
    <group position={[x, 0.43, z]}>
      <mesh castShadow>
        <boxGeometry args={[0.48, 0.13, 0.34]} />
        <meshStandardMaterial
          color="#727b7d"
          metalness={0.9}
          roughness={0.24}
          transparent={opacity < 1}
          opacity={opacity}
        />
      </mesh>
      <mesh position={[0, 0.075, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.09, 0.018, 8, 24]} />
        <meshBasicMaterial color="#252c2e" transparent opacity={opacity} />
      </mesh>
    </group>
  );
}

function CapScrew({
  x,
  z,
  opacity,
}: {
  x: number;
  z: number;
  opacity: number;
}) {
  return (
    <group position={[x, 0.73, z]}>
      <mesh position={[0, -0.42, 0]} castShadow>
        <cylinderGeometry args={[0.095, 0.095, 0.78, 24]} />
        <meshStandardMaterial
          color="#8c9698"
          metalness={0.9}
          roughness={0.2}
          transparent={opacity < 1}
          opacity={opacity}
        />
      </mesh>
      <mesh castShadow>
        <cylinderGeometry args={[0.205, 0.205, 0.055, 32]} />
        <meshStandardMaterial
          color="#d2d6d6"
          metalness={0.92}
          roughness={0.18}
          transparent={opacity < 1}
          opacity={opacity}
        />
      </mesh>
      <mesh position={[0, 0.15, 0]} castShadow>
        <cylinderGeometry args={[0.175, 0.175, 0.25, 32]} />
        <meshStandardMaterial
          color="#adb5b6"
          metalness={0.92}
          roughness={0.2}
          transparent={opacity < 1}
          opacity={opacity}
        />
      </mesh>
      <mesh position={[0, 0.281, 0]}>
        <cylinderGeometry args={[0.07, 0.07, 0.012, 6]} />
        <meshBasicMaterial color="#30383a" transparent opacity={opacity} />
      </mesh>
    </group>
  );
}

function DemoAssembly({
  mode,
  exploded,
}: {
  mode: InspectMode;
  exploded: boolean;
}) {
  const geometry = useMemo(makeBridgePlateGeometry, []);
  const opacity = mode === "xray" ? 0.42 : mode === "negative" ? 0.12 : 1;
  const hardwareOpacity = mode === "xray" ? 0.58 : opacity;
  const showNegative = mode !== "solid";
  const holePositions: Array<[number, number]> = [
    [-1.5, -1.25],
    [1.5, -1.25],
    [-1.5, 1.25],
    [1.5, 1.25],
  ];

  return (
    <group position={[0, 0.05, 0]}>
      <group position={[0, 0, -1.25]}>
        <ExtrusionRail opacity={opacity} />
      </group>
      <group position={[0, 0, 1.25]}>
        <ExtrusionRail opacity={opacity} />
      </group>

      {holePositions.map(([x, z]) => (
        <TNut key={`nut-${x}-${z}`} x={x} z={z} opacity={hardwareOpacity} />
      ))}

      <AnimatedLift lift={exploded ? 0.9 : 0}>
        <mesh
          geometry={geometry}
          rotation={[-Math.PI / 2, 0, 0]}
          position={[0, 0.61, 0]}
          castShadow
          receiveShadow
        >
          <meshStandardMaterial
            color="#2d8fd5"
            metalness={0.16}
            roughness={0.48}
            transparent={opacity < 1}
            opacity={opacity}
            side={THREE.DoubleSide}
          />
        </mesh>
        {showNegative &&
          holePositions.map(([x, z]) => (
            <mesh key={`void-${x}-${z}`} position={[x, 0.61, z]}>
              <cylinderGeometry args={[0.12, 0.12, 0.7, 24]} />
              <meshBasicMaterial
                color="#f2663a"
                transparent
                opacity={mode === "negative" ? 0.82 : 0.36}
                wireframe={mode === "xray"}
              />
            </mesh>
          ))}
      </AnimatedLift>

      <AnimatedLift lift={exploded ? 1.8 : 0}>
        {holePositions.map(([x, z]) => (
          <CapScrew
            key={`screw-${x}-${z}`}
            x={x}
            z={z}
            opacity={hardwareOpacity}
          />
        ))}
      </AnimatedLift>
    </group>
  );
}

export interface SharedMeshTransform {
  scale: number;
  position: [number, number, number];
}

export function deriveSharedMeshTransform(
  bounds: {
    min: { x: number; y: number; z: number };
    max: { x: number; y: number; z: number };
  },
  targetLongest = 4.8,
): SharedMeshTransform {
  const size = {
    x: bounds.max.x - bounds.min.x,
    y: bounds.max.y - bounds.min.y,
    z: bounds.max.z - bounds.min.z,
  };
  const longest = Math.max(size.x, size.y, size.z) || 1;
  const scale = targetLongest / longest;
  const center = {
    x: (bounds.min.x + bounds.max.x) / 2,
    y: (bounds.min.y + bounds.max.y) / 2,
    z: (bounds.min.z + bounds.max.z) / 2,
  };
  return {
    scale,
    position: [-center.x * scale, -center.y * scale, -center.z * scale],
  };
}

function useStlGeometry(url: string) {
  const geometry = useLoader(STLLoader, url);
  return useMemo(() => {
    const clone = geometry.clone();
    clone.computeVertexNormals();
    clone.computeBoundingBox();
    return clone;
  }, [geometry]);
}

function StlGhost({ url }: { url: string }) {
  const geometry = useStlGeometry(url);
  return (
    <mesh geometry={geometry}>
      <meshBasicMaterial color="#f2663a" transparent opacity={0.2} wireframe />
    </mesh>
  );
}

function LiveStlPair({
  currentUrl,
  baselineUrl,
  mode,
}: {
  currentUrl: string;
  baselineUrl?: string;
  mode: InspectMode;
}) {
  const geometry = useStlGeometry(currentUrl);
  const transform = useMemo(() => {
    geometry.computeBoundingBox();
    const bounds = geometry.boundingBox;
    return bounds
      ? deriveSharedMeshTransform(bounds)
      : { scale: 1, position: [0, 0, 0] as [number, number, number] };
  }, [geometry]);
  return (
    <group scale={transform.scale} position={transform.position}>
      <mesh geometry={geometry} castShadow receiveShadow>
        <meshStandardMaterial
          color="#afc1c5"
          metalness={0.38}
          roughness={0.4}
          wireframe={mode === "negative"}
          transparent={mode !== "solid"}
          opacity={mode === "solid" ? 1 : 0.42}
        />
      </mesh>
      {baselineUrl && <StlGhost url={baselineUrl} />}
    </group>
  );
}

function DemoGhost({
  baseline,
  revision,
}: {
  baseline: Revision;
  revision: Revision;
}) {
  const geometry = useMemo(makeBridgePlateGeometry, []);
  const current = revision.dimensions;
  const prior = baseline.dimensions;
  const ratio: [number, number, number] =
    current && prior
      ? [prior.x / current.x, prior.z / current.z, prior.y / current.y]
      : [0.985, 0.96, 0.985];
  return (
    <group
      scale={[ratio[0], ratio[1], ratio[2]]}
      position={[0.07, 0.61, -0.07]}
    >
      <mesh geometry={geometry} rotation={[-Math.PI / 2, 0, 0]}>
        <meshBasicMaterial
          color="#f2663a"
          transparent
          opacity={0.2}
          wireframe
        />
      </mesh>
    </group>
  );
}

function SpecProxy() {
  return (
    <group position={[0, 0.4, 0]}>
      <mesh>
        <boxGeometry args={[4.8, 0.65, 3.2]} />
        <meshBasicMaterial
          color="#748286"
          transparent
          opacity={0.2}
          wireframe
        />
      </mesh>
    </group>
  );
}

function ModelScene({
  revision,
  view,
  mode,
  comparing,
  baseline,
  demoFallback,
  exploded,
}: {
  revision: Revision;
  view: ViewId;
  mode: InspectMode;
  comparing: boolean;
  baseline?: Revision;
  demoFallback: boolean;
  exploded: boolean;
}) {
  return (
    <>
      <CameraController view={view} />
      <color attach="background" args={["#101517"]} />
      <fog attach="fog" args={["#101517", 11, 24]} />
      <ambientLight intensity={1.2} />
      <hemisphereLight args={["#dff9ff", "#1b2224", 1.8]} />
      <directionalLight
        position={[4, 9, 6]}
        intensity={3.2}
        color="#effdff"
        castShadow
      />
      <directionalLight
        position={[-7, 2, -4]}
        intensity={1.6}
        color="#1bb6d2"
      />
      <spotLight
        position={[0, 4, -7]}
        intensity={2}
        color="#f2663a"
        angle={0.5}
        penumbra={1}
      />
      <Suspense fallback={null}>
        {revision.stlUrl ? (
          <LiveStlPair
            currentUrl={revision.stlUrl}
            baselineUrl={
              comparing && baseline?.id !== revision.id
                ? baseline?.stlUrl
                : undefined
            }
            mode={mode}
          />
        ) : demoFallback ? (
          <DemoAssembly mode={mode} exploded={exploded} />
        ) : (
          <SpecProxy />
        )}
        {!revision.stlUrl &&
          comparing &&
          baseline &&
          baseline.id !== revision.id &&
          (demoFallback ? (
            <DemoGhost baseline={baseline} revision={revision} />
          ) : null)}
      </Suspense>
      <Grid
        position={[0, -0.43, 0]}
        args={[18, 18]}
        cellSize={0.5}
        cellThickness={0.45}
        cellColor="#344044"
        sectionSize={2.5}
        sectionThickness={0.8}
        sectionColor="#536368"
        fadeDistance={12}
        fadeStrength={1.4}
        infiniteGrid
      />
      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={0.08}
        minDistance={4.2}
        maxDistance={15}
        target={[0, 0.35, 0]}
      />
      <GizmoHelper alignment="bottom-right" margin={[66, 54]}>
        <GizmoViewport
          axisColors={["#f2663a", "#1d8a78", "#1bb6d2"]}
          labelColor="#e6ecec"
        />
      </GizmoHelper>
    </>
  );
}

function PartSchematic({
  view,
  negative,
  dimensions,
}: {
  view: ViewId;
  negative: boolean;
  dimensions: Revision["dimensions"];
}) {
  const isSide = view === "right";
  const isSection = view === "section";
  const isAccess = view === "access";
  return (
    <svg viewBox="0 0 180 94" aria-hidden="true">
      <defs>
        <pattern
          id={`hatch-${view}`}
          width="7"
          height="7"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <line x1="0" y1="0" x2="0" y2="7" stroke="#57656a" strokeWidth="2" />
        </pattern>
      </defs>
      <g className="schematic-grid">
        <path d="M10 47H170M90 6V88" />
        <path d="M26 17H154V77H26Z" />
      </g>
      {isSide ? (
        <>
          <g className="schematic-stock">
            <path d="M39 49H67V70H39Z" />
            <path d="M113 49H141V70H113Z" />
            <path d="M47 49V70M59 49V70M121 49V70M133 49V70" />
          </g>
          <g className="schematic-part">
            <path
              d="M27 41H153V49H27Z"
              fill={isSection ? `url(#hatch-${view})` : undefined}
            />
            <path className="schematic-hole" d="M50 41V49M130 41V49" />
          </g>
        </>
      ) : (
        <>
          <g className="schematic-stock">
            <path d="M18 25H162V36H18ZM18 58H162V69H18Z" />
            <path d="M18 30H162M18 63H162" />
          </g>
          <g className="schematic-part">
            <path
              d="M39 18H141L147 24V70L141 76H39L33 70V24Z"
              fill={isSection ? `url(#hatch-${view})` : undefined}
            />
            {[
              [-1, -1],
              [1, -1],
              [-1, 1],
              [1, 1],
            ].map(([x, y], i) => (
              <circle
                key={i}
                className="schematic-hole"
                cx={90 + x * 42}
                cy={47 + y * 17}
                r="4"
              />
            ))}
          </g>
        </>
      )}
      {(negative || isAccess) && (
        <g className="schematic-negative">
          <path d="M48 10V84M132 10V84" />
          {isAccess && (
            <>
              <path d="M42 15L48 8L54 15M126 15L132 8L138 15" />
              <path d="M42 79L48 86L54 79M126 79L132 86L138 79" />
            </>
          )}
        </g>
      )}
      <g className="schematic-dim">
        <path d="M26 81H154M26 77V86M154 77V86" />
        <text x="90" y="90" textAnchor="middle">
          {dimensions ? dimensions.x.toFixed(2) : "—"}
        </text>
      </g>
    </svg>
  );
}

function ModeButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`rig-mode ${active ? "is-active" : ""}`}
      type="button"
      onClick={onClick}
    >
      {label}
    </button>
  );
}

export function VisionRig({
  revision,
  comparing,
  baseline,
  demoFallback = false,
}: VisionRigProps) {
  const [view, setView] = useState<ViewId>("iso");
  const [mode, setMode] = useState<InspectMode>("solid");
  const [exploded, setExploded] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.target instanceof HTMLInputElement ||
        event.target instanceof HTMLTextAreaElement
      )
        return;
      const index = Number(event.key) - 1;
      if (index >= 0 && index < views.length) setView(views[index].id);
      if (event.key.toLowerCase() === "e" && demoFallback)
        setExploded((value) => !value);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [demoFallback]);

  return (
    <section className="vision-rig" aria-labelledby="rig-title">
      <header className="rig-header">
        <div>
          <div className="eyebrow">
            <ScanLine size={13} /> Synchronized vision rig
          </div>
          <div className="rig-title-row">
            <h1 id="rig-title">{revision.id} / inspection model</h1>
            {comparing && baseline && (
              <span className="compare-chip">Overlaying {baseline.id}</span>
            )}
          </div>
        </div>
        <div className="rig-controls">
          {demoFallback && (
            <div className="assembly-mode-group" aria-label="Assembly state">
              <button
                className={!exploded ? "is-active" : ""}
                type="button"
                aria-pressed={!exploded}
                onClick={() => setExploded(false)}
              >
                <Boxes size={12} /> Fitted
              </button>
              <button
                className={exploded ? "is-active" : ""}
                type="button"
                aria-pressed={exploded}
                onClick={() => setExploded(true)}
              >
                <MoveUp size={12} /> Exploded
              </button>
            </div>
          )}
          <div className="rig-mode-group" aria-label="Model display mode">
            <ModeButton
              active={mode === "solid"}
              label="Solid"
              onClick={() => setMode("solid")}
            />
            <ModeButton
              active={mode === "xray"}
              label="X-ray"
              onClick={() => setMode("xray")}
            />
            <ModeButton
              active={mode === "negative"}
              label="Negative"
              onClick={() => setMode("negative")}
            />
          </div>
        </div>
      </header>

      <div className="viewport-shell" ref={viewportRef}>
        <div className="viewport-readout viewport-readout-left">
          <span>
            CAM {views.find((candidate) => candidate.id === view)?.index} ·{" "}
            {exploded && demoFallback ? "EXPLODED" : "FITTED"}
          </span>
          <strong>
            {views
              .find((candidate) => candidate.id === view)
              ?.label.toUpperCase()}
          </strong>
        </div>
        <div className="viewport-readout viewport-readout-right">
          <span>TRIANGLES</span>
          <strong>
            {revision.triangles === null
              ? revision.stlUrl
                ? "UNCOUNTED"
                : "NO MESH"
              : `${revision.triangles.toLocaleString()} △`}
          </strong>
        </div>
        <div className="viewport-crosshair" aria-hidden="true">
          <Crosshair size={28} />
        </div>
        {!revision.stlUrl && !demoFallback && (
          <div className="viewport-proxy-note">
            Spec proxy · compile an STL for mesh inspection
          </div>
        )}
        {comparing && baseline && !baseline.stlUrl && !demoFallback && (
          <div className="viewport-compare-note">
            Baseline overlay unavailable · {baseline.id} has no STL
          </div>
        )}
        <Canvas
          shadows
          camera={{
            position: cameraPositions.iso,
            fov: 37,
            near: 0.1,
            far: 100,
          }}
          dpr={[1, 1.8]}
          gl={{ antialias: true, powerPreference: "high-performance" }}
        >
          <ModelScene
            revision={revision}
            view={view}
            mode={mode}
            comparing={comparing}
            baseline={baseline}
            demoFallback={demoFallback}
            exploded={exploded}
          />
        </Canvas>
        <div className="viewport-hint">
          <Rotate3D size={13} /> Drag to orbit · wheel to zoom
        </div>
        <button
          className="viewport-expand"
          type="button"
          aria-label="Expand viewport"
          onClick={() => void viewportRef.current?.requestFullscreen()}
        >
          <Maximize2 size={15} />
        </button>
      </div>

      <div className="view-tile-grid" aria-label="Inspection views">
        {views.map((candidate) => (
          <button
            key={candidate.id}
            className={`view-tile ${view === candidate.id ? "is-active" : ""}`}
            type="button"
            aria-pressed={view === candidate.id}
            onClick={() => setView(candidate.id)}
          >
            <span className="view-index">{candidate.index}</span>
            <span className="view-datum">{candidate.datum}</span>
            <PartSchematic
              view={candidate.id}
              negative={mode !== "solid"}
              dimensions={revision.dimensions}
            />
            <span className="view-label">
              <Box size={11} /> {candidate.label}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
