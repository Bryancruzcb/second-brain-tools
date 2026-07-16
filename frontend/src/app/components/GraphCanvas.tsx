"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
} from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Html, Line, OrbitControls, Stars } from '@react-three/drei';
import { Bloom, EffectComposer } from '@react-three/postprocessing';
import { Maximize, Network, Search, Tag } from 'lucide-react';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import * as THREE from 'three';
import type { GraphEdge, GraphNode } from '../types';

const TAG_PALETTE: Record<string, string> = {
  school: '#61a8ff',
  coding: '#c9f568',
  personal: '#ff9278',
  'second-brain': '#b89aff',
  projects: '#68d9b0',
  career: '#f2c14e',
  memory: '#f58db6',
};

const DEFAULT_PALETTE = '#89a0b8';
const GHOST_EDGE_COLOR = '#74d8cb';

const CLUSTER_COLORS = [
  '#ff8170',
  '#e8b94f',
  '#68d9b0',
  '#61a8ff',
  '#a894f4',
  '#e986b6',
  '#70c8c0',
  '#e97789',
];

const REPULSION = 25000;
const ATTRACTION = 0.05;
const CENTER_PULL = 0.005;
const DAMPING = 0.75;
const MAX_VELOCITY = 5;
const IDEAL_DISTANCE = 100;
const MAX_REPULSION_DISTANCE_SQUARED = 300 * 300;

type Point3 = [number, number, number];
type Color3 = [number, number, number];
type EdgeColors = [Color3, Color3];

const DEFAULT_CAMERA_POSITION: Point3 = [0, 0, 1000];
const WHITE_EDGE_COLORS: EdgeColors = [[1, 1, 1], [1, 1, 1]];
const GHOST_EDGE_COLORS: EdgeColors = [colorTuple(GHOST_EDGE_COLOR), colorTuple(GHOST_EDGE_COLOR)];
const EMPTY_NODES: GraphNode[] = [];
const EMPTY_EDGES: GraphEdge[] = [];

interface GraphCssVariables extends CSSProperties {
  '--graph-node-color'?: string;
  '--graph-tag-color'?: string;
}

interface WorkingNode extends GraphNode {
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
}

interface LayoutNode extends GraphNode {
  position: Point3;
  radius: number;
  color: string;
  colorTuple: Color3;
  connections: number;
  normalizedTags: string[];
  isLabeled: boolean;
}

interface LayoutEdge extends GraphEdge {
  key: string;
  sourceNode: LayoutNode;
  targetNode: LayoutNode;
  points: [Point3, Point3];
  colors: EdgeColors;
}

interface GraphLayout {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  nodeById: Map<string, LayoutNode>;
}

interface ResolvedEdge {
  edge: GraphEdge;
  key: string;
  sourceIndex: number;
  targetIndex: number;
}

interface GraphSceneProps {
  layout: GraphLayout;
  selectedNodeId: string | null;
  activeFilters: Set<string>;
  orbitRef: RefObject<OrbitControlsImpl | null>;
  prefersReducedMotion: boolean;
  starCount: number;
  onNodeSelect: (node: LayoutNode, shiftKey: boolean) => void;
}

interface CameraFocusProps {
  position: Point3 | null;
  controlsRef: RefObject<OrbitControlsImpl | null>;
  prefersReducedMotion: boolean;
}

interface Props {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
  selectedNodeId?: string | null;
  onNodeSelect?: (node: GraphNode | null, shiftKey?: boolean) => void;
  isExpanded?: boolean;
}

