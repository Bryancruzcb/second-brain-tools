'use client';

import dynamic from 'next/dynamic';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Brain,
  ChevronRight,
  FilePlus2,
  Maximize2,
  Menu,
  Minimize2,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Sparkles,
  X,
} from 'lucide-react';
import ChatPanel from './components/ChatPanel';
import CommandSearch from './components/CommandSearch';
import ContextChips from './components/ContextChips';
import FocusPanelResizeHandle from './components/FocusPanelResizeHandle';
import NotePanel from './components/NotePanel';
import Overview from './components/Overview';
import Sidebar from './components/Sidebar';
import type {
  GraphNode,
  HealthData,
  HealthResponse,
  RecentNote,
  SearchResult,
  ViewMode,
} from './types';
import { API_BASE } from './types';

const GraphCanvas = dynamic(() => import('./components/GraphCanvas'), {
  ssr: false,
  loading: () => <div className="graph-loading"><span /><span /><span /><p>Preparing your knowledge map…</p></div>,
});

type Notice = { message: string; tone: 'success' | 'error' | 'info' };

const FOCUS_LEFT_DEFAULT_WIDTH = 360;
const FOCUS_LEFT_MIN_WIDTH = 240;
const FOCUS_LEFT_MAX_WIDTH = 560;
const FOCUS_RIGHT_DEFAULT_WIDTH = 410;
const FOCUS_RIGHT_MIN_WIDTH = 300;
const FOCUS_RIGHT_MAX_WIDTH = 720;

