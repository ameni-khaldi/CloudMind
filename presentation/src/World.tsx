import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, Line, OrbitControls, RoundedBox, useCursor } from "@react-three/drei";
import gsap from "gsap";
import { useEffect, useMemo, useRef, useState } from "react";
import { Group, Vector3, type Points } from "three";
import type { OrbitControls as Controls } from "three-stdlib";
import { story, type Item } from "./story";
import type { Evidence } from "./types";

const blue = "#7cb5d5", coral = "#e9957d", navy = "#263746", cream = "#f8f3ea";
type Vec = [number, number, number];
const zone = (scene: number): Vec => [scene * 25, 0, (scene % 2) * 3];

function Camera({ scene, replay, reduced, explore }: { scene: number; replay: number; reduced: boolean; explore: boolean }) {
  const camera = useThree((state) => state.camera);
  const controls = useRef<Controls>(null);
  const previous = useRef({ scene, replay });
  const mounted = useRef(false);
  useEffect(() => {
    const [x, , z] = zone(scene);
    const current = controls.current;
    if (!current) return;
    const city = scene === 1;
    const target = new Vector3(x, city ? 0.55 : 0.95, z);
    const end = new Vector3(x + (city ? 8.6 : 7.2), city ? 9.4 : 5.1, z + (city ? 11.8 : 11.5));
    const first = !mounted.current;
    mounted.current = true;
    const restart = previous.current.scene === scene && previous.current.replay !== replay;
    previous.current = { scene, replay };
    if (first || restart) {
      current.target.copy(target);
      camera.position.copy(end);
      if (!reduced) camera.position.add(new Vector3(2.5, 0.9, 3.2));
    }
    if (reduced) {
      current.target.copy(target);
      camera.position.copy(end);
      current.update();
      return;
    }
    const animation = gsap.timeline({ defaults: { duration: 1.35, ease: "power3.inOut" } });
    animation.to(camera.position, { x: end.x, y: end.y, z: end.z }, 0)
      .to(current.target, { x: target.x, y: target.y, z: target.z, onUpdate: () => current.update() }, 0);
    return () => { animation.kill(); };
  }, [camera, reduced, replay, scene]);
  return <OrbitControls ref={controls} enabled={explore} enablePan={false} enableDamping={!reduced}
    minDistance={5} maxDistance={25} maxPolarAngle={Math.PI / 2.05} />;
}

function Clickable({ children, title, label, picked, onPick }: {
  children: React.ReactNode; title: string; label?: boolean; picked: boolean; onPick: () => void;
}) {
  const [hover, setHover] = useState(false);
  useCursor(hover);
  return <group onClick={(event) => { event.stopPropagation(); onPick(); }}
    onPointerOver={(event) => { event.stopPropagation(); setHover(true); }}
    onPointerOut={() => setHover(false)}>
    <group scale={hover || picked ? 1.075 : 1}>{children}</group>
    {(label || hover || picked) && <Html position={[0, -0.65, 0.4]} center pointerEvents="none"
      zIndexRange={[5, 0]}><span className={hover || picked ? "world-label chosen" : "world-label"}>{title}</span></Html>}
  </group>;
}

function Atmosphere({ reduced, active }: { reduced: boolean; active: boolean }) {
  const points = useRef<Points>(null);
  const positions = useMemo(() => Float32Array.from({ length: 210 }, (_, index) => {
    const n = Math.floor(index / 3);
    if (index % 3 === 1) return 0.4 + (n * 0.721 % 1) * 5.2;
    return Math.sin(n * (index % 3 === 0 ? 17.1 : 7.3)) * (3.6 + (n * 0.619 % 1) * 3);
  }), []);
  useFrame((_, dt) => { if (!reduced && active && points.current) points.current.rotation.y += Math.min(dt, 0.05) * 0.055; });
  return <points ref={points}>
    <bufferGeometry><bufferAttribute attach="attributes-position" args={[positions, 3]} /></bufferGeometry>
    <pointsMaterial size={0.038} color="#faffff" transparent opacity={0.9} sizeAttenuation />
  </points>;
}