function normalizeTag(tag: string) {
  return tag.trim().replace(/^#/, '').toLowerCase();
}

function getNodeColor(node: GraphNode) {
  if (node.cluster_id !== undefined && node.cluster_id >= 0) {
    return CLUSTER_COLORS[node.cluster_id % CLUSTER_COLORS.length];
  }

  for (const tag of node.tags) {
    const paletteColor = TAG_PALETTE[normalizeTag(tag)];
    if (paletteColor) return paletteColor;
  }

  return DEFAULT_PALETTE;
}

function colorTuple(color: string): Color3 {
  const value = new THREE.Color(color);
  return [value.r, value.g, value.b];
}

function hashString(value: string, salt: number) {
  let hash = (2166136261 ^ salt) >>> 0;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  hash ^= hash >>> 16;
  hash = Math.imul(hash, 2246822507);
  hash ^= hash >>> 13;
  return (hash >>> 0) / 4294967295;
}

function createInitialPosition(nodeId: string, spread: number): Point3 {
  const longitude = hashString(nodeId, 0x51f15e) * Math.PI * 2;
  const vertical = hashString(nodeId, 0x9e3779) * 2 - 1;
  const radial = spread * (0.35 + hashString(nodeId, 0x85ebca) * 0.65);
  const horizontal = Math.sqrt(Math.max(0, 1 - vertical * vertical));

  return [
    Math.cos(longitude) * horizontal * radial,
    vertical * radial * 0.72,
    Math.sin(longitude) * horizontal * radial,
  ];
}

function buildGraphLayout(nodes: GraphNode[], edges: GraphEdge[]): GraphLayout {
  if (nodes.length === 0) {
    return { nodes: [], edges: [], nodeById: new Map() };
  }

  const indexById = new Map<string, number>();
  nodes.forEach((node, index) => indexById.set(node.id, index));

  const connections = new Map<string, number>();
  const resolvedEdges: ResolvedEdge[] = [];

  edges.forEach((edge, index) => {
    const sourceIndex = indexById.get(edge.source);
    const targetIndex = indexById.get(edge.target);
    if (sourceIndex === undefined || targetIndex === undefined) return;

    connections.set(edge.source, (connections.get(edge.source) ?? 0) + 1);
    connections.set(edge.target, (connections.get(edge.target) ?? 0) + 1);
    resolvedEdges.push({
      edge,
      sourceIndex,
      targetIndex,
      key: `${edge.source}:${edge.target}:${edge.is_ghost ? 'ghost' : 'link'}:${index}`,
    });
  });

  const spread = Math.min(520, Math.max(180, Math.sqrt(nodes.length) * 50));
  const workingNodes: WorkingNode[] = nodes.map((node) => {
    const [x, y, z] = createInitialPosition(node.id, spread);
    return { ...node, x, y, z, vx: 0, vy: 0, vz: 0 };
  });

  const iterations = nodes.length <= 250 ? 120 : nodes.length <= 500 ? 90 : 60;

  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const cooling = Math.max(0.08, 1 - iteration / iterations);

    for (let sourceIndex = 0; sourceIndex < workingNodes.length; sourceIndex += 1) {
      const source = workingNodes[sourceIndex];
      for (let targetIndex = sourceIndex + 1; targetIndex < workingNodes.length; targetIndex += 1) {
        const target = workingNodes[targetIndex];
        let dx = target.x - source.x;
        let dy = target.y - source.y;
        let dz = target.z - source.z;
        let distanceSquared = dx * dx + dy * dy + dz * dz;

        if (distanceSquared > MAX_REPULSION_DISTANCE_SQUARED) continue;
        if (distanceSquared < 1) {
          dx = (sourceIndex + 1) * 0.01;
          dy = (targetIndex + 1) * 0.01;
          dz = 0.01;
          distanceSquared = dx * dx + dy * dy + dz * dz;
        }

        const distance = Math.sqrt(distanceSquared);
        const force = (REPULSION / distanceSquared) * cooling;
        const forceX = (dx / distance) * force;
        const forceY = (dy / distance) * force;
        const forceZ = (dz / distance) * force;

        source.vx -= forceX;
        source.vy -= forceY;
        source.vz -= forceZ;
        target.vx += forceX;
        target.vy += forceY;
        target.vz += forceZ;
      }
    }

    resolvedEdges.forEach(({ sourceIndex, targetIndex }) => {
      const source = workingNodes[sourceIndex];
      const target = workingNodes[targetIndex];
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const dz = target.z - source.z;
      const distance = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
      const force = ATTRACTION * (distance - IDEAL_DISTANCE) * cooling;
      const forceX = (dx / distance) * force;
      const forceY = (dy / distance) * force;
      const forceZ = (dz / distance) * force;

      source.vx += forceX;
      source.vy += forceY;
      source.vz += forceZ;
      target.vx -= forceX;
      target.vy -= forceY;
      target.vz -= forceZ;
    });

    workingNodes.forEach((node) => {
      node.vx = (node.vx - node.x * CENTER_PULL * cooling) * DAMPING;
      node.vy = (node.vy - node.y * CENTER_PULL * cooling) * DAMPING;
      node.vz = (node.vz - node.z * CENTER_PULL * cooling) * DAMPING;

      const speed = Math.sqrt(node.vx ** 2 + node.vy ** 2 + node.vz ** 2);
      if (speed > MAX_VELOCITY) {
        const scale = MAX_VELOCITY / speed;
        node.vx *= scale;
        node.vy *= scale;
        node.vz *= scale;
      }

      node.x += node.vx;
      node.y += node.vy;
      node.z += node.vz;
    });
  }

  const center = workingNodes.reduce(
    (value, node) => {
      value.x += node.x;
      value.y += node.y;
      value.z += node.z;
      return value;
    },
    { x: 0, y: 0, z: 0 },
  );
  center.x /= workingNodes.length;
  center.y /= workingNodes.length;
  center.z /= workingNodes.length;

  const labelBudget = nodes.length <= 48 ? nodes.length : Math.min(34, Math.ceil(nodes.length * 0.16));
  const labeledNodeIds = new Set(
    [...nodes]
      .sort((a, b) => (connections.get(b.id) ?? 0) - (connections.get(a.id) ?? 0))
      .slice(0, labelBudget)
      .map((node) => node.id),
  );

  const layoutNodes: LayoutNode[] = workingNodes.map((node) => {
    const color = getNodeColor(node);
    const connectionCount = connections.get(node.id) ?? 0;
    return {
      id: node.id,
      label: node.label,
      tags: node.tags,
      cluster_id: node.cluster_id,
      position: [node.x - center.x, node.y - center.y, node.z - center.z],
      radius: 4 + Math.min(connectionCount * 0.8, 8),
      color,
      colorTuple: colorTuple(color),
      connections: connectionCount,
      normalizedTags: node.tags.map(normalizeTag).filter(Boolean),
      isLabeled: labeledNodeIds.has(node.id),
    };
  });

  const nodeById = new Map(layoutNodes.map((node) => [node.id, node]));
  const layoutEdges: LayoutEdge[] = resolvedEdges.map(({ edge, key, sourceIndex, targetIndex }) => {
    const sourceNode = layoutNodes[sourceIndex];
    const targetNode = layoutNodes[targetIndex];
    return {
      ...edge,
      key,
      sourceNode,
      targetNode,
      points: [sourceNode.position, targetNode.position],
      colors: edge.is_ghost
        ? GHOST_EDGE_COLORS
        : [sourceNode.colorTuple, targetNode.colorTuple],
    };
  });

  return { nodes: layoutNodes, edges: layoutEdges, nodeById };
}

