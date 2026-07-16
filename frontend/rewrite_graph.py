import sys

content = """\"\"\"use client\"\"\"; // replaced later

import { useRef, useMemo, useState, useEffect } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, Line, Html, Stars } from '@react-three/drei';
import { EffectComposer, Bloom } from '@react-three/postprocessing';
import { Network, FileText, Share2, Tag, Search, X, Loader2, MessageSquare } from 'lucide-react';
import * as THREE from 'three';
import Markdown from 'react-markdown';
import type { GraphNode, GraphEdge } from '../types';
import { API_BASE } from '../types';

const TAG_PALETTE: Record<string, string> = {
  school: '#00ffff',
  coding: '#ff00ff',
  personal: '#00ff7f',
  'second-brain': '#8a2be2',
  projects: '#ff1493',
  career: '#ffd700',
  memory: '#ff4500',
};
const DEFAULT_PALETTE = '#00bfff';

function getNodeColor(tags: string[] | string | undefined) {
  const arr = Array.isArray(tags) ? tags : (tags ?? '').split(',').map(t => t.trim());
  for (const t of arr) {
    const key = t.replace(/^#/, '').toLowerCase();
    if (TAG_PALETTE[key]) return TAG_PALETTE[key];
  }
  return DEFAULT_PALETTE;
}

const REPULSION = 25000;
const ATTRACTION = 0.05;
const CENTER_PULL = 0.005;
const DAMPING = 0.75;
const MAX_VEL = 5;
const IDEAL_DIST = 100;

interface SimNode extends GraphNode {
  x: number; y: number; z: number;
  vx: number; vy: number; vz: number;
  radius: number;
  color: string;
  connections: number;
}

function GraphScene({ 
  nodes, 
  edges, 
  onNodeHover,
  onNodeSelect,
  selectedNode,
  activeFilters,
  orbitRef
}: { 
  nodes: GraphNode[], 
  edges: GraphEdge[], 
  onNodeHover: (n: SimNode | null) => void,
  onNodeSelect: (n: SimNode | null) => void,
  selectedNode: SimNode | null,
  activeFilters: Set<string>,
  orbitRef: any
}) {
  const simNodes = useRef<SimNode[]>([]);
  const simEdges = useRef<GraphEdge[]>([]);

  const [hoveredNode, setHoveredNode] = useState<number>(-1);
  const [layoutReady, setLayoutReady] = useState(false);
  const { camera } = useThree();

  useEffect(() => {
    if (!nodes || nodes.length === 0) return;
    simEdges.current = edges || [];
    
    const edgeCount = new Map<string, number>();
    simEdges.current.forEach(e => {
      edgeCount.set(e.source, (edgeCount.get(e.source) || 0) + 1);
      edgeCount.set(e.target, (edgeCount.get(e.target) || 0) + 1);
    });

    const spread = Math.sqrt(nodes.length) * 50;
    const ns = nodes.map(node => ({
      ...node,
      x: (Math.random() - 0.5) * spread,
      y: (Math.random() - 0.5) * spread,
      z: (Math.random() - 0.5) * spread,
      vx: 0, vy: 0, vz: 0,
      radius: 2 + Math.min((edgeCount.get(node.id) || 0) * 0.5, 4),
      color: getNodeColor(node.tags),
      connections: edgeCount.get(node.id) || 0,
    }));

    const N = ns.length;
    for (let iter = 0; iter < 100; iter++) {
      for (let i = 0; i < N; i++) {
        for (let j = i + 1; j < N; j++) {
          const dx = ns[j].x - ns[i].x;
          const dy = ns[j].y - ns[i].y;
          const dz = ns[j].z - ns[i].z;
          const dist = Math.sqrt(dx*dx + dy*dy + dz*dz) || 1;
          if (dist > 250) continue;
          const force = REPULSION / (dist * dist);
          const fx = (dx/dist)*force; const fy = (dy/dist)*force; const fz = (dz/dist)*force;
          ns[i].vx -= fx; ns[i].vy -= fy; ns[i].vz -= fz;
          ns[j].vx += fx; ns[j].vy += fy; ns[j].vz += fz;
        }
      }
      simEdges.current.forEach(edge => {
        const si = ns.findIndex(n => n.id === edge.source);
        const ti = ns.findIndex(n => n.id === edge.target);
        if (si === -1 || ti === -1) return;
        const dx = ns[ti].x - ns[si].x;
        const dy = ns[ti].y - ns[si].y;
        const dz = ns[ti].z - ns[si].z;
        const dist = Math.sqrt(dx*dx + dy*dy + dz*dz) || 1;
        const disp = dist - IDEAL_DIST;
        const force = ATTRACTION * disp;
        const fx = (dx/dist)*force; const fy = (dy/dist)*force; const fz = (dz/dist)*force;
        ns[si].vx += fx; ns[si].vy += fy; ns[si].vz += fz;
        ns[ti].vx -= fx; ns[ti].vy -= fy; ns[ti].vz -= fz;
      });
      for (let i = 0; i < N; i++) {
        ns[i].vx -= ns[i].x * CENTER_PULL;
        ns[i].vy -= ns[i].y * CENTER_PULL;
        ns[i].vz -= ns[i].z * CENTER_PULL;
        ns[i].vx *= DAMPING; ns[i].vy *= DAMPING; ns[i].vz *= DAMPING;
        const speed = Math.sqrt(ns[i].vx**2 + ns[i].vy**2 + ns[i].vz**2);
        if (speed > MAX_VEL) {
          ns[i].vx = (ns[i].vx/speed)*MAX_VEL;
          ns[i].vy = (ns[i].vy/speed)*MAX_VEL;
          ns[i].vz = (ns[i].vz/speed)*MAX_VEL;
        }
        ns[i].x += ns[i].vx; ns[i].y += ns[i].vy; ns[i].z += ns[i].vz;
      }
    }

    simNodes.current = ns;
    setLayoutReady(true);
  }, [nodes, edges]);

  const targetVec = useMemo(() => new THREE.Vector3(), []);
  
  useFrame(() => {
    if (selectedNode && orbitRef.current) {
      targetVec.set(selectedNode.x, selectedNode.y, selectedNode.z);
      orbitRef.current.target.lerp(targetVec, 0.05);
      orbitRef.current.update();
    }
  });

  if (!layoutReady) return null;

  return (
    <group>
      <Stars radius={500} depth={200} count={10000} factor={6} saturation={0} fade speed={1} />
      
      {simEdges.current.map((e, i) => {
        const source = simNodes.current.find(n => n.id === e.source);
        const target = simNodes.current.find(n => n.id === e.target);
        if (!source || !target) return null;
        
        const isHovered = hoveredNode === simNodes.current.indexOf(source) || hoveredNode === simNodes.current.indexOf(target);
        const sourceMatch = activeFilters.size === 0 || source.tags.some(t => activeFilters.has(t.replace(/^#/, '').toLowerCase()));
        const targetMatch = activeFilters.size === 0 || target.tags.some(t => activeFilters.has(t.replace(/^#/, '').toLowerCase()));
        
        const opacity = (sourceMatch && targetMatch) ? (isHovered ? 1.0 : 0.4) : 0.02;

        return (
          <Line
            key={`edge-${i}`}
            points={[[source.x, source.y, source.z], [target.x, target.y, target.z]]}
            color={isHovered ? "rgba(255,255,255,1.0)" : "rgba(0, 255, 255, 1.0)"}
            lineWidth={isHovered ? 3 : 1.5}
            transparent
            opacity={opacity}
          />
        );
      })}

      {simNodes.current.map((node, i) => {
        const isHovered = hoveredNode === i;
        const isSelected = selectedNode?.id === node.id;
        const isMatch = activeFilters.size === 0 || node.tags.some(t => activeFilters.has(t.replace(/^#/, '').toLowerCase()));
        const opacity = isMatch ? 0.9 : 0.1;
        const emissiveIntensity = isMatch ? (isHovered || isSelected ? 4.0 : 2.0) : 0.0;

        return (
          <mesh 
            key={`node-${node.id}`} 
            position={[node.x, node.y, node.z]}
            onPointerOver={(e) => { e.stopPropagation(); setHoveredNode(i); onNodeHover(node); }}
            onPointerOut={() => { setHoveredNode(-1); onNodeHover(null); }}
            onPointerDown={(e) => { e.stopPropagation(); onNodeSelect(node); }}
          >
            <sphereGeometry args={[isHovered || isSelected ? node.radius * 1.5 : node.radius, 32, 32]} />
            <meshStandardMaterial 
              color={isHovered || isSelected ? "#ffffff" : node.color}
              emissive={node.color}
              emissiveIntensity={emissiveIntensity}
              transparent
              opacity={opacity}
            />
            {(isHovered || isSelected) && (
              <Html distanceFactor={150} zIndexRange={[100, 0]}>
                <div style={{
                  background: 'rgba(5, 5, 10, 0.85)',
                  backdropFilter: 'blur(12px)',
                  padding: '6px 12px',
                  borderRadius: '12px',
                  color: 'white',
                  border: `1px solid ${node.color}`,
                  boxShadow: `0 0 20px ${node.color}40`,
                  fontSize: '12px',
                  fontWeight: 'bold',
                  pointerEvents: 'none',
                  whiteSpace: 'nowrap',
                  transform: 'translate3d(-50%, -150%, 0)'
                }}>
                  {node.label}
                </div>
              </Html>
            )}
          </mesh>
        );
      })}
    </group>
  );
}

interface Props {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
  onChatWithNode?: (title: string) => void;
}

export default function GraphCanvas({ nodes, edges, onChatWithNode }: Props) {
  const [activeNode, setActiveNode] = useState<SimNode | null>(null);
  const [selectedNode, setSelectedNode] = useState<SimNode | null>(null);
  
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilters, setActiveFilters] = useState<Set<string>>(new Set());
  
  const [noteContent, setNoteContent] = useState<string>('');
  const [isLoadingNote, setIsLoadingNote] = useState(false);
  
  const orbitRef = useRef<any>(null);

  useEffect(() => {
    if (selectedNode) {
      setIsLoadingNote(true);
      fetch(`${API_BASE}/api/note/${encodeURIComponent(selectedNode.label)}`)
        .then(res => {
          if (!res.ok) throw new Error("Failed to load");
          return res.json();
        })
        .then(data => {
          setNoteContent(data.content || 'No content found.');
        })
        .catch(() => {
          setNoteContent("Failed to load note content. Check backend connection.");
        })
        .finally(() => setIsLoadingNote(false));
    } else {
      setNoteContent('');
    }
  }, [selectedNode]);

  if (!nodes || nodes.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon"><Network size={32} /></div>
        <div className="empty-state-title">No Graph Data Yet</div>
        <div className="empty-state-desc">
          Run a vault scan from the sidebar to map your Obsidian vault's connections into an interactive 3D knowledge graph.
        </div>
      </div>
    );
  }

  const activeTags = activeNode ? (activeNode.tags || []) : (selectedNode ? (selectedNode.tags || []) : []);
  const displayNode = selectedNode || activeNode;

  const searchResults = searchQuery.trim() === '' ? [] : nodes.filter(n => n.label.toLowerCase().includes(searchQuery.toLowerCase())).slice(0, 5);

  const toggleFilter = (tag: string) => {
    setActiveFilters(prev => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  };

  return (
    <div className="graph-container" style={{
      width: '100%', height: '70vh', minHeight: 600, position: 'relative',
      background: 'transparent',
      borderRadius: '16px', overflow: 'hidden',
      border: '1px solid var(--color-glass-border)',
      boxShadow: '0 25px 60px rgba(0,0,0,0.6)'
    }}>
      
      {/* Search Bar Overlay */}
      <div style={{ position: 'absolute', top: 20, left: 20, zIndex: 20, width: 300 }}>
        <div style={{
          display: 'flex', alignItems: 'center', background: 'rgba(5, 5, 10, 0.75)',
          border: '1px solid var(--color-glass-border)', borderRadius: '12px',
          padding: '8px 16px', backdropFilter: 'blur(12px)', color: '#fff'
        }}>
          <Search size={16} color="#a0aab2" style={{ marginRight: 8 }} />
          <input 
            type="text" 
            placeholder="Search nodes..." 
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            style={{ background: 'transparent', border: 'none', color: '#fff', outline: 'none', width: '100%' }}
          />
        </div>
        {searchResults.length > 0 && (
          <div style={{
            marginTop: 8, background: 'rgba(5, 5, 10, 0.9)', border: '1px solid var(--color-glass-border)',
            borderRadius: '12px', overflow: 'hidden', backdropFilter: 'blur(12px)'
          }}>
            {searchResults.map(res => (
              <div 
                key={res.id} 
                onClick={() => {
                  setSearchQuery('');
                  setSelectedNode(res as any);
                }}
                style={{
                  padding: '10px 16px', color: '#fff', fontSize: 14, cursor: 'pointer',
                  borderBottom: '1px solid rgba(255,255,255,0.05)'
                }}
                onMouseOver={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.1)'}
                onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
              >
                {res.label}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Tag Filters Overlay */}
      <div style={{
        position: 'absolute', bottom: 20, left: 20, zIndex: 20,
        display: 'flex', flexWrap: 'wrap', gap: 8, maxWidth: '60%'
      }}>
        {Object.entries(TAG_PALETTE).map(([tag, color]) => (
          <button
            key={tag}
            onClick={() => toggleFilter(tag)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              background: activeFilters.has(tag) ? color : 'rgba(5, 5, 10, 0.75)',
              border: `1px solid ${activeFilters.has(tag) ? color : 'var(--color-glass-border)'}`,
              borderRadius: '20px', padding: '6px 12px',
              color: activeFilters.has(tag) ? '#000' : '#a0aab2',
              fontSize: 12, fontWeight: 600, cursor: 'pointer',
              backdropFilter: 'blur(12px)', transition: 'all 0.2s'
            }}
          >
            <Tag size={12} />
            #{tag}
          </button>
        ))}
      </div>

      {/* 3D Canvas */}
      <Canvas camera={{ position: [0, 0, 300], fov: 60, near: 1, far: 10000 }}>
        <ambientLight intensity={0.5} />
        <pointLight position={[100, 100, 100]} intensity={1} />
        <GraphScene 
          nodes={nodes} edges={edges || []} 
          onNodeHover={setActiveNode} 
          onNodeSelect={setSelectedNode}
          selectedNode={selectedNode}
          activeFilters={activeFilters}
          orbitRef={orbitRef}
        />
        <EffectComposer>
          <Bloom luminanceThreshold={0.0} luminanceSmoothing={0.9} height={300} intensity={1.5} />
        </EffectComposer>
        <OrbitControls ref={orbitRef} enableDamping dampingFactor={0.05} autoRotate={!selectedNode} autoRotateSpeed={0.5} maxDistance={2000} minDistance={20} />
      </Canvas>

      {/* Markdown Content Drawer */}
      <div style={{
        position: 'absolute', top: 0, right: selectedNode ? 0 : '-400px',
        width: '400px', height: '100%',
        background: 'rgba(10, 10, 15, 0.85)',
        borderLeft: '1px solid var(--color-glass-border-hover)',
        boxShadow: '-10px 0 40px rgba(0,0,0,0.5)',
        padding: '24px', backdropFilter: 'blur(24px)',
        zIndex: 30, transition: 'right 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        display: 'flex', flexDirection: 'column'
      }}>
        {selectedNode && (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
              <div>
                <h3 style={{ color: '#fff', fontSize: 20, margin: '0 0 8px 0', fontWeight: 600 }}>{selectedNode.label}</h3>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {selectedNode.tags.map(tag => (
                    <span key={tag} style={{ color: TAG_PALETTE[tag.toLowerCase().replace(/^#/, '')] || DEFAULT_PALETTE, fontSize: 12, fontWeight: 600 }}>#{tag.replace(/^#/, '')}</span>
                  ))}
                </div>
              </div>
              <button 
                onClick={() => setSelectedNode(null)}
                style={{ background: 'rgba(255,255,255,0.1)', border: 'none', borderRadius: '50%', padding: 6, color: '#fff', cursor: 'pointer' }}
              >
                <X size={16} />
              </button>
            </div>
            
            <button 
              onClick={() => onChatWithNode && onChatWithNode(selectedNode.label)}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                color: '#fff', border: 'none', borderRadius: '8px', padding: '10px',
                fontWeight: 600, cursor: 'pointer', marginBottom: 24
              }}
            >
              <MessageSquare size={16} />
              Chat with AI Copilot
            </button>

            <div style={{ flex: 1, overflowY: 'auto', color: '#e2e8f0', fontSize: 14, lineHeight: 1.6, paddingRight: 8 }}>
              {isLoadingNote ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
                  <Loader2 size={24} className="spin" style={{ color: '#8b5cf6' }} />
                </div>
              ) : (
                <div className="markdown-body" style={{ color: 'inherit' }}>
                  <Markdown>{noteContent}</Markdown>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Floating Hover Info (when drawer is closed) */}
      {!selectedNode && activeNode && (
        <div style={{
          position: 'absolute', top: 20, right: 20, width: '320px',
          background: 'rgba(5, 5, 10, 0.65)',
          border: '1px solid var(--color-glass-border-hover)',
          boxShadow: '0 12px 40px rgba(139, 92, 246, 0.2)',
          borderRadius: '16px', padding: '20px',
          backdropFilter: 'blur(24px)', zIndex: 10, pointerEvents: 'none',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
            <div style={{
              width: 12, height: 12, borderRadius: '50%',
              backgroundColor: activeNode.color,
              boxShadow: `0 0 16px ${activeNode.color}`
            }} />
            <span style={{ fontSize: 16, fontWeight: 700, color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {activeNode.label}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#a0aab2', marginBottom: 12 }}>
            <Share2 size={14} style={{ color: '#00f5d4' }} />
            <span>{activeNode.connections} Synaptic Connections</span>
          </div>
        </div>
      )}

      {/* Stats Badge */}
      <div style={{
        position: 'absolute', bottom: 20, right: 20,
        background: 'rgba(5, 5, 10, 0.65)',
        border: '1px solid var(--color-glass-border)',
        borderRadius: '8px', padding: '6px 12px',
        fontSize: 12, color: '#a0aab2',
        backdropFilter: 'blur(12px)', pointerEvents: 'none', zIndex: 10
      }}>
        {nodes.length} Nodes · {(edges || []).length} Edges
      </div>
    </div>
  );
}
"""

content = content.replace('\"\"\"use client\"\"\"; // replaced later', '"use client";')
with open('/Users/bryancruz/IdeaProjects/second-brain-tools/frontend/src/app/components/GraphCanvas.tsx', 'w') as f:
    f.write(content)
