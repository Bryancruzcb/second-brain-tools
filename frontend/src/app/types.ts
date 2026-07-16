// === Second Brain Dashboard Types ===

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface BrokenLink {
  source: string;
  source_title: string;
  target: string;
}

export interface OrphanedNote {
  path: string;
  title: string;
}

export interface TaglessNote {
  path: string;
  title: string;
  suggestions: string[];
}

export interface GraphNode {
  id: string;
  label: string;
  tags: string[];
  cluster_id?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  is_ghost?: boolean;
}

export interface HealthData {
  total_notes: number;
  total_links: number;
  avg_links_per_note: number;
  broken_links: BrokenLink[];
  orphaned_notes: OrphanedNote[];
  tagless_notes: TaglessNote[];
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface HealthResponse {
  data: HealthData;
  is_scanning: boolean;
  last_scan_time: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  timestamp: Date;
  isLoading?: boolean;
}

export interface Source {
  title: string;
  source: string;
  snippet: string;
  distance: number;
}

export interface QueryResponse {
  answer: string;
  sources: Source[];
  api_configured: boolean;
}

export interface NoteContentResponse {
  title: string;
  content: string;
}

export interface RecentNote {
  title: string;
  id: string;
  mtime: number;
  preview: string;
}

export interface SearchResult {
  title: string;
  id: string;
  snippet: string;
}

export type ViewMode = 'dashboard' | 'graph' | 'chat';