function Platform({ city }: { city: boolean }) {
  const radius = city ? 6.65 : 5.05;
  return <group>
    <mesh position={[0, -0.26, 0]} receiveShadow>
      <cylinderGeometry args={[radius, radius - 0.16, 0.48, 84]} />
      <meshStandardMaterial color="#e0e9e9" roughness={0.47} metalness={0.15} />
    </mesh>
    <mesh position={[0, -0.016, 0]} receiveShadow>
      <cylinderGeometry args={[radius - 0.09, radius - 0.09, 0.035, 84]} />
      <meshStandardMaterial color="#f5f3eb" roughness={0.66} />
    </mesh>
    <mesh position={[0, -0.14, 0]} rotation={[Math.PI / 2, 0, 0]}>
      <torusGeometry args={[radius - .025, .022, 8, 100]} />
      <meshStandardMaterial color="#ffffff" />
    </mesh>
    {!city && [2.1, 3.35, 4.35].map((r) => <mesh key={r} position={[0, .012, 0]} rotation={[Math.PI / 2, 0, 0]}>
      <torusGeometry args={[r, .012, 6, 88]} />
      <meshStandardMaterial color="#b4cfd8" transparent opacity={0.66} />
    </mesh>)}
    <mesh position={[0, -0.5, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
      <planeGeometry args={[23, 23]} /><shadowMaterial transparent opacity={0.19} />
    </mesh>
  </group>;
}

function Atlas({ items, reduced, selected, onPick }: {
  items: Item[]; reduced: boolean; selected: string; onPick: (index: number) => void;
}) {
  const core = useRef<Group>(null), orb = useRef<Group>(null);
  useFrame((state, dt) => {
    if (!reduced && core.current && orb.current) {
      core.current.rotation.y += Math.min(dt, .05) * .18;
      core.current.position.y = 2.35 + Math.sin(state.clock.elapsedTime * 1.1) * .16;
      orb.current.rotation.y += Math.min(dt, .05) * .075;
    }
  });
  return <>
    <group ref={orb} position={[0, 2.12, 0]}>
      {[[1.28, .23, .31], [1.04, -.35, 1.08], [1.49, .58, -.44]].map((rotation, i) =>
        <mesh key={i} rotation={rotation as Vec}>
          <torusGeometry args={[2.28 + i * .28, .021 + i * .007, 12, 96]} />
          <meshStandardMaterial color={i === 1 ? "#f0a189" : "#effdff"} metalness={.28} roughness={.17} />
        </mesh>)}
      {items.map((item, i) => <group key={item.title} position={[Math.cos(i * 2.11 + .3) * 2.73, (i - 1) * .59, Math.sin(i * 2.11 + .3) * 2.73]}>
        <Clickable title={item.title} picked={selected === item.title} onPick={() => onPick(i)}>
          <mesh castShadow><icosahedronGeometry args={[.36, 0]} />
            <meshStandardMaterial color={i === 1 ? coral : "#e6f6fb"} metalness={.14} roughness={.25} />
          </mesh>
        </Clickable>
      </group>)}
    </group>
    <group ref={core} position={[0, 2.35, 0]} rotation={[.24, -.24, .16]}>
      {Array.from({ length: 27 }, (_, i) => {
        const pos: Vec = [(i % 3 - 1) * .7, (Math.floor(i / 3) % 3 - 1) * .7, (Math.floor(i / 9) - 1) * .7];
        return <RoundedBox key={i} args={[.62, .62, .62]} radius={.075} smoothness={2} position={pos} castShadow>
          <meshPhysicalMaterial color={[blue, "#bfe2f0", coral, "#ebf7f8"][i % 4]} metalness={.12}
            roughness={.26} clearcoat={.9} transparent opacity={i % 4 === 1 ? .69 : .95} />
        </RoundedBox>;
      })}
    </group>
    {Array.from({ length: 13 }, (_, i) => {
      const a = i * Math.PI * 2 / 13;
      return <mesh key={i} position={[Math.cos(a) * 3.74, .08, Math.sin(a) * 3.74]}>
        <sphereGeometry args={[.065, 8, 6]} /><meshStandardMaterial color={i % 3 === 0 ? coral : blue} />
      </mesh>;
    })}
  </>;
}

function City({ evidence, selected, onPick }: { evidence: Evidence; selected: string; onPick: (i: number) => void }) {
  return <>
    {evidence.hotels.map((hotel, i) => {
      const height = .52 + (i * 13 % 21) / 16;
      const picked = selected === hotel.hotel_name;
      return <group key={hotel.hotel_id} position={[(i % 10 - 4.5) * 1.02, height * .5, (Math.floor(i / 10) - 2) * 1.24]}>
        <Clickable title={hotel.hotel_name} picked={picked} onPick={() => onPick(i)}>
          <RoundedBox args={[.72, height, .72]} radius={.048} smoothness={2} castShadow>
            <meshStandardMaterial color={picked ? "#ce7960" : i % 3 === 0 ? coral : i % 3 === 1 ? blue : "#b5d9e7"} roughness={.4} />
          </RoundedBox>
          <mesh position={[0, height * .2, .365]}><planeGeometry args={[.5, height * .1]} /><meshBasicMaterial color="#fff9ef" /></mesh>
          <mesh position={[0, -height * .15, .365]}><planeGeometry args={[.5, height * .1]} /><meshBasicMaterial color="#f4f9f9" /></mesh>
        </Clickable>
      </group>;
    })}
  </>;
}

const diagramLayouts: Record<number, Vec[]> = {
  2: [[-3.5, 0, 0], [-1.65, 0, -1.65], [-1.65, 0, 1.65], [.8, 0, 0], [3.05, 0, 0]],
  4: [[0, 0, 0], [-2.6, 0, -1.4], [2.6, 0, -1.4], [2.6, 0, 1.4], [-2.6, 0, 1.4]],
  5: [[-3.5, 0, 0], [-1.7, 0, 0], [.5, 0, -1.4], [.5, 0, 1.4], [3.2, 0, 0]],
  8: [[-3.45, 0, 0], [-1.65, 0, 0], [.45, 0, -1.55], [.45, 0, 1.55], [3.1, 0, 0]],
};
const branches: Record<number, [number, number][]> = {
  2: [[0,1],[0,2],[1,3],[2,3],[3,4]], 4: [[1,0],[0,2],[0,3],[0,4]],
  5: [[0,1],[1,2],[1,3],[2,4],[3,4]], 8: [[0,1],[1,2],[1,3],[2,4],[3,4]],
};

function Route({ from, to, reduced, index }: { from: Vec; to: Vec; reduced: boolean; index: number }) {
  const bead = useRef<Group>(null);
  useFrame(({ clock }) => {
    if (!bead.current) return;
    const t = reduced ? .55 : (clock.elapsedTime * .47 + index * .37) % 1;
    bead.current.position.set(from[0] + (to[0] - from[0]) * t, .24, from[2] + (to[2] - from[2]) * t);
  });
  return <>
    <Line points={[[from[0], .22, from[2]], [to[0], .22, to[2]]]} color="#649eb4" lineWidth={2} transparent opacity={.7} />
    <group ref={bead}><mesh><sphereGeometry args={[.095, 10, 8]} /><meshBasicMaterial color="#d7785d" /></mesh></group>
  </>;
}

function Diagram({ scene, items, reduced, selected, onPick }: {
  scene: number; items: Item[]; reduced: boolean; selected: string; onPick: (i: number) => void;
}) {
  const positions: Vec[] = diagramLayouts[scene] ?? items.map((_, i) => [(i - (items.length - 1) / 2) * 1.8, 0, Math.sin(i * 1.6) * .84]);
  const routes = branches[scene] ?? positions.slice(1).map((_, i): [number, number] => [i, i + 1]);
  return <>
    {routes.map(([a, b], i) => <Route key={i} from={positions[a]} to={positions[b]} reduced={reduced} index={i} />)}
    {items.map((item, i) => {
      const color = selected === item.title ? "#d27e62" : i % 2 === 0 ? blue : coral;
      return <group key={item.title} position={[positions[i][0], .86, positions[i][2]]}>
        <Clickable title={item.title} picked={selected === item.title} label onPick={() => onPick(i)}>
          {scene === 4 && i === 0 ? <mesh castShadow>
            <cylinderGeometry args={[.88,.7,1.42,32]} /><meshPhysicalMaterial color={color} roughness={.3} clearcoat={.7} />
          </mesh> : <>
            {[0,1,2].map(layer => <RoundedBox key={layer} position={[0, layer * .36 - .52, 0]}
              args={[1.15 - layer * .12, .27, 1.05 - layer * .11]} radius={.07} smoothness={2} castShadow>
                <meshPhysicalMaterial color={layer === 1 ? cream : color} metalness={.12}
                  roughness={.35} clearcoat={.8} transparent opacity={layer === 2 ? .92 : 1} />
            </RoundedBox>)}
          </>}
          <mesh position={[0, .49, 0]}>
            <octahedronGeometry args={[.23,0]} /><meshStandardMaterial color={i % 2 ? "#fff0e3" : "#f4fcff"} />
          </mesh>
        </Clickable>
      </group>;
    })}
  </>;
}

export default function World({ scene, evidence, selected, onPick, reduced, explore, replay, paused, onFailure }: {
  scene: number; evidence: Evidence; selected: string; onPick: (i: number) => void;
  reduced: boolean; explore: boolean; replay: number; paused: boolean; onFailure: () => void;
}) {
  const [last, setLast] = useState(scene);
  const [previous, setPrevious] = useState(scene);
  useEffect(() => {
    if (scene !== last) { setPrevious(last); setLast(scene); }
    const timer = window.setTimeout(() => setPrevious(scene), 1550);
    return () => window.clearTimeout(timer);
  }, [last, scene]);
  const visible = [...new Set([scene, previous])];
  return <Canvas camera={{ fov: 42, position: [9, 7, 14], near: .1, far: 100 }} dpr={[1, 1.5]} shadows frameloop={paused ? "never" : "always"}
    gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
    onCreated={({ gl }) => gl.domElement.addEventListener("webglcontextlost", (event) => { event.preventDefault(); onFailure(); }, { once: true })}>
    <ambientLight intensity={1.55} color="#fff4e8" />
    <hemisphereLight intensity={1.2} color="#fff8e9" groundColor={navy} />
    {visible.map((index) => <group key={index} position={zone(index)}>
      <directionalLight position={[-5, 9, 5]} intensity={index === scene ? 2.35 : 0} color="#fff5dc" castShadow={index === scene}
        shadow-mapSize={[1024,1024]} shadow-camera-left={-8} shadow-camera-right={8}
        shadow-camera-top={8} shadow-camera-bottom={-8} shadow-normalBias={.035} />
      <Platform city={index === 1} />
      <Atmosphere reduced={reduced} active={index === scene} />
      {index === 0 ? <Atlas items={story[0].items} selected={selected} reduced={reduced} onPick={onPick} />
        : index === 1 || index === 7 ? <City evidence={evidence} selected={selected} onPick={onPick} />
        : <Diagram scene={index} items={story[index].items} reduced={reduced} selected={selected} onPick={onPick} />}
    </group>)}
    <Camera scene={scene} replay={replay} reduced={reduced} explore={explore} />
  </Canvas>;
}
