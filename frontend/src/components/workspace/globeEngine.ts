import type ForceGraph3D from "3d-force-graph";
import type { ForceGraph3DInstance } from "3d-force-graph";
import type * as Three from "three";
import type { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import type { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import {
  GLOBE_COLORS,
  NO_DATE_RADIUS,
  TIME_INNER,
  arcMiddle,
  folderArcs,
  hubRadius,
  SHOW_ALL,
  describe,
  folderName,
  isShown,
  matchesQuery,
  radiusOf,
  ringRadius,
  timeScale,
  type Arc,
  type Globe,
  type GlobeFilter,
  type GlobeLinkKind,
  type GlobeNode,
} from "@/lib/vaultGlobe";

/**
 * The WebGL side of the 3D vault map. It owns the renderer, the force layout,
 * and everything drawn in the scene, from createGlobeEngine() to dispose().
 * VaultGlobe.tsx holds the React state and tells the engine what changed.
 *
 * The map is a flattened disc around the vault's center, read like a clock face:
 * the distance from the middle is age (each dated chat or note sits on the time
 * ring for its age, newest in the middle; dots without a date sit on the dashed
 * "No date" ring), and the slice is the folder (each folder owns a slice of the
 * circle sized by what it holds, with its name on the rim).
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

/** three-forcegraph keeps each dot's drawn object on the node as __threeObj; d3 adds position and velocity. */
type Point = GlobeNode & {
  x?: number;
  y?: number;
  z?: number;
  vx?: number;
  vy?: number;
  vz?: number;
  fx?: number;
  fy?: number;
  fz?: number;
  __threeObj?: Three.Object3D;
};
type Edge = { source: string | Point; target: string | Point; kind: GlobeLinkKind };
type Vec = { x: number; y: number; z: number };
type ScreenLabel = { sprite: Three.Sprite; w: number; h: number };
type FolderLabel = ScreenLabel & { node: Point; depth: number; rank: number; opacity: number; alpha: number };

/** OrbitControls autoRotateSpeed: one full turn about every five minutes. */
const SPIN_SPEED = 0.2;
/** Where the camera starts, and the direction it looks from when it fits the vault: about 40 degrees above the disc. */
const HOME_VIEW: Vec = Object.freeze({ x: 0, y: 1500, z: 1800 });
const ORIGIN: Vec = Object.freeze({ x: 0, y: 0, z: 0 });
const TURN_MS = 1200;
const ZOOM_MS = 300;
/** The layout settles for this long before the first fit, unless someone moves the map first. */
const FIRST_FIT_DELAY_MS = 1500;
/** The first fit and Reset view keep every dot and folder name inside this share of the view's half-width and half-height. */
const FIT_EDGE = 0.8;
const MIN_DISTANCE = 80;
const MAX_DISTANCE = 6000;
/** How hard a dot is pulled onto its time ring, back into its folder's slice, and toward the disc's plane. */
const TIME_PULL = 0.6;
const SLICE_PULL = 0.6;
const FLAT_PULL = 0.12;
/**
 * A folder's name shows once the camera is this close to the folder, as a share of the
 * distance that fits the whole vault (index = folder depth). Top-level names always show.
 */
const NAME_ZOOM = [Infinity, Infinity, 0.55, 0.4, 0.28];
/**
 * Where a top folder's name may sit relative to its dot (sprite center y): above it first, then
 * below, then further out. Top folder names always show, so a crowded one moves instead of hiding.
 */
const TOP_NAME_SPOTS = [-0.4, 1.4, -1.8, 2.8];
/** Opacity change per frame while a folder name fades in or out. */
const FADE_STEP = 0.1;
const BLOOM = Object.freeze({ strength: 0.4, radius: 0.35, threshold: 0.35 });
const BACKGROUND = "#080B10"; // --night
const ACCENT = "#74C7EF"; // --accent
const INK = "#E8ECF1"; // --ink
const MUTED = "#A6B0BE"; // --muted
const DIM = "#8A95A5"; // --dim
/** Links to a note with more links than this are drawn fainter, so hubs do not turn into a blur. */
const HUB_DEGREE = 40;
const MAX_SOURCE_MARKERS = 12;
/** Background stars: a dim, dense layer and a brighter, sparse one, far outside the map. */
const STAR_LAYERS = [
  { count: 1600, px: 2.5, opacity: 0.35 },
  { count: 260, px: 4.5, opacity: 0.55 },
] as const;
const STAR_RADIUS = Object.freeze({ min: 6500, max: 9000 });
/** How close (in CSS pixels) the pointer must be to a dot to hover or click it. */
const HIT_PX = 8;
/** On-screen sizes in CSS pixels: these stay the same however far back the camera is. */
const PX = Object.freeze({ folderText: 12, coreText: 13, nameText: 13, ringText: 12, reticle: 34, sourceMarker: 28 });

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
  /** Where each dot belongs from the middle (its time ring), or undefined for folders and the core. */
  let ringTarget = new Map<string, number>();
  /** The slice of the circle each dot must stay inside (its folder's). */
  let dotArcs: ReadonlyMap<string, Arc> = new Map();
  /** Set once someone drags, scrolls, or picks; the map then stops moving the camera on its own. */
  let userMoved = false;
  let firstFit = 0;
  /** The camera distance that fits the vault; folder names appear as the camera comes inside shares of it. */
  let fitDistance = Math.hypot(HOME_VIEW.x, HOME_VIEW.y, HOME_VIEW.z);
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
  let sized: ScreenLabel[] = [];

  /** World size per CSS pixel for a sprite without size attenuation (same at any distance). */
  function pixelScale(): number {
    const camera = graph.camera() as Three.PerspectiveCamera;
    return (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) / Math.max(1, mount.clientHeight);
  }

  function sizeSprite(entry: ScreenLabel) {
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
  /** Untracked sprites (the picked point's name, time ring names) are disposed by their owner, not at teardown. */
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

  function dropSprite(sprite: Three.Sprite) {
    sized = sized.filter((e) => e.sprite !== sprite);
    sprite.removeFromParent();
    sprite.material.map?.dispose();
    sprite.material.dispose();
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
      if (n.kind === "folder" && n.depth >= 2) return DIM;
      const base = GLOBE_COLORS[n.kind];
      return dimmed(n) ? rgba(base, 0.08) : base;
    })
    .nodeVisibility((n) => isShown(n, view.filter))
    .linkVisibility((l) => {
      const s = end(l.source);
      const t = end(l.target);
      if (!s || !t || !isShown(s, view.filter) || !isShown(t, view.filter)) return false;
      // Folders show as slices with names on the rim, so folder-structure lines are not drawn.
      if (l.kind === "tree") return false;
      // Dots sit by age and folder, not by links, so a link can cross the whole disc: lines
      // show only for the picked dot (what it links to, and for a chat, its projects).
      return touchesSelected(l);
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
    .warmupTicks(120)
    .cooldownTime(20000)
    .onNodeClick((n) => {
      if (n.kind === "chat" || n.kind === "note") events.onPick(n.id);
      else turnTo(n.id);
    });

  // ---------- forces: a dot's ring is its age, its slice is its folder ----------
  // Folders and the center are pinned; only the dots push each other apart, so they do not overlap.
  graph.d3Force("charge")?.strength((n: Point) => (n.kind === "chat" || n.kind === "note" ? -40 : 0));
  // Links between notes only nudge; they must not drag a dot off its ring or out of its slice.
  graph.d3Force("link")?.distance(75).strength((l: Edge) => (l.kind === "link" ? 0.02 : 0));
  // The middle of the time rings is the vault's center, so nothing may shift the layout off it.
  graph.d3Force("center", null);

  let forceNodes: Point[] = [];
  const timeForce = Object.assign(
    (alpha: number) => {
      for (const n of forceNodes) {
        const target = ringTarget.get(n.id);
        if (n.x === undefined || n.z === undefined) continue;
        if (target !== undefined) {
          const d = Math.hypot(n.x, n.z) || 1e-6;
          const k = ((target - d) / d) * TIME_PULL * alpha;
          n.vx = (n.vx ?? 0) + n.x * k;
          n.vz = (n.vz ?? 0) + n.z * k;
        }
        const arc = dotArcs.get(n.id);
        if (arc) {
          // Turn the dot back into its slice along the circle when it has drifted out of it,
          // the short way round (a dot just below 0 degrees is near a slice that starts at 0).
          const a = Math.atan2(n.z, n.x);
          const tau = Math.PI * 2;
          const past = (((a - arc.from) % tau) + tau) % tau;
          const span = arc.to - arc.from;
          const off = past <= span ? 0 : past - span < tau - past ? span - past : tau - past;
          if (off !== 0) {
            const d = Math.hypot(n.x, n.z);
            const push = off * d * SLICE_PULL * alpha;
            n.vx = (n.vx ?? 0) - Math.sin(a) * push;
            n.vz = (n.vz ?? 0) + Math.cos(a) * push;
          }
        }
        if (n.y !== undefined) n.vy = (n.vy ?? 0) - n.y * FLAT_PULL * alpha;
      }
    },
    {
      initialize: (nodes: Point[]) => {
        forceNodes = nodes;
      },
    },
  );
  graph.d3Force("time", timeForce);

  /**
   * After every layout step, put each dot exactly on its time ring and inside its slice, so the
   * rings and slices never lie; the forces above only decide where along that arc it settles.
   */
  function holdToRingsAndSlices() {
    const tau = Math.PI * 2;
    for (const n of forceNodes) {
      const r = ringTarget.get(n.id);
      if (r === undefined || n.x === undefined || n.z === undefined) continue;
      let a = Math.atan2(n.z, n.x);
      const arc = dotArcs.get(n.id);
      if (arc) {
        const past = (((a - arc.from) % tau) + tau) % tau;
        const span = arc.to - arc.from;
        if (past > span) a = past - span < tau - past ? arc.to : arc.from;
      }
      n.x = Math.cos(a) * r;
      n.z = Math.sin(a) * r;
    }
  }
  graph.onEngineTick(holdToRingsAndSlices);

  const controls = graph.controls() as OrbitControls;
  controls.autoRotate = false;
  controls.autoRotateSpeed = SPIN_SPEED;
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = MIN_DISTANCE;
  controls.maxDistance = MAX_DISTANCE;
  controls.zoomToCursor = true;
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

  // Round, soft background stars that stay put (they are scenery, so they do not move).
  const dotCanvas = document.createElement("canvas");
  dotCanvas.width = dotCanvas.height = 64;
  const dotCtx = dotCanvas.getContext("2d");
  if (dotCtx) {
    const glow = dotCtx.createRadialGradient(32, 32, 0, 32, 32, 32);
    glow.addColorStop(0, "rgba(255,255,255,1)");
    glow.addColorStop(0.35, "rgba(255,255,255,0.55)");
    glow.addColorStop(1, "rgba(255,255,255,0)");
    dotCtx.fillStyle = glow;
    dotCtx.fillRect(0, 0, 64, 64);
  }
  const dotTexture = keep(new THREE.CanvasTexture(dotCanvas));
  const pixelRatio = graph.renderer().getPixelRatio();
  for (const layer of STAR_LAYERS) {
    const positions = new Float32Array(layer.count * 3);
    for (let i = 0; i < layer.count; i++) {
      const r = STAR_RADIUS.min + Math.random() * (STAR_RADIUS.max - STAR_RADIUS.min);
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      positions.set([r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta)], i * 3);
    }
    const geometry = keep(new THREE.BufferGeometry());
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const material = keep(
      new THREE.PointsMaterial({
        map: dotTexture,
        color: 0x9fd6ff,
        size: layer.px * pixelRatio,
        sizeAttenuation: false,
        transparent: true,
        opacity: layer.opacity,
        depthWrite: false,
        alphaTest: 0.02,
      }),
    );
    scene.add(new THREE.Points(geometry, material));
  }

  // The time rings: one circle per age, in the disc's plane, with its name on the side facing the camera.
  const rings = new THREE.Group();
  scene.add(rings);
  let ringLabels: { sprite: Three.Sprite; radius: number }[] = [];

  function circle(radius: number, color: string, opacity: number, dashed: boolean): Three.LineLoop {
    const points: number[] = [];
    for (let i = 0; i < 192; i++) {
      const a = (i / 192) * Math.PI * 2;
      points.push(Math.cos(a) * radius, 0, Math.sin(a) * radius);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    const material = dashed
      ? new THREE.LineDashedMaterial({ color, transparent: true, opacity, dashSize: 14, gapSize: 12, depthWrite: false })
      : new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false });
    const loop = new THREE.LineLoop(geometry, material);
    if (dashed) loop.computeLineDistances();
    return loop;
  }

  function buildRings(globe: Globe, nowMs: number) {
    for (const child of [...rings.children]) {
      const line = child as Three.Line;
      line.geometry.dispose();
      (line.material as Three.Material).dispose();
      line.removeFromParent();
    }
    ringLabels.forEach((l) => dropSprite(l.sprite));
    ringLabels = [];
    const dates = globe.nodes.flatMap((n) => (n.date ? [n.date] : []));
    const scale = timeScale(dates, nowMs);
    for (const ring of scale.rings) {
      rings.add(circle(ring.radius, ACCENT, 0.22, false));
      const sprite = textSprite(ring.label, ACCENT, PX.ringText, 0.85, false);
      sprite.center.set(0.5, -0.2);
      scene.add(sprite);
      ringLabels.push({ sprite, radius: ring.radius });
    }
    if (globe.nodes.some((n) => (n.kind === "chat" || n.kind === "note") && !n.date)) {
      rings.add(circle(NO_DATE_RADIUS, MUTED, 0.2, true));
      const sprite = textSprite("No date", MUTED, PX.ringText, 0.8, false);
      sprite.center.set(0.5, -0.2);
      scene.add(sprite);
      ringLabels.push({ sprite, radius: NO_DATE_RADIUS });
    }
    ringTarget = new Map();
    for (const n of globe.nodes) {
      const r = ringRadius(n, scale, nowMs);
      if (r !== null) ringTarget.set(n.id, r);
    }
  }

  /** Faint lines where one top folder's slice ends and the next begins. */
  function buildDividers(folders: ReadonlyMap<string, Arc>, topFolders: readonly string[]) {
    const points: number[] = [];
    const outer = NO_DATE_RADIUS + 40;
    for (const path of topFolders) {
      const arc = folders.get(path);
      if (!arc) continue;
      const a = arc.from;
      points.push(Math.cos(a) * TIME_INNER, 0, Math.sin(a) * TIME_INNER, Math.cos(a) * outer, 0, Math.sin(a) * outer);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    const material = new THREE.LineBasicMaterial({ color: MUTED, transparent: true, opacity: 0.12, depthWrite: false });
    rings.add(new THREE.LineSegments(geometry, material));
  }

  // ---------- folder names: every folder has one; deeper folders show as the camera comes closer ----------
  const folderLabels: FolderLabel[] = [];

  graph.nodeThreeObjectExtend(true).nodeThreeObject((n) => {
    const group = new THREE.Group();
    group.add(hitArea(n));
    const name = folderName(n);
    if (name) {
      const core = n.kind === "core";
      const top = n.depth <= 1;
      const opacity = core ? 0.9 : top ? 0.85 : 0.8;
      const sprite = textSprite(name, core ? INK : top ? MUTED : DIM, core ? PX.coreText : PX.folderText, opacity);
      // Anchor under the text, so the name sits just above its dot at any distance.
      sprite.center.set(0.5, -0.4);
      sprite.visible = false;
      group.add(sprite);
      const entry = sized.find((e) => e.sprite === sprite);
      if (entry) {
        folderLabels.push({ ...entry, node: n, depth: n.depth, rank: n.children, opacity, alpha: 0 });
        // Shallow folders first, then bigger ones: they keep their names when names would overlap.
        folderLabels.sort((a, b) => a.depth - b.depth || b.rank - a.rank);
      }
    }
    return group;
  });

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

  let nameSprite: Three.Sprite | null = null;
  let nameFor: string | null = null;
  function showName(n: Point | undefined) {
    if (nameFor === (n?.id ?? null)) return;
    if (nameSprite) {
      dropSprite(nameSprite);
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
  const worldSpot = new THREE.Vector3();
  type Rect = { l: number; r: number; t: number; b: number };
  /**
   * Screen rectangle of a fixed-size sprite anchored by its center, or null when off screen.
   * `at` is the sprite's world position when the caller knows it (a folder name sits on its dot).
   */
  function screenRect(sprite: Three.Sprite, w: number, h: number, at?: Point): Rect | null {
    if (at) projected.set(at.x ?? 0, at.y ?? 0, at.z ?? 0).project(graph.camera());
    else sprite.getWorldPosition(projected).project(graph.camera());
    if (projected.z > 1 || Math.abs(projected.x) > 1.2 || Math.abs(projected.y) > 1.2) return null;
    const x = ((projected.x + 1) / 2) * mount.clientWidth;
    const y = ((1 - projected.y) / 2) * mount.clientHeight;
    const left = x - sprite.center.x * w;
    const bottom = y + sprite.center.y * h;
    return { l: left - 4, r: left + w + 4, t: bottom - h - 2, b: bottom + 2 };
  }
  const overlaps = (a: Rect, b: Rect) => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b;
  const entryFor = (sprite: Three.Sprite) => sized.find((e) => e.sprite === sprite);

  /** Put each time ring's name on the side of its ring that faces the camera. */
  function placeRingLabels() {
    const cam = graph.camera().position;
    const angle = Math.atan2(cam.x, cam.z);
    for (const label of ringLabels) {
      label.sprite.position.set(Math.sin(angle) * label.radius, 0, Math.cos(angle) * label.radius);
    }
  }

  /**
   * Decide which folder names show: top folders always (moving above or below their dot to stay
   * clear); a deeper folder once the camera is close enough to it and only where it does not cover
   * another name (shallower and bigger folders win).
   */
  function updateFolderNames(picked: Point | undefined) {
    const taken: Rect[] = [];
    const reserve = (sprite: Three.Sprite | null, w?: number, h?: number) => {
      if (!sprite || !sprite.visible) return;
      const size = w !== undefined && h !== undefined ? { w, h } : entryFor(sprite);
      const rect = size && screenRect(sprite, size.w, size.h);
      if (rect) taken.push(rect);
    };
    reserve(reticle, PX.reticle, PX.reticle);
    if (picked) reserve(nameSprite);
    for (const ring of ringLabels) {
      const size = entryFor(ring.sprite);
      const rect = size ? screenRect(ring.sprite, size.w, size.h) : null;
      ring.sprite.visible = rect !== null && !taken.some((t) => overlaps(t, rect));
      if (ring.sprite.visible && rect) taken.push(rect);
    }

    const cam = graph.camera().position;
    for (const label of folderLabels) {
      // A folder hidden by the Map's filters keeps its dot's visible flag off; skip its name too.
      let shown = true;
      for (let o = label.sprite.parent; o; o = o.parent) shown &&= o.visible;
      let wanted = shown;
      if (wanted && label.depth >= 2) {
        const limit = NAME_ZOOM[Math.min(label.depth, NAME_ZOOM.length - 1)] * fitDistance;
        worldSpot.set(label.node.x ?? 0, label.node.y ?? 0, label.node.z ?? 0);
        wanted = worldSpot.distanceTo(cam) < limit;
      }
      let rect: Rect | null = null;
      let show = false;
      if (wanted && label.depth === 1) {
        for (const spot of TOP_NAME_SPOTS) {
          label.sprite.center.y = spot;
          rect = screenRect(label.sprite, label.w, label.h, label.node);
          if (rect && !taken.some((t) => overlaps(t, rect as Rect))) break;
        }
        if (!rect || taken.some((t) => overlaps(t, rect as Rect))) {
          label.sprite.center.y = TOP_NAME_SPOTS[0];
          rect = screenRect(label.sprite, label.w, label.h, label.node);
        }
        show = rect !== null;
      } else if (wanted) {
        rect = screenRect(label.sprite, label.w, label.h, label.node);
        show = rect !== null && !taken.some((t) => overlaps(t, rect as Rect));
      }
      if (show && rect) taken.push(rect);
      const goal = show ? 1 : 0;
      label.alpha = options.reducedMotion
        ? goal
        : label.alpha + Math.max(-FADE_STEP, Math.min(FADE_STEP, goal - label.alpha));
      label.sprite.material.opacity = label.alpha * label.opacity;
      label.sprite.visible = label.alpha > 0.01;
    }
  }

  let frameId = 0;
  const frame = () => {
    frameId = requestAnimationFrame(frame);
    if (!spheresMuted) spheresMuted = muteSpheres();
    hitRadius = HIT_PX * pixelScale() * graph.camera().position.distanceTo(controls.target);
    const picked = view.selected ? byId.get(view.selected) : undefined;
    place(reticle, picked);
    if (nameSprite) place(nameSprite, picked);
    placeRingLabels();
    updateFolderNames(picked);
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
   * Put the whole vault in view, looking at its center from the home direction: the closest
   * distance at which every shown dot and folder name stays inside FIT_EDGE of the view.
   */
  const fitProbe = new THREE.Vector3();
  function fitAll(ms: number) {
    const points = [...byId.values()].filter(
      (n) => isShown(n, view.filter) && Number.isFinite(n.x) && Number.isFinite(n.y) && Number.isFinite(n.z),
    );
    if (!points.length) return;
    const dir = new THREE.Vector3(HOME_VIEW.x, HOME_VIEW.y, HOME_VIEW.z).normalize();
    const probe = (graph.camera() as Three.PerspectiveCamera).clone();
    const fits = (distance: number) => {
      probe.position.set(dir.x * distance, dir.y * distance, dir.z * distance);
      probe.lookAt(ORIGIN.x, ORIGIN.y, ORIGIN.z);
      probe.updateMatrixWorld();
      return points.every((n) => {
        fitProbe.set(n.x ?? 0, n.y ?? 0, n.z ?? 0).project(probe);
        return fitProbe.z < 1 && Math.abs(fitProbe.x) <= FIT_EDGE && Math.abs(fitProbe.y) <= FIT_EDGE;
      });
    };
    // Binary search between "too close" and "far enough" for the nearest distance that fits.
    let near = MIN_DISTANCE;
    let far = MAX_DISTANCE;
    if (fits(near)) far = near;
    for (let i = 0; i < 24 && far - near > 1; i++) {
      const mid = (near + far) / 2;
      if (fits(mid)) far = mid;
      else near = mid;
    }
    fitDistance = far;
    graph.cameraPosition({ x: dir.x * far, y: dir.y * far, z: dir.z * far }, ORIGIN, ms);
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
      .linkWidth(graph.linkWidth());
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
      const nowMs = Date.now();
      const arcs = folderArcs(globe);
      dotArcs = arcs.dots;
      buildRings(globe, nowMs);
      const topFolders = globe.nodes.filter((n) => n.kind === "folder" && n.depth === 1).map((n) => n.path);
      buildDividers(arcs.folders, arcs.dots.size ? [...topFolders, ""] : topFolders);
      const nodes: Point[] = globe.nodes.map((n): Point => {
        // The vault's center is the middle of the time rings; each folder's name is pinned on the rim of its slice.
        if (n.kind === "core") return { ...n, x: 0, y: 0, z: 0, fx: 0, fy: 0, fz: 0 };
        if (n.kind === "folder") {
          const a = arcMiddle(arcs.folders.get(n.path) ?? { from: 0, to: 0 });
          const r = hubRadius(n.depth);
          return { ...n, x: Math.cos(a) * r, y: 0, z: Math.sin(a) * r, fx: Math.cos(a) * r, fy: 0, fz: Math.sin(a) * r };
        }
        // Dots start on their ring, somewhere inside their slice, so the layout settles fast and true.
        const arc = arcs.dots.get(n.id) ?? { from: 0, to: Math.PI * 2 };
        const a = arc.from + Math.random() * (arc.to - arc.from);
        const r = ringTarget.get(n.id) ?? NO_DATE_RADIUS;
        return { ...n, x: Math.cos(a) * r, y: (Math.random() - 0.5) * 40, z: Math.sin(a) * r };
      });
      byId = new Map(nodes.map((n) => [n.id, n]));
      folderLabels.forEach((l) => {
        sized = sized.filter((e) => e.sprite !== l.sprite);
      });
      folderLabels.length = 0;
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
      ringLabels.forEach((l) => dropSprite(l.sprite));
      for (const child of [...rings.children]) {
        const line = child as Three.Line;
        line.geometry.dispose();
        (line.material as Three.Material).dispose();
      }
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