export default function Home() {
  const [activeView, setActiveView] = useState<ViewMode>('dashboard');
  const [healthData, setHealthData] = useState<HealthData | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [isIndexing, setIsIndexing] = useState(false);
  const [lastScanTime, setLastScanTime] = useState(0);
  const [recentNotes, setRecentNotes] = useState<RecentNote[]>([]);
  const [dailyDigest, setDailyDigest] = useState<GraphNode[]>([]);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [noteContent, setNoteContent] = useState('');
  const [editContent, setEditContent] = useState('');
  const [isLoadingNote, setIsLoadingNote] = useState(false);
  const [isNoteReadOnly, setIsNoteReadOnly] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isCowriting, setIsCowriting] = useState(false);
  const noteRequestId = useRef(0);

  const [chatContextNodes, setChatContextNodes] = useState<GraphNode[]>([]);
  const [chatInputPreset, setChatInputPreset] = useState('');

  const [omniQuery, setOmniQuery] = useState('');
  const [omniResults, setOmniResults] = useState<SearchResult[]>([]);
  const [isOmniSearching, setIsOmniSearching] = useState(false);
  const [isOmniOpen, setIsOmniOpen] = useState(false);
  const omniTimer = useRef<number | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [showCreateNote, setShowCreateNote] = useState(false);
  const [newNoteTitle, setNewNoteTitle] = useState('');
  const [isCreatingNote, setIsCreatingNote] = useState(false);

  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isLeftOpen, setIsLeftOpen] = useState(true);
  const [isRightOpen, setIsRightOpen] = useState(true);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isGraphVisible, setIsGraphVisible] = useState(false);
  const [focusLeftWidth, setFocusLeftWidth] = useState(FOCUS_LEFT_DEFAULT_WIDTH);
  const [focusRightWidth, setFocusRightWidth] = useState(FOCUS_RIGHT_DEFAULT_WIDTH);
  const workspaceMainRef = useRef<HTMLElement | null>(null);
  const overviewSectionRef = useRef<HTMLElement | null>(null);
  const graphSectionRef = useRef<HTMLElement | null>(null);
  const chatSectionRef = useRef<HTMLElement | null>(null);

  const scrollToView = useCallback((view: ViewMode) => {
    const target = view === 'dashboard'
      ? overviewSectionRef.current
      : view === 'graph'
        ? graphSectionRef.current
        : chatSectionRef.current;
    setActiveView(view);
    setIsMobileMenuOpen(false);
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target?.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'start' });
  }, []);

  const showNotice = useCallback((message: string, tone: Notice['tone'] = 'info') => {
    setNotice({ message, tone });
  }, []);

  const fetchHealth = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/health`);
      if (!response.ok) throw new Error('Health request failed');
      const result: HealthResponse = await response.json();
      setHealthData(result.data);
      setIsScanning(result.is_scanning);
      setLastScanTime(result.last_scan_time);
      setIsConnected(true);
    } catch {
      setIsConnected(false);
      setIsScanning(false);
    }
  }, []);

  const fetchRecent = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/recent`);
      if (!response.ok) throw new Error('Recent notes request failed');
      const result = await response.json();
      setRecentNotes(result.notes ?? []);
    } catch {
      setRecentNotes([]);
    }
  }, []);

  const fetchDigest = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/digest`);
      if (!response.ok) throw new Error('Digest request failed');
      const result = await response.json();
      setDailyDigest(result.digest ?? []);
    } catch {
      setDailyDigest([]);
    }
  }, []);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => {
      void Promise.all([fetchHealth(), fetchRecent(), fetchDigest()]);
    }, 0);
    return () => window.clearTimeout(initialLoad);
  }, [fetchDigest, fetchHealth, fetchRecent]);

  useEffect(() => {
    if (!isScanning) return;
    const interval = window.setInterval(() => void fetchHealth(), 2500);
    return () => window.clearInterval(interval);
  }, [fetchHealth, isScanning]);

  useEffect(() => {
    if (!notice) return;
    const timeout = window.setTimeout(() => setNotice(null), 3800);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
      if (event.key === 'Escape') {
        setIsOmniOpen(false);
        setShowCreateNote(false);
      }
    };
    window.addEventListener('keydown', handleShortcut);
    return () => window.removeEventListener('keydown', handleShortcut);
  }, []);

  useEffect(() => {
    const root = workspaceMainRef.current;
    const sections: Array<{ view: ViewMode; element: HTMLElement | null }> = [
      { view: 'dashboard', element: overviewSectionRef.current },
      { view: 'graph', element: graphSectionRef.current },
      { view: 'chat', element: chatSectionRef.current },
    ];
    if (!root || sections.some(({ element }) => !element)) return;

    let frame = 0;
    const updateActiveSection = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const activeLine = root.getBoundingClientRect().top + Math.min(180, root.clientHeight * 0.25);
        let nextView: ViewMode = 'dashboard';
        sections.forEach(({ view, element }) => {
          if (element && element.getBoundingClientRect().top <= activeLine) nextView = view;
        });
        setActiveView(nextView);
      });
    };

    updateActiveSection();
    root.addEventListener('scroll', updateActiveSection, { passive: true });
    window.addEventListener('resize', updateActiveSection);
    return () => {
      window.cancelAnimationFrame(frame);
      root.removeEventListener('scroll', updateActiveSection);
      window.removeEventListener('resize', updateActiveSection);
    };
  }, []);

  useEffect(() => {
    const root = workspaceMainRef.current;
    const graphSection = graphSectionRef.current;
    if (!root || !graphSection) return;

    const observer = new IntersectionObserver(([entry]) => {
      setIsGraphVisible(entry.isIntersecting);
    }, { root, threshold: 0.01 });

    observer.observe(graphSection);
    return () => observer.disconnect();
  }, []);

  const triggerScan = async () => {
    setIsScanning(true);
    try {
      const response = await fetch(`${API_BASE}/api/health/scan`, { method: 'POST' });
      if (!response.ok) throw new Error('Scan failed');
      showNotice('Vault refresh started. The graph will update automatically.', 'info');
      window.setTimeout(() => void fetchHealth(), 750);
    } catch {
      setIsScanning(false);
      showNotice('Could not start the vault refresh. Check the FastAPI service.', 'error');
    }
  };

  const triggerIndex = async () => {
    setIsIndexing(true);
    try {
      const response = await fetch(`${API_BASE}/api/index`, { method: 'POST' });
      if (!response.ok) throw new Error('Index failed');
      showNotice('AI search re-indexing started in the background.', 'success');
    } catch {
      showNotice('Could not start re-indexing. Check the backend service.', 'error');
    } finally {
      window.setTimeout(() => setIsIndexing(false), 1200);
    }
  };

  const loadNode = useCallback(async (node: GraphNode, moveToGraph = true) => {
    const requestId = ++noteRequestId.current;
    setSelectedNode(node);
    setIsLoadingNote(true);
    setIsEditing(false);
    setNoteContent('');
    setEditContent('');
    setIsNoteReadOnly(false);
    if (moveToGraph) scrollToView('graph');

    try {
      const response = await fetch(`${API_BASE}/api/note/${node.id.split('/').map(encodeURIComponent).join('/')}`);
      if (!response.ok) throw new Error('Note request failed');
      const result = await response.json();
      if (requestId !== noteRequestId.current) return;
      const content = result.content || 'This note is empty.';
      setNoteContent(content);
      setEditContent(content);
      setIsNoteReadOnly(Boolean(result.read_only_fallback));
    } catch {
      if (requestId !== noteRequestId.current) return;
      setNoteContent('Unable to load this note. It may have moved since the last vault refresh.');
      setEditContent('');
      showNotice(`Could not load “${node.label}”.`, 'error');
    } finally {
      if (requestId === noteRequestId.current) setIsLoadingNote(false);
    }
  }, [scrollToView, showNotice]);

  const handleNodeSelect = useCallback((node: GraphNode | null, shiftKey = false) => {
    if (!node) {
      setSelectedNode(null);
      return;
    }
    if (shiftKey) {
      setChatContextNodes((current) => {
        const exists = current.some((item) => item.id === node.id);
        if (exists) return current.filter((item) => item.id !== node.id);
        if (current.length >= 8) {
          showNotice('Context is limited to eight notes for reliable local answers.', 'info');
          return current;
        }
        return [...current, node];
      });
      return;
    }
    void loadNode(node, false);
  }, [loadNode, showNotice]);

  const openRecentNote = (note: RecentNote) => {
    const matchingNode = healthData?.nodes.find((node) => node.id === note.id || node.label === note.title);
    void loadNode(matchingNode ?? { id: note.id, label: note.title, tags: [] });
  };

  const closeSelectedNote = () => {
    noteRequestId.current += 1;
    setSelectedNode(null);
    setIsEditing(false);
    setIsNoteReadOnly(false);
  };

  const saveNote = async () => {
    if (!selectedNode) return;
    setIsSaving(true);
    try {
      const notePath = selectedNode.id.split('/').map(encodeURIComponent).join('/');
      const response = await fetch(`${API_BASE}/api/note/${notePath}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editContent }),
      });
      if (!response.ok) throw new Error('Save failed');
      setNoteContent(editContent);
      setIsEditing(false);
      showNotice(`Saved “${selectedNode.label}”.`, 'success');
      void fetchRecent();
    } catch {
      showNotice('The note was not saved. Your draft is still in the editor.', 'error');
    } finally {
      setIsSaving(false);
    }
  };

  const cowriteNote = async () => {
    setIsCowriting(true);
    try {
      const response = await fetch(`${API_BASE}/api/cowrite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editContent }),
      });
      if (!response.ok) throw new Error('Co-write failed');
      const result = await response.json();
      if (!result.completion) throw new Error('Empty completion');
      setEditContent((current) => `${current}${current.endsWith('\n') ? '' : '\n\n'}${result.completion}`);
    } catch {
      showNotice('Qwen could not continue this note. Make sure Ollama is running.', 'error');
    } finally {
      setIsCowriting(false);
    }
  };

  const chatWithNode = () => {
    if (!selectedNode) return;
    setChatContextNodes((current) => current.some((node) => node.id === selectedNode.id) ? current : [...current, selectedNode]);
    setChatInputPreset(`Summarize ${selectedNode.label} and surface its most useful connections.`);
    scrollToView('chat');
    setIsFullscreen(false);
  };

  const handleSearchChange = (query: string) => {
    setOmniQuery(query);
    setIsOmniOpen(true);
    if (omniTimer.current) window.clearTimeout(omniTimer.current);
    if (!query.trim()) {
      setOmniResults([]);
      setIsOmniSearching(false);
      return;
    }
    setIsOmniSearching(true);
    omniTimer.current = window.setTimeout(async () => {
      try {
        const response = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(query)}`);
        if (!response.ok) throw new Error('Search failed');
        const result = await response.json();
        setOmniResults(result.results ?? []);
      } catch {
        setOmniResults([]);
      } finally {
        setIsOmniSearching(false);
      }
    }, 260);
  };

  const askFromSearch = (query: string) => {
    if (!query) return;
    setChatInputPreset(query);
    scrollToView('chat');
    setIsOmniOpen(false);
    setOmniQuery('');
  };

  const selectSearchResult = (result: SearchResult) => {
    const node = healthData?.nodes.find((item) => item.id === result.id || item.label === result.title);
    setIsOmniOpen(false);
    setOmniQuery('');
    void loadNode(node ?? { id: result.id, label: result.title, tags: [] });
  };

  const createNote = async () => {
    const title = newNoteTitle.trim();
    if (!title) return;
    setIsCreatingNote(true);
    try {
      const response = await fetch(`${API_BASE}/api/note/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || 'Create failed');
      }
      setShowCreateNote(false);
      setNewNoteTitle('');
      showNotice(`Created “${title}”. Refresh the vault when you are ready to map it.`, 'success');
      await fetchRecent();
      void loadNode({ id: `${title}.md`, label: title, tags: [] });
    } catch (error) {
      showNotice(error instanceof Error ? error.message : 'Could not create the note.', 'error');
    } finally {
      setIsCreatingNote(false);
    }
  };

  const removeContextNode = (id: string) => setChatContextNodes((current) => current.filter((node) => node.id !== id));

  const renderNotePanel = () => selectedNode ? (
    <NotePanel
      node={selectedNode}
      content={noteContent}
      editContent={editContent}
      isLoading={isLoadingNote}
      isReadOnly={isNoteReadOnly}
      isEditing={isEditing}
      isSaving={isSaving}
      isCowriting={isCowriting}
      onEditContentChange={setEditContent}
      onStartEditing={() => setIsEditing(true)}
      onCancelEditing={() => { setIsEditing(false); setEditContent(noteContent); }}
      onSave={() => void saveNote()}
      onCowrite={() => void cowriteNote()}
      onChat={chatWithNode}
      onClose={closeSelectedNote}
    />
  ) : null;

  return (
    <div className={`app-shell${isSidebarCollapsed ? ' sidebar-collapsed' : ''}${isMobileMenuOpen ? ' mobile-menu-open' : ''}`}>
      <Sidebar
        activeView={activeView}
        onViewChange={scrollToView}
        onScan={() => void triggerScan()}
        isScanning={isScanning}
        isConnected={isConnected}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapsed={() => setIsSidebarCollapsed((collapsed) => !collapsed)}
      />

      <div className="app-main">
        <header className="app-topbar">
          <button type="button" className="mobile-menu-button" onClick={() => setIsMobileMenuOpen((open) => !open)} aria-label="Toggle navigation">
            {isMobileMenuOpen ? <X size={19} /> : <Menu size={19} />}
          </button>
          <CommandSearch
            inputRef={searchInputRef}
            query={omniQuery}
            results={omniResults}
            isSearching={isOmniSearching}
            isOpen={isOmniOpen}
            onQueryChange={handleSearchChange}
            onFocus={() => setIsOmniOpen(true)}
            onBlur={() => window.setTimeout(() => setIsOmniOpen(false), 160)}
            onAsk={askFromSearch}
            onSelect={selectSearchResult}
          />
          <div className="topbar-meta">
            <span className="privacy-pill"><span className="status-orb ready" /> Local only</span>
            <button type="button" className="icon-button" onClick={() => setShowCreateNote(true)} aria-label="Create a new note" title="New note">
              <FilePlus2 size={17} />
            </button>
          </div>
        </header>

        <main className="workspace-main" ref={workspaceMainRef}>
          <section
            id="overview"
            ref={overviewSectionRef}
            className="journey-section journey-overview"
            aria-label="Workspace overview"
          >
            <Overview
              healthData={healthData}
              recentNotes={recentNotes}
              digest={dailyDigest}
              isScanning={isScanning}
              isIndexing={isIndexing}
              lastScanTime={lastScanTime}
              onScan={() => void triggerScan()}
              onIndex={() => void triggerIndex()}
              onCreate={() => setShowCreateNote(true)}
              onOpenGraph={() => scrollToView('graph')}
              onOpenChat={() => scrollToView('chat')}
              onOpenNode={(node) => void loadNode(node)}
              onOpenRecent={openRecentNote}
            />
          </section>

          <section
            id="knowledge-graph"
            ref={graphSectionRef}
            className="journey-section journey-graph"
            aria-labelledby="knowledge-graph-title"
          >
            <div className="graph-view view-enter">
              <header className="view-heading graph-heading">
                <div>
                  <span className="view-context">Spatial view</span>
                  <h1 id="knowledge-graph-title">Knowledge graph</h1>
                  <p>Explore relationships. Select a node to read it; Shift-click nodes to add them to Qwen context.</p>
                </div>
                <button type="button" className="button ghost" onClick={() => setIsFullscreen(true)}>
                  <Maximize2 size={16} /> Focus mode
                </button>
              </header>
              <ContextChips nodes={chatContextNodes} onRemove={removeContextNode} onClear={() => setChatContextNodes([])} compact />
              <div className={`graph-workspace ${selectedNode ? 'has-note' : ''}`}>
                <div className="graph-stage">
                  <GraphCanvas
                    nodes={healthData?.nodes}
                    edges={healthData?.edges}
                    selectedNodeId={selectedNode?.id}
                    onNodeSelect={handleNodeSelect}
                    isActive={isGraphVisible}
                  />
                </div>
                {renderNotePanel()}
              </div>
            </div>
          </section>

          <section
            id="ask-qwen"
            ref={chatSectionRef}
            className="journey-section journey-chat"
            aria-labelledby="ask-qwen-title"
          >
            <div className="chat-view view-enter">
              <header className="view-heading chat-heading">
                <div>
                  <span className="view-context">Local retrieval assistant</span>
                  <h1 id="ask-qwen-title">Ask Qwen</h1>
                  <p>Answers are grounded in your indexed notes and generated locally through Ollama.</p>
                </div>
                <span className="model-badge"><Brain size={15} /> Qwen 2.5 · local</span>
              </header>
              <ContextChips nodes={chatContextNodes} onRemove={removeContextNode} onClear={() => setChatContextNodes([])} />
              <div className="chat-workspace">
                <ChatPanel presetQuery={chatInputPreset} contextNodes={chatContextNodes} />
              </div>
            </div>
          </section>
        </main>
      </div>

      {isFullscreen && (
        <div className="fullscreen-workspace" role="dialog" aria-modal="true" aria-label="Knowledge graph focus mode">
          <div className="fullscreen-graph">
            <GraphCanvas
              nodes={healthData?.nodes}
              edges={healthData?.edges}
              selectedNodeId={selectedNode?.id}
              onNodeSelect={handleNodeSelect}
              isExpanded
            />
          </div>

          <div className="fullscreen-toolbar">
            <div className="fullscreen-brand"><Brain size={17} /><span>Knowledge graph</span></div>
            <button type="button" className="button danger subtle" onClick={() => setIsFullscreen(false)}>
              <Minimize2 size={15} /> Exit focus mode
            </button>
          </div>

          <button type="button" className="fullscreen-toggle left" onClick={() => setIsLeftOpen((open) => !open)} aria-label="Toggle graph overview">
            {isLeftOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          </button>
          <button type="button" className="fullscreen-toggle right" onClick={() => setIsRightOpen((open) => !open)} aria-label="Toggle note and chat panel">
            {isRightOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
          </button>

          <aside
            id="focus-graph-overview"
            className={`focus-panel focus-left ${isLeftOpen ? '' : 'closed'}`}
            style={{ width: focusLeftWidth }}
            aria-hidden={!isLeftOpen}
          >
            <FocusPanelResizeHandle
              controlsId="focus-graph-overview"
              defaultWidth={FOCUS_LEFT_DEFAULT_WIDTH}
              edge="right"
              label="Resize graph overview panel"
              maxWidth={FOCUS_LEFT_MAX_WIDTH}
              minWidth={FOCUS_LEFT_MIN_WIDTH}
              onResize={setFocusLeftWidth}
              width={focusLeftWidth}
            />
            <div className="focus-panel-heading"><span>Graph overview</span><strong>{healthData?.total_notes ?? 0} notes</strong></div>
            <div className="focus-metrics">
              <div><strong>{healthData?.total_links ?? 0}</strong><span>connections</span></div>
              <div><strong>{healthData?.avg_links_per_note?.toFixed(1) ?? '0.0'}</strong><span>per note</span></div>
            </div>
            <div className="focus-section">
              <h2>Rediscover</h2>
              {dailyDigest.map((node) => (
                <button type="button" key={node.id} onClick={() => void loadNode(node, false)}>
                  <span>{node.label}</span><ChevronRight size={14} />
                </button>
              ))}
            </div>
            <div className="focus-hint"><Sparkles size={15} /><span>Shift-click nodes to build a focused Qwen context.</span></div>
          </aside>

          <aside
            id="focus-ai-workspace"
            className={`focus-panel focus-right ${isRightOpen ? '' : 'closed'}`}
            style={{ width: focusRightWidth }}
            aria-hidden={!isRightOpen}
          >
            <FocusPanelResizeHandle
              controlsId="focus-ai-workspace"
              defaultWidth={FOCUS_RIGHT_DEFAULT_WIDTH}
              edge="left"
              label="Resize AI workspace panel"
              maxWidth={FOCUS_RIGHT_MAX_WIDTH}
              minWidth={FOCUS_RIGHT_MIN_WIDTH}
              onResize={setFocusRightWidth}
              width={focusRightWidth}
            />
            {selectedNode ? renderNotePanel() : (
              <div className="focus-chat">
                <div className="focus-panel-heading"><span>AI workspace</span><strong>Ask Qwen</strong></div>
                <ContextChips nodes={chatContextNodes} onRemove={removeContextNode} compact />
                <ChatPanel presetQuery={chatInputPreset} contextNodes={chatContextNodes} />
              </div>
            )}
          </aside>
        </div>
      )}

      {showCreateNote && (
        <dialog className="create-dialog" open aria-labelledby="create-note-title">
          <form method="dialog" onSubmit={(event) => { event.preventDefault(); void createNote(); }}>
            <div className="dialog-icon"><FilePlus2 size={19} /></div>
            <h2 id="create-note-title">Create a new note</h2>
            <p>It will be written directly into your local Obsidian vault.</p>
            <label htmlFor="new-note-title">Note title</label>
            <input
              id="new-note-title"
              autoFocus
              value={newNoteTitle}
              onChange={(event) => setNewNoteTitle(event.target.value)}
              placeholder="e.g. Retrieval ideas"
            />
            <div className="dialog-actions">
              <button type="button" className="button ghost" onClick={() => setShowCreateNote(false)}>Cancel</button>
              <button type="submit" className="button primary" disabled={!newNoteTitle.trim() || isCreatingNote}>
                {isCreatingNote ? 'Creating…' : 'Create note'}
              </button>
            </div>
          </form>
        </dialog>
      )}

      {notice && (
        <div className={`toast ${notice.tone}`} role="status">
          <span>{notice.message}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss notification"><X size={14} /></button>
        </div>
      )}

      <button type="button" className="mobile-backdrop" onClick={() => setIsMobileMenuOpen(false)} aria-label="Close navigation" />
    </div>
  );
}