function matchesFilters(node: LayoutNode, activeFilters: Set<string>) {
  return activeFilters.size === 0
    || node.normalizedTags.some((tag) => activeFilters.has(tag));
}

function usePrefersReducedMotion() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() => (
    typeof window !== 'undefined'
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false
  ));

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handleChange = (event: MediaQueryListEvent) => setPrefersReducedMotion(event.matches);
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  return prefersReducedMotion;
}

function CameraFocus({ position, controlsRef, prefersReducedMotion }: CameraFocusProps) {
  const focusTarget = useMemo(() => new THREE.Vector3(), []);

  useFrame(() => {
    const controls = controlsRef.current;
    if (!controls || !position) return;

    focusTarget.set(...position);
    if (controls.target.distanceToSquared(focusTarget) < 0.01) return;

    if (prefersReducedMotion) controls.target.copy(focusTarget);
    else controls.target.lerp(focusTarget, 0.08);
    controls.update();
  });

  return null;
}

function GraphScene({
  layout,
  selectedNodeId,
  activeFilters,
  orbitRef,
  prefersReducedMotion,
  starCount,
  onNodeSelect,
}: GraphSceneProps) {
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const sphereGeometry = useMemo(() => new THREE.SphereGeometry(1, 20, 20), []);
  const selectedPosition = selectedNodeId
    ? layout.nodeById.get(selectedNodeId)?.position ?? null
    : null;

  return (
    <group>
      <Stars
        radius={500}
        depth={200}
        count={starCount}
        factor={4}
        saturation={0}
        fade
        speed={prefersReducedMotion ? 0 : 0.25}
      />

      {layout.edges.map((edge) => {
        const isHovered = hoveredNodeId === edge.sourceNode.id || hoveredNodeId === edge.targetNode.id;
        const isMatch = matchesFilters(edge.sourceNode, activeFilters)
          && matchesFilters(edge.targetNode, activeFilters);
        const opacity = isMatch ? (isHovered ? 1 : 0.38) : 0.025;

        return (
          <Line
            key={edge.key}
            points={edge.points}
            vertexColors={isHovered ? WHITE_EDGE_COLORS : edge.colors}
            dashed={Boolean(edge.is_ghost)}
            dashScale={1}
            dashSize={4}
            gapSize={2}
            lineWidth={edge.is_ghost ? (isHovered ? 2 : 1) : (isHovered ? 3 : 1.4)}
            transparent
            opacity={edge.is_ghost ? opacity * 0.45 : opacity}
          />
        );
      })}

      {layout.nodes.map((node) => {
        const isHovered = hoveredNodeId === node.id;
        const isSelected = selectedNodeId === node.id;
        const isMatch = matchesFilters(node, activeFilters);
        const nodeScale = node.radius * (isHovered || isSelected ? 1.45 : 1);

        return (
          <group key={node.id} position={node.position}>
            <mesh
              geometry={sphereGeometry}
              scale={nodeScale}
              onPointerOver={(event) => {
                event.stopPropagation();
                setHoveredNodeId(node.id);
              }}
              onPointerOut={(event) => {
                event.stopPropagation();
                setHoveredNodeId(null);
              }}
              onClick={(event) => {
                event.stopPropagation();
                onNodeSelect(node, event.shiftKey);
              }}
            >
              <meshStandardMaterial
                color={isHovered || isSelected ? '#ffffff' : node.color}
                emissive={node.color}
                emissiveIntensity={isMatch ? (isHovered || isSelected ? 3.5 : 1.65) : 0}
                transparent
                opacity={isMatch ? 0.92 : 0.1}
                toneMapped={false}
                roughness={0.25}
                metalness={0.72}
              />
            </mesh>

            {(node.isLabeled || isHovered || isSelected) && (
              <Html
                center
                position={[0, node.radius * 2.25, 0]}
                distanceFactor={420}
                zIndexRange={[100, 0]}
              >
                <span
                  className={`graph-node-label${isHovered || isSelected ? ' is-emphasized' : ''}`}
                  style={{ '--graph-node-color': node.color } as GraphCssVariables}
                >
                  {node.label}
                </span>
              </Html>
            )}
          </group>
        );
      })}

      <CameraFocus
        position={selectedPosition}
        controlsRef={orbitRef}
        prefersReducedMotion={prefersReducedMotion}
      />
    </group>
  );
}

