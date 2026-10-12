import type ForceGraph3D from "3d-force-graph";
import type { ForceGraph3DInstance } from "3d-force-graph";
import type * as Three from "three";
import type { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import type { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import {
  GLOBE_COLORS,
  SHOW_ALL,
  describe,
  hubLabel,
  isShown,
  matchesQuery,
  radiusOf,
  type Globe,
  type GlobeFilter,
  type GlobeLinkKind,
  type GlobeNode,
} from "@/lib/vaultGlobe";

/**
 * The WebGL side of the 3D vault map. It owns the renderer, the force layout,
 * and everything drawn in the scene, from createGlobeEngine() to dispose().
 * VaultGlobe.tsx holds the React state and tells the engine what changed.
 */

export type GlobeLibs = Readonly<{
  ForceGraph3D: typeof ForceGraph3D;
  THREE: typeof Three;
  UnrealBloomPass: typeof UnrealBloomPass;
  OutputPass: typeof OutputPass;
}>;

export type GlobeView = Readonly<{
  /** The point drawn as picked (white, with a ring and its name). */
  selected: string | null;
  /** Points marked as the latest answer's sources. */
  sources: ReadonlySet<string>;
  filter: GlobeFilter;
  /** Dims notes and chats that do not match. */
  query: string;
}>;

export type GlobeEngine = Readonly<{
  setData: (globe: Globe) => void;
  setView: (view: GlobeView) => void;
  /** Turn to face a point from the same distance (never zooms in); stops the spin. */
  turnTo: (id: string) => void;
  setSpin: (on: boolean) => void;
  /** factor < 1 moves closer, > 1 moves back. */
  zoom: (factor: number) => void;
  /** Fit the whole vault in view again. */
  reset: () => void;
  dispose: () => void;
}>;

/** three-forcegraph keeps each dot's drawn object on the node as __threeObj. */
type Point = GlobeNode & { x?: number; y?: number; z?: number; __threeObj?: Three.Object3D };
type Edge = { source: string | Point; target: string | Point; kind: GlobeLinkKind };
type Vec = { x: number; y: number; z: number };

/** OrbitControls autoRotateSpeed: one full turn about every five minutes. */
const SPIN_SPEED = 0.2;
/** Where the camera starts, and the direction it looks from when it fits the vault in view. */
const HOME_VIEW: Vec = Object.freeze({ x: 0, y: 520, z: 2300 });
const ORIGIN: Vec = Object.freeze({ x: 0, y: 0, z: 0 });
const TURN_MS = 1200;
const ZOOM_MS = 300;
/** The layout settles for this long before the first fit, unless someone moves the map first. */
const FIRST_FIT_DELAY_MS = 1500;
/** The first fit and Reset view frame this share of the points, with this much room around them. */
const FIT_SHARE = 0.95;
const FIT_MARGIN = 1.15;
const MIN_DISTANCE = 80;
const MAX_DISTANCE = 6000;
const BLOOM = Object.freeze({ strength: 0.4, radius: 0.35, threshold: 0.35 });
const BACKGROUND = "#080B10"; // --night
const ACCENT = "#74C7EF"; // --accent
const INK = "#E8ECF1"; // --ink
const MUTED = "#A6B0BE"; // --muted
/** Links to a note with more links than this are drawn fainter, so hubs do not turn into a blur. */
const HUB_DEGREE = 40;
const MAX_SOURCE_MARKERS = 12;
const STAR_COUNT = 2200;
/** How close (in CSS pixels) the pointer must be to a dot to hover or click it. */
const HIT_PX = 8;
/** On-screen sizes in CSS pixels: these stay the same however far back the camera is. */
const PX = Object.freeze({ hubText: 12, coreText: 13, nameText: 13, reticle: 34, sourceMarker: 28 });

function rgba(hex: string, alpha: number): string {
  const v = parseInt(hex.slice(1), 16);
  return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${alpha})`;
}

function tooltip(n: GlobeNode): HTMLElement {
  const box = document.createElement("div");
  box.className = "globe-tip";
  const title = document.createElement("strong");
  title.textContent = n.title;
  const what = document.createElement("span");
  what.textContent = describe(n);
  box.append(title, what);
  return box;
}

export function createGlobeEngine(
  mount: HTMLElement,
  libs: GlobeLibs,
  events: Readonly<{ onPick: (id: string) => void; onSpinStopped: () => void }>,
  options: Readonly<{ reducedMotion: boolean }>,
): GlobeEngine {
  const { ForceGraph3D: Graph, THREE, UnrealBloomPass: Bloom, OutputPass: Output } = libs;
  const turnMs = options.reducedMotion ? 0 : TURN_MS;
  const disposables: { dispose: () => void }[] = [];
  const keep = <T extends { dispose: () => void }>(x: T): T => {
    disposables.push(x);
    return x;
  };

  let view: GlobeView = { selected: null, sources: new Set(), filter: SHOW_ALL, query: "" };
  let byId = new Map<string, Point>();
  /** Set once someone drags, scrolls, or picks; the map then stops moving the camera on its own. */
  let userMoved = false;
  let firstFit = 0;
  /** World-space pickup radius, kept at HIT_PX on screen as the camera moves. */
  let hitRadius = 10;
  let spheresMuted = false;

  const end = (x: Edge["source"]): Point | undefined => (typeof x === "object" ? x : byId.get(x));
  const touchesSelected = (l: Edge) =>
    view.selected !== null && (end(l.source)?.id === view.selected || end(l.target)?.id === view.selected);
  const dimmed = (n: Point) =>
    view.query.trim() !== "" && (n.kind === "chat" || n.kind === "note") && !matchesQuery(n, view.query);

  // ---------- sprites that keep one on-screen size ----------
  const dpr = Math.max(2, window.devicePixelRatio || 1);
  /** Every live fixed-size sprite, resized when the map changes size. */
  let sized: { sprite: Three.Sprite; w: number; h: number }[] = [];

  /** World size per CSS pixel for a sprite without size attenuation (same at any distance). */
  function pixelScale(): number {
    const camera = graph.camera() as Three.PerspectiveCamera;
    return (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) / Math.max(1, mount.clientHeight);
  }

  function sizeSprite(entry: { sprite: Three.Sprite; w: number; h: number }) {
    const k = pixelScale();
    entry.sprite.scale.set(entry.w * k, entry.h * k, 1);
  }

  function screenSprite(canvas: HTMLCanvasElement, w: number, h: number, opacity: number, tracked: boolean): Three.Sprite {
    const own = <T extends { dispose: () => void }>(x: T): T => (tracked ? keep(x) : x);
    const texture = own(new THREE.CanvasTexture(canvas));
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.minFilter = THREE.LinearFilter;
    const material = own(
      new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false, opacity, sizeAttenuation: false }),
    );
    const sprite = new THREE.Sprite(material);
    const entry = { sprite, w, h };
    sizeSprite(entry);
    sized.push(entry);
    return sprite;
  }

  const fontFamily = getComputedStyle(document.documentElement).getPropertyValue("--font-martian").trim();
  /** Untracked sprites (the picked point's name) are disposed by their owner, not at teardown. */
  function textSprite(text: string, color: string, px: number, opacity: number, tracked = true): Three.Sprite {
    const font = `500 ${px}px ${fontFamily ? `${fontFamily}, ` : ""}ui-monospace, monospace`;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (!ctx) return new THREE.Sprite();
    ctx.font = font;
    const w = Math.ceil(ctx.measureText(text).width) + 12;
    const h = px + 8;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
    ctx.font = font;
    ctx.textBaseline = "middle";
    // A dark outline keeps the text readable over bright dots.
    ctx.lineWidth = 3;
    ctx.strokeStyle = BACKGROUND;
    ctx.strokeText(text, 6, h / 2);
    ctx.fillStyle = color;
    ctx.fillText(text, 6, h / 2);
    return screenSprite(canvas, w, h, opacity, tracked);
  }

  function markerSprite(px: number, draw: (ctx: CanvasRenderingContext2D) => void): Three.Sprite {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 256;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.translate(128, 128);
      ctx.strokeStyle = ACCENT;
      draw(ctx);
    }
    const sprite = screenSprite(canvas, px, px, 1, true);
    sprite.material.depthTest = false;
    sprite.visible = false;
    sprite.renderOrder = 10;
    return sprite;
  }

  // ---------- the graph ----------
  const graph: ForceGraph3DInstance<Point, Edge> = new Graph(mount, { controlType: "orbit" }) as unknown as ForceGraph3DInstance<
    Point,
    Edge
  >;
  graph
    .width(mount.clientWidth)
    .height(mount.clientHeight)
    .backgroundColor(BACKGROUND)
    .showNavInfo(false)
    .enableNodeDrag(false)
    .nodeRelSize(1)
    .nodeVal((n) => radiusOf(n) ** 3)
    .nodeResolution(10)
    .nodeOpacity(0.9)
    .nodeLabel((n) => tooltip(n))
    .nodeColor((n) => {
      if (n.id === view.selected) return "#FFFFFF";
      const base = GLOBE_COLORS[n.kind];
      return dimmed(n) ? rgba(base, 0.08) : base;
    })
    .nodeVisibility((n) => isShown(n, view.filter))
    .linkVisibility((l) => {
      const s = end(l.source);
      const t = end(l.target);
      if (!s || !t || !isShown(s, view.filter) || !isShown(t, view.filter)) return false;
      // A point's line to its own folder only shapes the layout; drawing all of them is clutter.
      if (l.kind === "tree" && (s.kind === "chat" || s.kind === "note")) return false;
      // A chat's lines to its projects show only while the chat is picked.
      if (l.kind === "topic") return touchesSelected(l);
      return true;
    })
    .linkColor((l) => {
      if (touchesSelected(l)) return rgba(ACCENT, 0.9);
      const s = end(l.source);
      const t = end(l.target);
      if (view.query.trim() && ((s && dimmed(s)) || (t && dimmed(t)))) return "rgba(244,239,227,0.03)";
      if (l.kind === "tree") return "rgba(120,160,210,0.08)";
      if ((s?.degree ?? 0) > HUB_DEGREE || (t?.degree ?? 0) > HUB_DEGREE) return "rgba(244,239,227,0.05)";
      return "rgba(244,239,227,0.14)";
    })
    .linkOpacity(1)
    .linkWidth((l) => (touchesSelected(l) ? 0.8 : 0))
    .linkDirectionalParticles((l) => (touchesSelected(l) ? 2 : 0))
    .linkDirectionalParticleWidth(1.6)
    .linkDirectionalParticleSpeed(0.006)
    .linkDirectionalParticleColor(() => ACCENT)
    .warmupTicks(80)
    .cooldownTime(20000)
    .onNodeClick((n) => {
      if (n.kind === "chat" || n.kind === "note") events.onPick(n.id);
      else turnTo(n.id);
    });

  graph.d3Force("charge")?.strength((n: Point) => (n.kind === "core" ? -900 : n.kind === "folder" ? -220 : -55));
  graph.d3Force("link")?.distance((l: Edge) => {
    if (l.kind === "tree") {
      const s = end(l.source);
      const t = end(l.target);
      return t?.kind === "core" ? 230 : s?.kind === "folder" ? 95 : 42;
    }
    return l.kind === "topic" ? 130 : 75;
  });

  const controls = graph.controls() as OrbitControls;
  controls.autoRotate = false;
  controls.autoRotateSpeed = SPIN_SPEED;
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = MIN_DISTANCE;
  controls.maxDistance = MAX_DISTANCE;
  graph.cameraPosition(HOME_VIEW, ORIGIN);

  // The composer works in linear color; the output pass converts to the screen's sRGB once, at the end.
  const bloom = new Bloom(new THREE.Vector2(mount.clientWidth, mount.clientHeight), BLOOM.strength, BLOOM.radius, BLOOM.threshold);
  const output = new Output();
  graph.postProcessingComposer().addPass(bloom);
  graph.postProcessingComposer().addPass(output);

  // ---------- the scene around the graph ----------
  const scene = graph.scene();
  // A scene background is cleared inside the composer's linear render target. The renderer's
  // clear color alone is applied before that and comes out too light (sRGB encoded twice).
  scene.background = new THREE.Color(BACKGROUND);

  const starPositions = new Float32Array(STAR_COUNT * 3);
  for (let i = 0; i < STAR_COUNT; i++) {
    const r = 1500 + Math.random() * 1800;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    starPositions.set([r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta)], i * 3);
  }
  const starGeometry = keep(new THREE.BufferGeometry());
  starGeometry.setAttribute("position", new THREE.BufferAttribute(starPositions, 3));
  const stars = new THREE.Points(
    starGeometry,
    keep(new THREE.PointsMaterial({ color: 0x7fd0ff, size: 2.2, transparent: true, opacity: 0.25, depthWrite: false })),
  );
  scene.add(stars);

  const rings = new THREE.Group();
  rings.position.y = -480;
  for (const [radius, opacity] of [[320, 0.07], [520, 0.05], [740, 0.03], [980, 0.018]] as const) {
    const ring = new THREE.Mesh(
      keep(new THREE.RingGeometry(radius, radius + 1.2, 160)),
      keep(new THREE.MeshBasicMaterial({ color: ACCENT, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false })),
    );
    ring.rotation.x = -Math.PI / 2;
    rings.add(ring);
  }
  const ticks: number[] = [];
  for (let i = 0; i < 72; i++) {
    const a = (i / 72) * Math.PI * 2;
    const len = i % 6 === 0 ? 34 : 14;
    ticks.push(Math.cos(a) * 520, 0, Math.sin(a) * 520, Math.cos(a) * (520 + len), 0, Math.sin(a) * (520 + len));
  }
  const tickGeometry = keep(new THREE.BufferGeometry());
  tickGeometry.setAttribute("position", new THREE.Float32BufferAttribute(ticks, 3));
  rings.add(new THREE.LineSegments(tickGeometry, keep(new THREE.LineBasicMaterial({ color: ACCENT, transparent: true, opacity: 0.12 }))));
  scene.add(rings);

  const coreShell = new THREE.Mesh(
    keep(new THREE.IcosahedronGeometry(24, 1)),
    keep(new THREE.MeshBasicMaterial({ color: ACCENT, wireframe: true, transparent: true, opacity: 0.25 })),
  );

  // From far back a dot is 2 or 3 pixels wide. Each dot gets an invisible pickup area that reports
  // its distance from the pointer's ray, so the dot nearest the pointer wins, and hidden dots never do.
  const hitCenter = new THREE.Vector3();
  function hitArea(n: Point): Three.Object3D {
    const hit = new THREE.Object3D();
    hit.raycast = (raycaster, intersects) => {
      if (!isShown(n, view.filter)) return;
      hit.getWorldPosition(hitCenter);
      const d2 = raycaster.ray.distanceSqToPoint(hitCenter);
      const r = Math.max(hitRadius, radiusOf(n));
      if (d2 > r * r) return;
      intersects.push({ distance: Math.sqrt(d2), point: hitCenter.clone(), object: hit });
    };
    return hit;
  }

  /** The library's own spheres would still answer the pointer when hidden; the pickup areas replace them. */
  function muteSpheres(): boolean {
    let all = true;
    for (const n of byId.values()) {
      const obj = n.__threeObj;
      if (!obj) {
        all = false;
        continue;
      }
      if (obj.userData.muted) continue;
      obj.raycast = () => {};
      obj.userData.muted = true;
    }
    return all;
  }

  graph.nodeThreeObjectExtend(true).nodeThreeObject((n) => {
    const group = new THREE.Group();
    group.add(hitArea(n));
    if (n.kind === "core") group.add(coreShell);
    const label = hubLabel(n);
    if (label) {
      const core = n.kind === "core";
      const sprite = textSprite(label, core ? INK : MUTED, core ? PX.coreText : PX.hubText, core ? 0.9 : 0.8);
      // Anchor under the text, so the name sits just above its dot at any distance.
      sprite.center.set(0.5, -0.4);
      group.add(sprite);
      const entry = sized.find((e) => e.sprite === sprite);
      if (entry) {
        hubLabels.push({ sprite, w: entry.w, h: entry.h, rank: core ? Infinity : n.children });
        hubLabels.sort((a, b) => b.rank - a.rank);
      }
    }
    return group;
  });

  // ---------- markers: the picked point, its name, and the answer's sources ----------
  const reticle = markerSprite(PX.reticle, (ctx) => {
    ctx.lineWidth = 10;
    ctx.beginPath();
    ctx.arc(0, 0, 84, 0, Math.PI * 2);
    ctx.stroke();
    ctx.lineWidth = 14;
    for (let i = 0; i < 4; i++) {
      ctx.rotate(Math.PI / 2);
      ctx.beginPath();
      ctx.moveTo(0, -124);
      ctx.lineTo(0, -98);
      ctx.stroke();
    }
  });
  scene.add(reticle);

  const sourceMarkers = Array.from({ length: MAX_SOURCE_MARKERS }, () => {
    const marker = markerSprite(PX.sourceMarker, (ctx) => {
      ctx.lineWidth = 14;
      for (let i = 0; i < 4; i++) {
        ctx.rotate(Math.PI / 2);
        ctx.beginPath();
        ctx.moveTo(-110, -60);
        ctx.lineTo(-110, -110);
        ctx.lineTo(-60, -110);
        ctx.stroke();
      }
    });
    scene.add(marker);
    return marker;
  });

  /** Folder names, biggest folder first: when names would overlap on screen, the smaller folder's name hides. */
  const hubLabels: { sprite: Three.Sprite; w: number; h: number; rank: number }[] = [];

  let nameSprite: Three.Sprite | null = null;
  let nameFor: string | null = null;
  function showName(n: Point | undefined) {
    if (nameFor === (n?.id ?? null)) return;
    if (nameSprite) {
      const old = nameSprite;
      sized = sized.filter((e) => e.sprite !== old);
      scene.remove(nameSprite);
      nameSprite.material.map?.dispose();
      nameSprite.material.dispose();
      nameSprite = null;
    }
    nameFor = n?.id ?? null;
    if (!n || n.kind === "core") return;
    const text = n.title.length > 48 ? `${n.title.slice(0, 47)}…` : n.title;
    nameSprite = textSprite(text, INK, PX.nameText, 0.95, false);
    // Sits above the ring around the picked dot.
    nameSprite.center.set(0.5, -0.9);
    nameSprite.material.depthTest = false;
    nameSprite.renderOrder = 11;
    scene.add(nameSprite);
  }

  function place(sprite: Three.Sprite, n: Point | undefined) {
    if (!n || n.x === undefined || n.y === undefined || n.z === undefined || !isShown(n, view.filter)) {
      sprite.visible = false;
      return;
    }
    sprite.visible = true;
    sprite.position.set(n.x, n.y, n.z);
  }

  const projected = new THREE.Vector3();
  type Rect = { l: number; r: number; t: number; b: number };
  /** Screen rectangle of a fixed-size sprite anchored by its center, or null when off screen. */
  function screenRect(sprite: Three.Sprite, w: number, h: number): Rect | null {
    sprite.getWorldPosition(projected).project(graph.camera());
    if (projected.z > 1 || Math.abs(projected.x) > 1.2 || Math.abs(projected.y) > 1.2) return null;
    const x = ((projected.x + 1) / 2) * mount.clientWidth;
    const y = ((1 - projected.y) / 2) * mount.clientHeight;
    const left = x - sprite.center.x * w;
    const bottom = y + sprite.center.y * h;
    return { l: left - 4, r: left + w + 4, t: bottom - h - 2, b: bottom + 2 };
  }
  const overlaps = (a: Rect, b: Rect) => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b;

  function hideOverlappingNames(picked: Point | undefined) {
    const taken: Rect[] = [];
    if (reticle.visible) {
      const rect = screenRect(reticle, PX.reticle, PX.reticle);
      if (rect) taken.push(rect);
    }
    if (nameSprite && picked && nameSprite.visible) {
      const entry = sized.find((e) => e.sprite === nameSprite);
      const rect = entry && screenRect(nameSprite, entry.w, entry.h);
      if (rect) taken.push(rect);
    }
    for (const label of hubLabels) {
      // A folder hidden by the Map's filters keeps its dot's visible flag off; skip its name too.
      let shown = true;
      for (let o = label.sprite.parent; o; o = o.parent) shown &&= o.visible;
      const rect = shown ? screenRect(label.sprite, label.w, label.h) : null;
      const free = rect !== null && !taken.some((t) => overlaps(t, rect));
      label.sprite.visible = free;
      if (free && rect) taken.push(rect);
    }
  }

  let frameId = 0;
  const frame = (t: number) => {
    frameId = requestAnimationFrame(frame);
    if (!options.reducedMotion) {
      rings.rotation.y += 0.0009;
      stars.rotation.y -= 0.00012;
      coreShell.rotation.y += 0.004;
      coreShell.rotation.x += 0.0017;
      reticle.material.rotation = (t / 4000) % (Math.PI * 2);
    }
    if (!spheresMuted) spheresMuted = muteSpheres();
    hitRadius = HIT_PX * pixelScale() * graph.camera().position.distanceTo(controls.target);
    const picked = view.selected ? byId.get(view.selected) : undefined;
    place(reticle, picked);
    if (nameSprite) {
      place(nameSprite, picked);
    }
    hideOverlappingNames(picked);
    let i = 0;
    for (const id of view.sources) {
      if (i >= sourceMarkers.length) break;
      const n = byId.get(id);
      if (!n || id === view.selected) continue;
      place(sourceMarkers[i], n);
      i++;
    }
    for (; i < sourceMarkers.length; i++) sourceMarkers[i].visible = false;
  };
  frameId = requestAnimationFrame(frame);

  // ---------- size, framing, and user input ----------
  const resize = new ResizeObserver(() => {
    const w = mount.clientWidth;
    const h = mount.clientHeight;
    if (!w || !h) return;
    graph.width(w).height(h);
    bloom.setSize(w, h);
    sized.forEach(sizeSprite);
  });
  resize.observe(mount);

  /**
   * Put the vault in view, looking from the home direction. The radius covers 95% of the
   * shown points (plus a margin), so one far-off cluster does not shrink everything else.
   */
  function fitAll(ms: number) {
    const points = [...byId.values()].filter(
      (n) => isShown(n, view.filter) && Number.isFinite(n.x) && Number.isFinite(n.y) && Number.isFinite(n.z),
    );
    if (!points.length) return;
    const center = {
      x: points.reduce((sum, n) => sum + (n.x ?? 0), 0) / points.length,
      y: points.reduce((sum, n) => sum + (n.y ?? 0), 0) / points.length,
      z: points.reduce((sum, n) => sum + (n.z ?? 0), 0) / points.length,
    };
    const distances = points
      .map((n) => Math.hypot((n.x ?? 0) - center.x, (n.y ?? 0) - center.y, (n.z ?? 0) - center.z))
      .sort((a, b) => a - b);
    const radius = Math.max(60, distances[Math.floor(FIT_SHARE * (distances.length - 1))] * FIT_MARGIN);
    const camera = graph.camera() as Three.PerspectiveCamera;
    const halfV = THREE.MathUtils.degToRad(camera.fov / 2);
    const halfH = Math.atan(Math.tan(halfV) * camera.aspect);
    const distance = Math.min(MAX_DISTANCE, radius / Math.sin(Math.min(halfV, halfH)));
    const dir = new THREE.Vector3(HOME_VIEW.x, HOME_VIEW.y, HOME_VIEW.z).normalize();
    graph.cameraPosition(
      { x: center.x + dir.x * distance, y: center.y + dir.y * distance, z: center.z + dir.z * distance },
      center,
      ms,
    );
  }

  const stopSpin = () => {
    userMoved = true;
    if (!controls.autoRotate) return;
    controls.autoRotate = false;
    events.onSpinStopped();
  };
  mount.addEventListener("pointerdown", stopSpin);
  mount.addEventListener("wheel", stopSpin, { passive: true });

  function refresh() {
    graph
      .nodeColor(graph.nodeColor())
      .nodeVisibility(graph.nodeVisibility())
      .linkVisibility(graph.linkVisibility())
      .linkColor(graph.linkColor())
      .linkWidth(graph.linkWidth())
      .linkDirectionalParticles(graph.linkDirectionalParticles());
  }

  /** Center a point in view while keeping the camera's current distance, so picking never zooms in. */
  function turnTo(id: string) {
    const n = byId.get(id);
    if (!n || n.x === undefined || n.y === undefined || n.z === undefined) return;
    stopSpin();
    const at = { x: n.x, y: n.y, z: n.z };
    const cam = graph.cameraPosition();
    const t = controls.target;
    const distance = Math.hypot(cam.x - t.x, cam.y - t.y, cam.z - t.z);
    const dx = cam.x - at.x;
    const dy = cam.y - at.y;
    const dz = cam.z - at.z;
    const k = distance / (Math.hypot(dx, dy, dz) || 1);
    graph.cameraPosition({ x: at.x + dx * k, y: at.y + dy * k, z: at.z + dz * k }, at, turnMs);
  }

  return {
    setData(globe) {
      const nodes: Point[] = globe.nodes.map((n) => ({ ...n }));
      byId = new Map(nodes.map((n) => [n.id, n]));
      const labelSprites = new Set(hubLabels.map((l) => l.sprite));
      sized = sized.filter((e) => !labelSprites.has(e.sprite));
      hubLabels.length = 0;
      spheresMuted = false;
      graph.graphData({ nodes, links: globe.links.map((l) => ({ ...l })) });
      nameFor = null;
      showName(view.selected ? byId.get(view.selected) : undefined);
      window.clearTimeout(firstFit);
      firstFit = window.setTimeout(() => {
        if (!userMoved) fitAll(turnMs);
      }, FIRST_FIT_DELAY_MS);
    },
    setView(next) {
      view = next;
      showName(view.selected ? byId.get(view.selected) : undefined);
      refresh();
    },
    turnTo,
    setSpin(on) {
      controls.autoRotate = on;
    },
    zoom(factor) {
      const cam = graph.cameraPosition();
      const t = controls.target;
      graph.cameraPosition(
        { x: t.x + (cam.x - t.x) * factor, y: t.y + (cam.y - t.y) * factor, z: t.z + (cam.z - t.z) * factor },
        { x: t.x, y: t.y, z: t.z },
        options.reducedMotion ? 0 : ZOOM_MS,
      );
    },
    reset() {
      fitAll(turnMs);
    },
    dispose() {
      window.clearTimeout(firstFit);
      cancelAnimationFrame(frameId);
      resize.disconnect();
      mount.removeEventListener("pointerdown", stopSpin);
      mount.removeEventListener("wheel", stopSpin);
      showName(undefined);
      const renderer = graph.renderer();
      graph._destructor();
      controls.dispose();
      bloom.dispose();
      output.dispose();
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
      renderer.forceContextLoss();
      mount.replaceChildren();
    },
  };
}
