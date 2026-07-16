import sys

content = """'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Brain, Link2, AlertTriangle, FileQuestion,
  RefreshCw, Sparkles, ArrowDown, MessageSquare, 
  PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, X, Loader2, Maximize, Minimize
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
  const [activeSection, setActiveSection] = useState<'hero' | 'graph' | 'chat'>('hero');
  const [chatInputPreset, setChatInputPreset] = useState<string>('');

  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isLeftOpen, setIsLeftOpen] = useState(true);
  const [isRightOpen, setIsRightOpen] = useState(true);
  
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [noteContent, setNoteContent] = useState<string>('');
  const [isLoadingNote, setIsLoadingNote] = useState(false);

  const heroRef  = useRef<HTMLDivElement>(null);
  const graphRef = useRef<HTMLDivElement>(null);
  const chatRef  = useRef<HTMLDivElement>(null);

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
    const observerOptions = {
      root: null,
      rootMargin: '-30% 0px -30% 0px',
      threshold: 0,
    };
    const observerCallback = (entries: IntersectionObserverEntry[]) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const id = entry.target.getAttribute('id');
          if (id === 'hero' || id === 'graph' || id === 'chat') {
            setActiveSection(id as any);
          }
        }
      });
    };
    const observer = new IntersectionObserver(observerCallback, observerOptions);
    if (heroRef.current) observer.observe(heroRef.current);
    if (graphRef.current) observer.observe(graphRef.current);
    if (chatRef.current) observer.observe(chatRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (selectedNode) {
      if (isFullscreen) setIsRightOpen(true);
      setIsLoadingNote(true);
      fetch(`${API_BASE}/api/note/${encodeURIComponent(selectedNode.label)}`)
        .then(res => res.json())
        .then(data => setNoteContent(data.content || 'No content found.'))
        .catch(() => setNoteContent("Failed to load note content."))
        .finally(() => setIsLoadingNote(false));
    } else {
      setNoteContent('');
    }
  }, [selectedNode, isFullscreen]);

  const triggerScan = async () => {
    try {
      setIsScanning(true);
      await fetch(`${API_BASE}/api/health/scan`, { method: 'POST' });
    } catch {
      setIsScanning(false);
    }
  };

  const handleChatWithNode = (title: string) => {
    setChatInputPreset(`Summarize my note on ${title}`);
    if (isFullscreen) {
      // If we are in fullscreen, the right panel handles chat natively!
      // The prop chatInputPreset passes down automatically.
    } else {
      chatRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  };

  const formatTime = (epoch: number) => {
    if (!epoch) return 'Never';
    return new Date(epoch * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const totalNotes = healthData?.total_notes ?? 0;
  const totalLinks = healthData?.total_links ?? 0;
  const brokenCount = healthData?.broken_links?.length ?? 0;
  const orphanCount = healthData?.orphaned_notes?.length ?? 0;

  // ─────────────────────────────────────────────────────────────────────────────
  // FULLSCREEN MODE
  // ─────────────────────────────────────────────────────────────────────────────
  if (isFullscreen) {
    return (
      <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', overflow: 'hidden', display: 'flex', background: '#020205', zIndex: 9999 }}>
        {/* 3D Graph (Fullscreen Background) */}
        <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', zIndex: 1 }}>
          <GraphCanvas nodes={healthData?.nodes} edges={healthData?.edges} onNodeSelect={setSelectedNode} />
        </div>

        {/* Top Controls: Exit Fullscreen */}
        <div style={{ position: 'absolute', top: 24, left: '50%', transform: 'translateX(-50%)', zIndex: 30, display: 'flex', gap: 16 }}>
           <button onClick={() => setIsFullscreen(false)} style={{
             display: 'flex', alignItems: 'center', gap: 8, padding: '10px 20px', borderRadius: 30,
             background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)',
             color: '#ff006e', cursor: 'pointer', fontWeight: 600, fontSize: 13, backdropFilter: 'blur(12px)'
           }}>
             <Minimize size={16} /> Exit Fullscreen
           </button>
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
          position: 'absolute', top: 80, bottom: 20, left: 20, width: 380,
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
          position: 'absolute', top: 80, bottom: 20, right: 20, width: 420,
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
                  onClick={() => handleChatWithNode(selectedNode.label)}
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
                <ChatPanel presetQuery={chatInputPreset} />
              </div>
            </div>
          ) : (
            /* Just Chat (Full Height) */
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '16px 0' }}>
              <h3 style={{ color: '#fff', fontSize: 16, margin: '0 16px 16px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Brain size={18} style={{ color: '#9d4edd' }} /> AI Copilot
              </h3>
              <div style={{ flex: 1, padding: '0 16px' }}>
                <ChatPanel presetQuery={chatInputPreset} />
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // NORMAL SCROLLABLE LANDING PAGE
  // ─────────────────────────────────────────────────────────────────────────────
  return (
    <div className="landing-page">
      <section className="section hero-section" id="hero" ref={heroRef}>
        <div className="hero-brand">
          <div className="hero-brand-icon">
            <Brain size={28} />
          </div>
          <div>
            <h1 className="hero-title">Second Brain</h1>
            <p className="hero-subtitle">Knowledge Engine · Rust + FastAPI + Next.js</p>
          </div>
        </div>

        <p className="hero-desc">
          Your personal Obsidian vault — parsed by a high-concurrency Rust engine,
          indexed with vector embeddings, and queryable with AI.
        </p>

        <div className="stats-grid">
          <StatsCard icon={Brain}           value={healthData ? totalNotes : '—'} label="Total Notes"    accent="purple" />
          <StatsCard icon={Link2}           value={healthData ? totalLinks : '—'} label="Total Links"    accent="cyan" />
          <StatsCard icon={AlertTriangle}   value={healthData ? brokenCount : '—'} label="Broken Links"   accent="rose" />
          <StatsCard icon={FileQuestion}    value={healthData ? orphanCount : '—'} label="Orphaned Notes"  accent="amber" />
        </div>

        <div className="scan-bar">
          <button
            className="scan-btn"
            onClick={triggerScan}
            disabled={isScanning}
          >
            <RefreshCw size={16} className={isScanning ? 'spin' : ''} />
            {isScanning ? 'Scanning vault...' : 'Run Vault Scan'}
          </button>
          <span className="scan-status">
            <span className={`scan-dot ${isScanning ? 'scanning' : ''}`} />
            {isScanning ? 'Analyzing...' : `Last scan: ${formatTime(lastScanTime)}`}
          </span>
        </div>

        {totalNotes > 0 && (
          <button
            className="scroll-hint"
            onClick={() => graphRef.current?.scrollIntoView({ behavior: 'smooth' })}
          >
            <ArrowDown size={16} />
            <span>Scroll to graph</span>
          </button>
        )}
      </section>

      <section className="section graph-section" id="graph" ref={graphRef}>
        <div className="section-heading">
          <h2 className="section-title">Knowledge Graph</h2>
          <p className="section-subtitle">
            Interactive visualization of {totalNotes} notes and {totalLinks} connections
          </p>
        </div>

        <div style={{ 
          position: 'relative', width: '100%', height: '85vh', minHeight: 800, 
          borderRadius: 16, overflow: 'hidden', border: '1px solid var(--color-glass-border)',
          boxShadow: '0 25px 60px rgba(0,0,0,0.6)'
        }}>
          {/* Main 3D Graph Component */}
          <GraphCanvas 
            nodes={healthData?.nodes} 
            edges={healthData?.edges} 
            onNodeSelect={setSelectedNode}
          />
          
          {/* Expand Fullscreen Button overlay */}
          <button onClick={() => setIsFullscreen(true)} style={{
            position: 'absolute', top: 20, right: 20, zIndex: 20,
            display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', borderRadius: 8,
            background: 'rgba(10,10,15,0.85)', border: '1px solid rgba(255,255,255,0.1)',
            color: '#fff', cursor: 'pointer', fontWeight: 600, fontSize: 13, backdropFilter: 'blur(12px)'
          }}>
            <Maximize size={16} /> Expand Graph
          </button>

          {/* Inline Markdown Drawer overlay */}
          <div style={{
            position: 'absolute', top: 0, right: selectedNode ? 0 : '-400px',
            width: '400px', height: '100%', background: 'rgba(10, 10, 15, 0.85)',
            borderLeft: '1px solid var(--color-glass-border-hover)', boxShadow: '-10px 0 40px rgba(0,0,0,0.5)',
            padding: '24px', backdropFilter: 'blur(24px)', zIndex: 30,
            transition: 'right 0.3s cubic-bezier(0.16, 1, 0.3, 1)', display: 'flex', flexDirection: 'column'
          }}>
            {selectedNode && (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
                  <div>
                    <h3 style={{ color: '#fff', fontSize: 20, margin: '0 0 8px 0', fontWeight: 600 }}>{selectedNode.label}</h3>
                  </div>
                  <button onClick={() => setSelectedNode(null)} style={{ background: 'rgba(255,255,255,0.1)', border: 'none', borderRadius: '50%', padding: 6, color: '#fff', cursor: 'pointer' }}>
                    <X size={16} />
                  </button>
                </div>
                
                <button 
                  onClick={() => handleChatWithNode(selectedNode.label)}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', color: '#fff', border: 'none',
                    borderRadius: '8px', padding: '10px', fontWeight: 600, cursor: 'pointer', marginBottom: 24
                  }}
                >
                  <MessageSquare size={16} /> Chat with AI Copilot
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
        </div>
      </section>

      <section className="section chat-section" id="chat" ref={chatRef}>
        <div className="section-heading">
          <h2 className="section-title">Local AI (Qwen)</h2>
          <p className="section-subtitle">
            Ask questions about your vault — powered by RAG + Qwen 2.5
          </p>
        </div>
        <ChatPanel presetQuery={chatInputPreset} />
      </section>

      {healthData && (brokenCount > 0 || orphanCount > 0) && (
        <section className="section details-section">
          <div className="section-heading">
            <h2 className="section-title">Vault Health Details</h2>
            <p className="section-subtitle">Issues found during the last scan</p>
          </div>
          <div className="details-grid">
            {brokenCount > 0 && (
              <div className="glass-card detail-card">
                <div className="detail-card-header">
                  <AlertTriangle size={16} style={{ color: 'var(--color-accent-rose)' }} />
                  <span>Broken Links ({brokenCount})</span>
                </div>
                <ul className="detail-list">
                  {healthData.broken_links.slice(0, 10).map((bl, i) => (
                    <li key={i}>
                      <span className="detail-source">{bl.source_title}</span>
                      <span className="detail-arrow">→</span>
                      <span className="detail-target">{bl.target}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {orphanCount > 0 && (
              <div className="glass-card detail-card">
                <div className="detail-card-header">
                  <Sparkles size={16} style={{ color: 'var(--color-accent-amber)' }} />
                  <span>Orphaned Notes ({orphanCount})</span>
                </div>
                <ul className="detail-list">
                  {healthData.orphaned_notes.slice(0, 10).map((on, i) => (
                    <li key={i}>{on.title}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      )}

      <footer className="landing-footer">
        <span>Second Brain Tools</span>
        <span className="footer-sep">·</span>
        <span>Rust + FastAPI + ChromaDB + Next.js</span>
        <span className="footer-sep">·</span>
        <span>Bryan Cruz</span>
      </footer>

      <nav className="floating-nav">
        <button className={`floating-nav-dot ${activeSection === 'hero' ? 'active' : ''}`} title="Hero" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })} />
        <button className={`floating-nav-dot ${activeSection === 'graph' ? 'active' : ''}`} title="Graph" onClick={() => graphRef.current?.scrollIntoView({ behavior: 'smooth' })} />
        <button className={`floating-nav-dot ${activeSection === 'chat' ? 'active' : ''}`} title="Chat" onClick={() => chatRef.current?.scrollIntoView({ behavior: 'smooth' })} />
      </nav>
    </div>
  );
}
"""

with open('src/app/page.tsx', 'w') as f:
    f.write(content)