export default function GraphCanvas({
  nodes,
  edges,
  selectedNodeId,
  onNodeSelect,
  isExpanded = false,
}: Props) {
  const graphNodes = nodes ?? EMPTY_NODES;
  const graphEdges = edges ?? EMPTY_EDGES;
  const layout = useMemo(
    () => buildGraphLayout(graphNodes, graphEdges),
    [graphNodes, graphEdges],
  );

  const [searchQuery, setSearchQuery] = useState('');
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [activeResultIndex, setActiveResultIndex] = useState(0);
  const [activeFilters, setActiveFilters] = useState<Set<string>>(() => new Set());
  const orbitRef = useRef<OrbitControlsImpl>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchId = useId();
  const prefersReducedMotion = usePrefersReducedMotion();

  const resolvedSelectedNodeId = selectedNodeId ?? null;
  const normalizedQuery = searchQuery.trim().toLowerCase();
  const searchResults = useMemo(() => {
    if (!normalizedQuery) return graphNodes.slice(0, 5);
    return graphNodes
      .filter((node) => node.label.toLowerCase().includes(normalizedQuery))
      .slice(0, 5);
  }, [graphNodes, normalizedQuery]);

  const listboxId = `${searchId}-results`;
  const activeOptionIndex = Math.min(activeResultIndex, Math.max(searchResults.length - 1, 0));
  const activeOptionId = isSearchOpen && searchResults.length > 0
    ? `${listboxId}-option-${activeOptionIndex}`
    : undefined;

  const handleNodeSelect = useCallback((node: GraphNode, shiftKey = false) => {
    onNodeSelect?.(node, shiftKey);
  }, [onNodeSelect]);

  const selectSearchResult = useCallback((node: GraphNode) => {
    setSearchQuery('');
    setIsSearchOpen(false);
    setActiveResultIndex(0);
    onNodeSelect?.(node, false);
  }, [onNodeSelect]);

  const handleResetView = useCallback(() => {
    onNodeSelect?.(null, false);
    setSearchQuery('');
    setIsSearchOpen(false);
    setActiveResultIndex(0);

    const controls = orbitRef.current;
    if (!controls) return;
    controls.target.set(0, 0, 0);
    controls.object.position.set(...DEFAULT_CAMERA_POSITION);
    controls.update();
  }, [onNodeSelect]);

  const toggleFilter = useCallback((tag: string) => {
    setActiveFilters((current) => {
      const next = new Set(current);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  }, []);

  const handleSearchKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      setIsSearchOpen(true);
      if (searchResults.length === 0) return;
      setActiveResultIndex((current) => (
        event.key === 'ArrowDown'
          ? (current + 1) % searchResults.length
          : (current - 1 + searchResults.length) % searchResults.length
      ));
      return;
    }

    if (event.key === 'Enter' && searchResults.length > 0) {
      event.preventDefault();
      selectSearchResult(searchResults[activeOptionIndex]);
      return;
    }

    if (event.key === 'Escape') {
      event.preventDefault();
      setIsSearchOpen(false);
      setActiveResultIndex(0);
      searchInputRef.current?.blur();
    }
  };

  if (graphNodes.length === 0) {
    return (
      <div className="empty-state graph-empty-state" role="status">
        <div className="empty-state-icon" aria-hidden="true"><Network size={32} /></div>
        <div className="empty-state-title">No graph data yet</div>
        <div className="empty-state-desc">
          Scan your vault to map its notes and connections into this interactive knowledge graph.
        </div>
      </div>
    );
  }

  return (
    <section
      className={`graph-container${isExpanded ? ' graph-container--expanded' : ''}`}
      aria-label="Interactive knowledge graph"
    >
      <div className="graph-controls">
        <div className="graph-search">
          <Search size={16} aria-hidden="true" />
          <input
            ref={searchInputRef}
            type="search"
            role="combobox"
            aria-label="Search graph nodes"
            aria-autocomplete="list"
            aria-expanded={isSearchOpen && searchResults.length > 0}
            aria-controls={listboxId}
            aria-activedescendant={activeOptionId}
            autoComplete="off"
            placeholder="Search notes…"
            value={searchQuery}
            onChange={(event) => {
              setSearchQuery(event.target.value);
              setIsSearchOpen(true);
              setActiveResultIndex(0);
            }}
            onFocus={() => {
              setIsSearchOpen(true);
              setActiveResultIndex(0);
            }}
            onBlur={() => setIsSearchOpen(false)}
            onKeyDown={handleSearchKeyDown}
          />

          {isSearchOpen && searchResults.length > 0 && (
            <ul className="graph-search-results" id={listboxId} role="listbox">
              {searchResults.map((result, index) => (
                <li
                  key={result.id}
                  id={`${listboxId}-option-${index}`}
                  className={index === activeOptionIndex ? 'is-active' : undefined}
                  role="option"
                  aria-selected={resolvedSelectedNodeId === result.id}
                  onPointerMove={() => setActiveResultIndex(index)}
                  onPointerDown={(event) => {
                    event.preventDefault();
                    selectSearchResult(result);
                  }}
                >
                  <span>{result.label}</span>
                  <small>{result.tags.length > 0 ? `#${normalizeTag(result.tags[0])}` : 'Note'}</small>
                </li>
              ))}
            </ul>
          )}
        </div>

        <button
          type="button"
          className="graph-icon-button"
          onClick={handleResetView}
          aria-label="Reset graph camera"
          title="Reset graph camera"
        >
          <Maximize size={18} aria-hidden="true" />
        </button>
      </div>

      <div className="graph-filter-bar" role="group" aria-label="Filter graph by tag">
        {Object.entries(TAG_PALETTE).map(([tag, color]) => {
          const isActive = activeFilters.has(tag);
          return (
            <button
              key={tag}
              type="button"
              className={`graph-filter${isActive ? ' is-active' : ''}`}
              style={{ '--graph-tag-color': color } as GraphCssVariables}
              aria-pressed={isActive}
              onClick={() => toggleFilter(tag)}
            >
              <Tag size={12} aria-hidden="true" />
              <span>#{tag}</span>
            </button>
          );
        })}
      </div>

      <Canvas
        className="graph-canvas"
        camera={{ position: DEFAULT_CAMERA_POSITION, fov: 60, near: 1, far: 10000 }}
        dpr={[1, 1.5]}
        gl={{ antialias: false, powerPreference: 'high-performance' }}
        role="img"
        aria-label={`${graphNodes.length} notes connected by ${graphEdges.length} links in a three-dimensional map`}
        onPointerMissed={handleResetView}
      >
        <color attach="background" args={['#0d1117']} />
        <ambientLight intensity={0.5} />
        <pointLight position={[100, 100, 100]} intensity={1} />
        <GraphScene
          layout={layout}
          selectedNodeId={resolvedSelectedNodeId}
          activeFilters={activeFilters}
          orbitRef={orbitRef}
          prefersReducedMotion={prefersReducedMotion}
          starCount={isExpanded ? 2200 : 1400}
          onNodeSelect={handleNodeSelect}
        />
        <EffectComposer multisampling={4}>
          <Bloom luminanceThreshold={0.25} luminanceSmoothing={0.9} intensity={0.95} />
        </EffectComposer>
        <OrbitControls
          ref={orbitRef}
          makeDefault
          enableDamping
          dampingFactor={0.05}
          autoRotate={false}
          maxDistance={2000}
          minDistance={20}
        />
      </Canvas>

      <div
        className="graph-stats"
        aria-label={`${graphNodes.length} nodes and ${graphEdges.length} edges`}
      >
        {graphNodes.length} nodes <span aria-hidden="true">·</span> {graphEdges.length} edges
      </div>
    </section>
  );
}
