import sys

content = """'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Brain, Link2, AlertTriangle, FileQuestion,
  RefreshCw, Sparkles, MessageSquare, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, X, Loader2
} from 'lucide-react';
import dynamic from 'next/dynamic';
import Markdown from 'react-markdown';
import ChatPanel from './components/ChatPanel';
import type { HealthData, HealthResponse, GraphNode } from './types';
import { API_BASE } from './types';

const GraphCanvas = dynamic(() => import('./components/GraphCanvas'), {
  ssr: false,
});

function StatsCard({ icon: Icon, value, label, accent }: any) {
  return (
    <div className={`glass-card stat-card ${accent}`}>
      <div className="stat-card-header">
        <div className={`stat-card-icon ${accent}`}>
          <Icon size={18} />
        </div>
      </div>
      <div className="stat-card-value">{value}</div>
      <div className="stat-card-label">{label}</div>
    </div>
  );
}

export default function Home() {
  const [healthData, setHealthData] = useState<HealthData | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [lastScanTime, setLastScanTime] = useState(0);
  
  const [isLeftOpen, setIsLeftOpen] = useState(true);
  const [isRightOpen, setIsRightOpen] = useState(true);
  
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [noteContent, setNoteContent] = useState<string>('');
  const [isLoadingNote, setIsLoadingNote] = useState(false);
  const [chatPreset, setChatPreset] = useState('');

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/health`);
      if (!res.ok) return;
      const json: HealthResponse = await res.json();
      setHealthData(json.data);
      setIsScanning(json.is_scanning);
      setLastScanTime(json.last_scan_time);
    } catch {
      // Ignore
    }
  }, []);

  useEffect(() => { fetchHealth(); }, [fetchHealth]);

  useEffect(() => {
    if (!isScanning) return;
    const interval = setInterval(fetchHealth, 3000);
    return () => clearInterval(interval);
  }, [isScanning, fetchHealth]);

  useEffect(() => {
    if (selectedNode) {
      setIsRightOpen(true);
      setIsLoadingNote(true);
      fetch(`${API_BASE}/api/note/${encodeURIComponent(selectedNode.label)}`)
        .then(res => res.json())
        .then(data => setNoteContent(data.content || 'No content found.'))
        .catch(() => setNoteContent("Failed to load note content."))
        .finally(() => setIsLoadingNote(false));
    } else {
      setNoteContent('');
    }
  }, [selectedNode]);

  const triggerScan = async () => {
    try {
      setIsScanning(true);
      await fetch(`${API_BASE}/api/health/scan`, { method: 'POST' });
    } catch {
      setIsScanning(false);
    }
  };

  const totalNotes = healthData?.total_notes ?? 0;
  const totalLinks = healthData?.total_links ?? 0;
  const brokenCount = healthData?.broken_links?.length ?? 0;
  const orphanCount = healthData?.orphaned_notes?.length ?? 0;

  return (
    <div style={{ position: 'relative', width: '100vw', height: '100vh', overflow: 'hidden', display: 'flex', background: '#020205' }}>
      {/* 3D Graph (Fullscreen Background) */}
      <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', zIndex: 1 }}>
        <GraphCanvas 
          nodes={healthData?.nodes} 
          edges={healthData?.edges} 
          onNodeSelect={setSelectedNode}
        />
      </div>

      {/* Sidebar Toggles */}
      <button onClick={() => setIsLeftOpen(!isLeftOpen)} title="Toggle Dashboard" style={{
        position: 'absolute', top: 24, left: 24, zIndex: 20,
        background: 'rgba(10, 10, 15, 0.85)', border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: 8, color: '#a0aab2', padding: 8, cursor: 'pointer',
        backdropFilter: 'blur(12px)', transition: 'all 0.2s ease'
      }}>
        {isLeftOpen ? <PanelLeftClose size={20} /> : <PanelLeftOpen size={20} />}
      </button>

      <button onClick={() => setIsRightOpen(!isRightOpen)} title="Toggle AI Copilot" style={{
        position: 'absolute', top: 24, right: 24, zIndex: 20,
        background: 'rgba(10, 10, 15, 0.85)', border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: 8, color: '#a0aab2', padding: 8, cursor: 'pointer',
        backdropFilter: 'blur(12px)', transition: 'all 0.2s ease'
      }}>
        {isRightOpen ? <PanelRightClose size={20} /> : <PanelRightOpen size={20} />}
      </button>

      {/* LEFT SIDEBAR: Dashboard Control Center */}
      <div style={{
        position: 'absolute', top: 20, bottom: 20, left: 20, width: 380,
        background: 'rgba(10, 10, 15, 0.65)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)',
        border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: 16, zIndex: 10,
        display: 'flex', flexDirection: 'column',
        transition: 'transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.4s ease',
        boxShadow: '0 20px 40px rgba(0,0,0,0.5)', overflow: 'hidden',
        transform: isLeftOpen ? 'translateX(0)' : 'translateX(-420px)',
        opacity: isLeftOpen ? 1 : 0
      }}>
        <div style={{ padding: '24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px', height: '100%' }}>
          
          <div className="hero-brand" style={{ marginBottom: 0 }}>
            <div className="hero-brand-icon"><Brain size={24} /></div>
            <div>
              <h1 className="hero-title" style={{ fontSize: '20px', background: 'linear-gradient(135deg, #ffffff 30%, #a1a1aa 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Second Brain</h1>
              <p className="hero-subtitle" style={{ fontSize: '12px' }}>Knowledge Engine</p>
            </div>
          </div>

          <button className="scan-btn" onClick={triggerScan} disabled={isScanning} style={{
             display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', borderRadius: 6, cursor: 'pointer',
             fontSize: 12.5, fontWeight: 600, border: '1px solid rgba(255, 255, 255, 0.08)', background: 'rgba(255, 255, 255, 0.03)', color: '#fff'
          }}>
            <RefreshCw size={16} className={isScanning ? 'spin' : ''} />
            {isScanning ? 'Scanning vault...' : 'Run Vault Scan'}
          </button>
          
          <div className="stats-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <StatsCard icon={Brain} value={healthData ? totalNotes : '—'} label="Notes" accent="purple" />
            <StatsCard icon={Link2} value={healthData ? totalLinks : '—'} label="Links" accent="cyan" />
            <StatsCard icon={AlertTriangle} value={healthData ? brokenCount : '—'} label="Broken" accent="rose" />
            <StatsCard icon={FileQuestion} value={healthData ? orphanCount : '—'} label="Orphaned" accent="amber" />
          </div>

          {healthData && brokenCount > 0 && (
            <div className="glass-card detail-card" style={{ marginTop: 0, padding: 16, background: 'rgba(255, 255, 255, 0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8 }}>
              <div className="detail-card-header" style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, fontWeight: 600 }}>
                <AlertTriangle size={16} style={{ color: '#ff006e' }} />
                <span>Broken Links ({brokenCount})</span>
              </div>
              <ul className="detail-list" style={{ padding: 0, margin: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8 }}>
                {healthData.broken_links.slice(0, 10).map((bl, i) => (
                  <li key={i} style={{ display: 'flex', gap: 8, fontSize: 12, color: '#a0aab2' }}>
                    <span style={{ color: '#e2e8f0' }}>{bl.source_title}</span>
                    <span style={{ opacity: 0.5 }}>→</span>
                    <span style={{ color: '#ff006e' }}>{bl.target}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* RIGHT SIDEBAR: AI Chat & Note Content */}
      <div style={{
        position: 'absolute', top: 20, bottom: 20, right: 20, width: 420,
        background: 'rgba(10, 10, 15, 0.65)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)',
        border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: 16, zIndex: 10,
        display: 'flex', flexDirection: 'column',
        transition: 'transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.4s ease',
        boxShadow: '0 20px 40px rgba(0,0,0,0.5)', overflow: 'hidden',
        transform: isRightOpen ? 'translateX(0)' : 'translateX(440px)',
        opacity: isRightOpen ? 1 : 0
      }}>
        {selectedNode ? (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Top Half: Note Content */}
            <div style={{ flex: 1, padding: '20px', overflowY: 'auto', borderBottom: '1px solid rgba(255, 255, 255, 0.08)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
                <h3 style={{ color: '#fff', fontSize: 18, margin: 0, fontWeight: 600 }}>{selectedNode.label}</h3>
                <button 
                  onClick={() => setSelectedNode(null)} 
                  style={{ background: 'rgba(255,255,255,0.1)', border: 'none', borderRadius: '50%', padding: 4, color: '#fff', cursor: 'pointer' }}
                >
                  <X size={14} />
                </button>
              </div>
              <button 
                onClick={() => setChatPreset(`Summarize my note on ${selectedNode.label}`)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                  background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                  color: '#fff', border: 'none', borderRadius: '8px', padding: '8px',
                  fontWeight: 600, cursor: 'pointer', marginBottom: 16, width: '100%', fontSize: 13
                }}
              >
                <MessageSquare size={14} />
                Chat with AI Copilot
              </button>
              <div style={{ color: '#e2e8f0', fontSize: 13, lineHeight: 1.6 }}>
                {isLoadingNote ? (
                  <div style={{ display: 'flex', justifyContent: 'center', marginTop: 40 }}>
                    <Loader2 className="spin" size={24} style={{ color: '#8b5cf6' }} />
                  </div>
                ) : (
                  <div className="markdown-body"><Markdown>{noteContent}</Markdown></div>
                )}
              </div>
            </div>

            {/* Bottom Half: Chat Panel */}
            <div style={{ height: '350px' }}>
              <ChatPanel presetQuery={chatPreset} />
            </div>
          </div>
        ) : (
          /* Just Chat (Full Height) */
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '16px 0' }}>
            <h3 style={{ color: '#fff', fontSize: 16, margin: '0 16px 16px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Brain size={18} style={{ color: '#9d4edd' }} /> AI Copilot
            </h3>
            <div style={{ flex: 1, padding: '0 16px' }}>
              <ChatPanel presetQuery={chatPreset} />
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
"""

with open('src/app/page.tsx', 'w') as f:
    f.write(content)
