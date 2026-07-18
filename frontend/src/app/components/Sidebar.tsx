'use client';

import {
  Brain,
  LayoutDashboard,
  MessageCircle,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
} from 'lucide-react';
import type { ComponentType } from 'react';
import type { ViewMode } from '../types';

interface SidebarProps {
  activeView: ViewMode;
  onViewChange: (view: ViewMode) => void;
  onScan: () => void;
  isScanning: boolean;
  isConnected: boolean;
  isCollapsed: boolean;
  onToggleCollapsed: () => void;
}

const navItems: Array<{ view: ViewMode; label: string; description: string; icon: ComponentType<{ size?: number }> }> = [
  { view: 'dashboard', label: 'Overview', description: 'Vault activity and health', icon: LayoutDashboard },
  { view: 'graph', label: 'Knowledge graph', description: 'Explore connections in 3D', icon: Network },
  { view: 'chat', label: 'Ask Qwen', description: 'Search and synthesize', icon: MessageCircle },
];

export default function Sidebar({
  activeView,
  onViewChange,
  onScan,
  isScanning,
  isConnected,
  isCollapsed,
  onToggleCollapsed,
}: SidebarProps) {
  const serviceStatus = isConnected ? 'Local services online' : 'Backend offline';

  return (
    <aside id="workspace-sidebar" className={`app-sidebar${isCollapsed ? ' is-collapsed' : ''}`}>
      <button
        type="button"
        className="sidebar-collapse"
        onClick={onToggleCollapsed}
        aria-controls="workspace-sidebar"
        aria-expanded={!isCollapsed}
        aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {isCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
      </button>

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
            aria-label={isCollapsed ? item.label : undefined}
            data-label={item.label}
            title={isCollapsed ? item.label : undefined}
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
        <div className="system-row" role="status" aria-label={serviceStatus} title={isCollapsed ? serviceStatus : undefined}>
          <span className={`status-orb ${isConnected ? 'ready' : 'offline'}`} />
          <div>
            <strong>{isConnected ? 'Local services online' : 'Backend offline'}</strong>
            <span>{isConnected ? 'Private on this device' : 'Start FastAPI to reconnect'}</span>
          </div>
        </div>
        <button
          type="button"
          className="sidebar-scan"
          onClick={onScan}
          disabled={isScanning || !isConnected}
          aria-label={isScanning ? 'Refreshing vault' : 'Refresh vault'}
          title={isCollapsed ? (isScanning ? 'Refreshing vault' : 'Refresh vault') : undefined}
        >
          <RefreshCw size={15} className={isScanning ? 'spin' : ''} />
          <span className="sidebar-scan-label">{isScanning ? 'Refreshing vault…' : 'Refresh vault'}</span>
        </button>
      </div>
    </aside>
  );
}
