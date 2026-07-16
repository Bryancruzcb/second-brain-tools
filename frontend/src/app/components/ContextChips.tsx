'use client';

import { Layers3, X } from 'lucide-react';
import type { GraphNode } from '../types';

interface ContextChipsProps {
  nodes: GraphNode[];
  onRemove: (id: string) => void;
  onClear?: () => void;
  compact?: boolean;
}

export default function ContextChips({ nodes, onRemove, onClear, compact = false }: ContextChipsProps) {
  if (nodes.length === 0) return null;

  return (
    <div className={`context-strip ${compact ? 'compact' : ''}`}>
      <div className="context-strip-label">
        <Layers3 size={14} />
        <span>{nodes.length} note{nodes.length === 1 ? '' : 's'} in context</span>
      </div>
      <div className="context-chips">
        {nodes.map((node) => (
          <span className="context-chip" key={node.id}>
            <span>{node.label}</span>
            <button type="button" onClick={() => onRemove(node.id)} aria-label={`Remove ${node.label} from context`}>
              <X size={12} />
            </button>
          </span>
        ))}
      </div>
      {onClear && nodes.length > 1 && (
        <button type="button" className="text-button" onClick={onClear}>Clear</button>
      )}
    </div>
  );
}
