'use client';

import {
  ArrowRight,
  Brain,
  CircleAlert,
  FilePlus2,
  FileQuestion,
  Link2,
  Loader2,
  Network,
  RefreshCw,
  SearchCheck,
  Sparkles,
  Tags,
} from 'lucide-react';
import type { GraphNode, HealthData, RecentNote } from '../types';

interface OverviewProps {
  healthData: HealthData | null;
  recentNotes: RecentNote[];
  digest: GraphNode[];
  isScanning: boolean;
  isIndexing: boolean;
  lastScanTime: number;
  onScan: () => void;
  onIndex: () => void;
  onCreate: () => void;
  onOpenGraph: () => void;
  onOpenChat: () => void;
  onOpenNode: (node: GraphNode) => void;
  onOpenRecent: (note: RecentNote) => void;
}

function formatScanTime(epoch: number) {
  if (!epoch) return 'Not scanned yet';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(epoch * 1000));
}

function formatEditedTime(epoch: number) {
  const difference = Date.now() - epoch * 1000;
  const minutes = Math.max(1, Math.floor(difference / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function Overview({
  healthData,
  recentNotes,
  digest,
  isScanning,
  isIndexing,
  lastScanTime,
  onScan,
  onIndex,
  onCreate,
  onOpenGraph,
  onOpenChat,
  onOpenNode,
  onOpenRecent,
}: OverviewProps) {
  const notes = healthData?.total_notes ?? 0;
  const links = healthData?.total_links ?? 0;
  const broken = healthData?.broken_links.length ?? 0;
  const orphaned = healthData?.orphaned_notes.length ?? 0;
  const tagless = healthData?.tagless_notes.length ?? 0;
  const averageLinks = healthData?.avg_links_per_note ?? 0;

  return (
    <div className="overview-view view-enter">
      <header className="view-heading overview-heading">
        <div>
          <span className="view-context">Workspace overview</span>
          <h1>Your knowledge, within reach.</h1>
          <p>Review what changed, repair weak connections, or move directly into the graph and ask Qwen.</p>
        </div>
        <div className="heading-actions">
          <button type="button" className="button ghost" onClick={onCreate}>
            <FilePlus2 size={16} /> New note
          </button>
          <button type="button" className="button primary" onClick={onScan} disabled={isScanning}>
            {isScanning ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            {isScanning ? 'Scanning vault' : 'Refresh vault'}
          </button>
        </div>
      </header>

      <section className="vault-pulse" aria-label="Vault summary">
        <div className="pulse-item pulse-lead">
          <span className={`status-orb ${isScanning ? 'working' : 'ready'}`} />
          <div>
            <strong>{isScanning ? 'Reading your vault' : 'Vault is ready'}</strong>
            <span>{isScanning ? 'Graph and health data are updating' : `Last refreshed ${formatScanTime(lastScanTime)}`}</span>
          </div>
        </div>
        <div className="pulse-stat"><Brain size={16} /><strong>{healthData ? notes.toLocaleString() : '—'}</strong><span>notes</span></div>
        <div className="pulse-stat"><Link2 size={16} /><strong>{healthData ? links.toLocaleString() : '—'}</strong><span>links</span></div>
        <div className="pulse-stat"><Network size={16} /><strong>{healthData ? averageLinks.toFixed(1) : '—'}</strong><span>links / note</span></div>
        <div className={`pulse-stat ${broken + orphaned > 0 ? 'needs-attention' : ''}`}>
          <CircleAlert size={16} /><strong>{healthData ? broken + orphaned : '—'}</strong><span>issues</span>
        </div>
      </section>

      <div className="overview-grid">
        <section className="workspace-panel recent-panel">
          <div className="panel-heading">
            <div>
              <h2>Recently edited</h2>
              <p>Continue where your thinking last moved.</p>
            </div>
            <button type="button" className="text-button" onClick={onOpenGraph}>Open graph <ArrowRight size={14} /></button>
          </div>
          <div className="recent-list">
            {recentNotes.length > 0 ? recentNotes.slice(0, 6).map((note) => (
              <button type="button" className="recent-row" key={note.id} onClick={() => onOpenRecent(note)}>
                <span className="note-glyph">{note.title.slice(0, 1).toUpperCase()}</span>
                <span className="recent-copy">
                  <strong>{note.title}</strong>
                  <span>{note.preview || 'No preview available'}</span>
                </span>
                <time dateTime={new Date(note.mtime * 1000).toISOString()}>{formatEditedTime(note.mtime)}</time>
              </button>
            )) : (
              <div className="empty-inline">
                <FileQuestion size={20} />
                <div><strong>No recent notes yet</strong><span>Refresh the vault to load recent activity.</span></div>
              </div>
            )}
          </div>
        </section>

        <section className="workspace-panel rediscover-panel">
          <div className="panel-heading">
            <div>
              <h2>Rediscover</h2>
              <p>A small set of notes worth revisiting.</p>
            </div>
            <Sparkles size={18} />
          </div>
          <div className="digest-list">
            {digest.length > 0 ? digest.map((node, index) => (
              <button type="button" key={node.id} className="digest-row" onClick={() => onOpenNode(node)}>
                <span className="digest-index">0{index + 1}</span>
                <span><strong>{node.label}</strong><small>{node.tags.slice(0, 2).map((tag) => `#${tag.replace(/^#/, '')}`).join(' · ') || 'Untagged note'}</small></span>
                <ArrowRight size={15} />
              </button>
            )) : (
              <div className="empty-inline">
                <Brain size={20} />
                <div><strong>Your review queue is empty</strong><span>Scan the vault to surface notes.</span></div>
              </div>
            )}
          </div>
          <button type="button" className="button secondary full-width" onClick={onOpenChat}>
            <Sparkles size={16} /> Ask Qwen about your vault
          </button>
        </section>

        <section className="workspace-panel health-panel">
          <div className="panel-heading">
            <div>
              <h2>Vault health</h2>
              <p>Structural signals from the most recent parse.</p>
            </div>
            <span className={`health-score ${broken + orphaned + tagless === 0 ? 'clear' : ''}`}>
              {broken + orphaned + tagless === 0 ? 'All clear' : `${broken + orphaned + tagless} signals`}
            </span>
          </div>
          <div className="health-breakdown">
            <div><span className="health-icon danger"><CircleAlert size={16} /></span><strong>{broken}</strong><span>Broken links</span><small>{broken ? 'Targets that no longer resolve' : 'Every link resolves'}</small></div>
            <div><span className="health-icon warning"><FileQuestion size={16} /></span><strong>{orphaned}</strong><span>Orphaned notes</span><small>{orphaned ? 'Notes with no incoming links' : 'Every note is connected'}</small></div>
            <div><span className="health-icon neutral"><Tags size={16} /></span><strong>{tagless}</strong><span>Without tags</span><small>{tagless ? 'Candidates for categorization' : 'Every note is categorized'}</small></div>
          </div>
          {(broken > 0 || orphaned > 0) && (
            <div className="health-detail-lists">
              {broken > 0 && (
                <div>
                  <h3>Broken links</h3>
                  {healthData?.broken_links.slice(0, 4).map((item) => (
                    <span key={`${item.source}-${item.target}`}><strong>{item.source_title}</strong><small>→ {item.target}</small></span>
                  ))}
                </div>
              )}
              {orphaned > 0 && (
                <div>
                  <h3>Orphaned notes</h3>
                  {healthData?.orphaned_notes.slice(0, 4).map((item) => (
                    <span key={item.path}><strong>{item.title}</strong><small>{item.path}</small></span>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>

        <section className="workspace-panel index-panel">
          <div className="index-mark"><SearchCheck size={22} /></div>
          <div>
            <h2>AI search index</h2>
            <p>Refresh embeddings after adding or substantially editing notes so Qwen retrieves the newest context.</p>
          </div>
          <button type="button" className="button ghost" onClick={onIndex} disabled={isIndexing}>
            {isIndexing ? <Loader2 className="spin" size={16} /> : <SearchCheck size={16} />}
            {isIndexing ? 'Indexing' : 'Re-index notes'}
          </button>
        </section>
      </div>
    </div>
  );
}
