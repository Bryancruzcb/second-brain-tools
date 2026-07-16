'use client';

import { Brain, LayoutDashboard, MessageCircle, Network, RefreshCw } from 'lucide-react';
import type { ComponentType } from 'react';
import type { ViewMode } from '../types';

interface SidebarProps {
  activeView: ViewMode;
  onViewChange: (view: ViewMode) => void;
  onScan: () => void;
  isScanning: boolean;
  isConnected: boolean;
}

const navItems: Array<{ view: ViewMode; label: string; description: string; icon: ComponentType<{ size?: number }> }> = [
  { view: 'dashboard', label: 'Overview', description: 'Vault activity and health', icon: LayoutDashboard },
  { view: 'graph', label: 'Knowledge graph', description: 'Explore connections in 3D', icon: Network },
  { view: 'chat', label: 'Ask Qwen', description: 'Search and synthesize', icon: MessageCircle },
];

export default function Sidebar({ activeView, onViewChange, onScan, isScanning, isConnected }: SidebarProps) {
  return (
    <aside className="app-sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark" aria-hidden="true"><Brain size={20} /></div>
        <div className="brand-copy">
          <strong>Second Brain</strong>
          <span>Local knowledge engine</span>
        </div>
      </div>

      <nav className="sidebar-nav" aria-label="Workspace navigation">
        <span className="sidebar-section-label">Workspace</span>
        {navItems.map((item) => (
          <button
            type="button"
            key={item.view}
            className={`sidebar-item ${activeView === item.view ? 'active' : ''}`}
            onClick={() => onViewChange(item.view)}
            aria-current={activeView === item.view ? 'page' : undefined}
          >
            <span className="sidebar-item-icon"><item.icon size={18} /></span>
            <span className="sidebar-item-copy">
              <strong>{item.label}</strong>
              <small>{item.description}</small>
            </span>
          </button>
        ))}
      </nav>

      <div className="sidebar-spacer" />

      <div className="sidebar-system">
        <div className="system-row">
          <span className={`status-orb ${isConnected ? 'ready' : 'offline'}`} />
          <div>
            <strong>{isConnected ? 'Local services online' : 'Backend offline'}</strong>
            <span>{isConnected ? 'Private on this device' : 'Start FastAPI to reconnect'}</span>
          </div>
        </div>
        <button type="button" className="sidebar-scan" onClick={onScan} disabled={isScanning || !isConnected}>
          <RefreshCw size={15} className={isScanning ? 'spin' : ''} />
          {isScanning ? 'Refreshing vault…' : 'Refresh vault'}
        </button>
      </div>
    </aside>
  );
}
