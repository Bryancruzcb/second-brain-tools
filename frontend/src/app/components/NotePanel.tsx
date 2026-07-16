'use client';

import { ExternalLink, Loader2, MessageSquare, Pencil, Save, Sparkles, X } from 'lucide-react';
import Markdown from 'react-markdown';
import type { GraphNode } from '../types';

interface NotePanelProps {
  node: GraphNode;
  content: string;
  editContent: string;
  isLoading: boolean;
  isReadOnly: boolean;
  isEditing: boolean;
  isSaving: boolean;
  isCowriting: boolean;
  onEditContentChange: (content: string) => void;
  onStartEditing: () => void;
  onCancelEditing: () => void;
  onSave: () => void;
  onCowrite: () => void;
  onChat: () => void;
  onClose: () => void;
}

export default function NotePanel({
  node,
  content,
  editContent,
  isLoading,
  isReadOnly,
  isEditing,
  isSaving,
  isCowriting,
  onEditContentChange,
  onStartEditing,
  onCancelEditing,
  onSave,
  onCowrite,
  onChat,
  onClose,
}: NotePanelProps) {
  const obsidianUrl = `obsidian://open?vault=Obsidian%20Vault&file=${encodeURIComponent(node.id.replace(/\.md$/i, ''))}`;

  return (
    <aside className="note-panel" aria-label={`Note: ${node.label}`}>
      <header className="note-panel-header">
        <div className="note-heading-copy">
          <span className="note-heading-label">Selected note</span>
          <h2>{node.label}</h2>
          {node.tags.length > 0 && (
            <div className="note-tags" aria-label="Note tags">
              {node.tags.slice(0, 4).map((tag) => <span key={tag}>#{tag.replace(/^#/, '')}</span>)}
            </div>
          )}
        </div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close note panel">
          <X size={17} />
        </button>
      </header>

      <div className="note-actions">
        <button type="button" className="button secondary compact" onClick={onChat}>
          <MessageSquare size={15} /> Ask about note
        </button>
        {isReadOnly && (
          <span className="note-readonly-status" title="This OneDrive file is not downloaded. Open it in Obsidian to edit.">
            Indexed copy
          </span>
        )}
        {isEditing ? (
          <>
            <button type="button" className="button ghost compact" onClick={onCancelEditing}>Cancel</button>
            <button type="button" className="button primary compact" onClick={onSave} disabled={isSaving}>
              {isSaving ? <Loader2 className="spin" size={15} /> : <Save size={15} />}
              {isSaving ? 'Saving' : 'Save'}
            </button>
          </>
        ) : !isReadOnly ? (
          <button type="button" className="button ghost compact" onClick={onStartEditing}>
            <Pencil size={15} /> Edit
          </button>
        ) : null}
        <a className="icon-button" href={obsidianUrl} aria-label="Open note in Obsidian" title="Open in Obsidian">
          <ExternalLink size={16} />
        </a>
      </div>

      <div className="note-panel-body">
        {isLoading ? (
          <div className="panel-skeleton" aria-label="Loading note">
            <span /><span /><span /><span />
          </div>
        ) : isEditing ? (
          <>
            <textarea
              className="note-editor"
              value={editContent}
              onChange={(event) => onEditContentChange(event.target.value)}
              aria-label={`Edit ${node.label}`}
            />
            <button type="button" className="cowrite-button" onClick={onCowrite} disabled={isCowriting}>
              {isCowriting ? <Loader2 className="spin" size={15} /> : <Sparkles size={15} />}
              {isCowriting ? 'Qwen is writing…' : 'Continue with Qwen'}
            </button>
          </>
        ) : (
          <div className="markdown-body"><Markdown>{content}</Markdown></div>
        )}
      </div>
    </aside>
  );
}
