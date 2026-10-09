"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  fetchGraph,
  fetchHealth,
  fetchReady,
  folderCluster,
  isChatNote,
  mapHealthIssues,
  type AskHistoryEntry,
  type BackendGraphEdge,
  type BackendGraphNode,
  type BackendHealthData,
} from "@/lib/api";
import { folderColor } from "@/lib/folders";
import {
  normalizeView,
  VIEW_STORAGE_KEY,
  VIEWS,
  type ViewId,
} from "@/lib/workspace";

type ReadyState = {
  /** false when /api/ready could not be reached at all */
  reachable: boolean;
  ready: boolean;
  indexPopulated: boolean | null;
  components: Record<string, boolean>;
} | null;

export type FolderSummary = {
  name: string;
  color: string;
  /** notes in this folder (chats excluded) */
  count: number;
};

/** Vault-wide data the shell needs: counts, folders, open Health items. */
type VaultState = {
  status: "loading" | "ok" | "error";
  nodes: BackendGraphNode[];
  edges: BackendGraphEdge[];
  health: BackendHealthData | null;
};

type WorkspaceValue = {
  view: ViewId;
  setView: (view: ViewId) => void;
  selectedNoteId: string | null;
  selectNote: (
    id: string | null,
    opts?: { view?: ViewId; repairIssueId?: string | null; askContext?: boolean },
  ) => void;
  mapFocusId: string | null;
  repairIssueId: string | null;
  askContextId: string | null;
  setAskContextId: (id: string | null) => void;
  commandOpen: boolean;
  setCommandOpen: (open: boolean) => void;
  ready: ReadyState;

  /* Vault data shared by the sidebar (and later the views). */
  vaultStatus: VaultState["status"];
  folders: FolderSummary[];
  noteCount: number | null;
  chatCount: number | null;
  openIssueCount: number | null;
  refreshVault: () => void;

  /** Folder selected in the sidebar; filters the Map. null = all folders. */
  folderFilter: string | null;
  setFolderFilter: (folder: string | null) => void;

  /** Ask history: bumped after each Ask so every list reloads. */
  askHistoryVersion: number;
  bumpAskHistory: () => void;
  /** A saved question picked in the sidebar; AskView shows its answer. */
  askPick: { entry: AskHistoryEntry; nonce: number } | null;
  pickAskEntry: (entry: AskHistoryEntry) => void;
};

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

const VAULT_REFRESH_MS = 60_000;

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [view, setViewState] = useState<ViewId>("notes");
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [mapFocusId, setMapFocusId] = useState<string | null>(null);
  const [repairIssueId, setRepairIssueId] = useState<string | null>(null);
  const [askContextId, setAskContextId] = useState<string | null>(null);
  const [commandOpen, setCommandOpen] = useState(false);
  const [ready, setReady] = useState<ReadyState>(null);
  const [vault, setVault] = useState<VaultState>({
    status: "loading",
    nodes: [],
    edges: [],
    health: null,
  });
  const [vaultReloads, setVaultReloads] = useState(0);
  const [folderFilter, setFolderFilter] = useState<string | null>(null);
  const [askHistoryVersion, setAskHistoryVersion] = useState(0);
  const [askPick, setAskPick] = useState<WorkspaceValue["askPick"]>(null);

  const setView = useCallback((next: ViewId) => {
    setViewState(next);
    try {
      window.localStorage.setItem(VIEW_STORAGE_KEY, next);
    } catch {
      /* storage unavailable (private mode): the view just won't persist */
    }
  }, []);

  // Restore the last view. A #hash wins over storage; the legacy "repair"
  // key (stored or #repair) maps to "health".
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      let stored: string | null = null;
      try {
        stored = window.localStorage.getItem(VIEW_STORAGE_KEY);
      } catch {
        /* ignore */
      }
      const fromHash = normalizeView(window.location.hash);
      const restored = fromHash ?? normalizeView(stored);
      if (restored) setView(restored);
      if (window.location.hash.replace(/^#/, "").toLowerCase() === "repair") {
        window.history.replaceState(null, "", "#health");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [setView]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetchReady();
        if (!cancelled)
          setReady({
            reachable: true,
            ready: res.ready,
            indexPopulated: res.index_populated ?? null,
            components: res.components || {},
          });
      } catch {
        if (!cancelled)
          setReady({
            reachable: false,
            ready: false,
            indexPopulated: null,
            components: {},
          });
      }
    };
    void poll();
    const id = window.setInterval(poll, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Graph + health feed the sidebar's folders, counts and Health badge.
  const backendUp = ready?.reachable ?? null;
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const [graph, health] = await Promise.allSettled([fetchGraph(), fetchHealth()]);
      if (cancelled) return;
      if (graph.status === "rejected" && health.status === "rejected") {
        setVault((v) => ({ ...v, status: "error" }));
        return;
      }
      setVault({
        status: "ok",
        nodes: graph.status === "fulfilled" ? graph.value.nodes || [] : [],
        edges: graph.status === "fulfilled" ? graph.value.edges || [] : [],
        health: health.status === "fulfilled" ? health.value.data || null : null,
      });
    };
    void load();
    const id = window.setInterval(load, VAULT_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [vaultReloads, backendUp]);

  const refreshVault = useCallback(() => setVaultReloads((n) => n + 1), []);

  const { folders, noteCount, chatCount, openIssueCount } = useMemo(() => {
    if (vault.status !== "ok") {
      return { folders: [], noteCount: null, chatCount: null, openIssueCount: null };
    }
    const byFolder = new Map<string, number>();
    let chats = 0;
    for (const n of vault.nodes) {
      if (isChatNote(n.id)) {
        chats += 1;
        continue;
      }
      const name = folderCluster(n.id);
      byFolder.set(name, (byFolder.get(name) || 0) + 1);
    }
    const list: FolderSummary[] = [...byFolder.entries()]
      .map(([name, count]) => ({ name, count, color: folderColor(name) }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
    return {
      folders: list,
      noteCount: vault.nodes.length - chats,
      chatCount: chats,
      openIssueCount: vault.health ? mapHealthIssues(vault.health).length : null,
    };
  }, [vault]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandOpen(true);
        return;
      }
      if (meta && ["1", "2", "3", "4"].includes(e.key)) {
        e.preventDefault();
        setView(VIEWS[Number(e.key) - 1]);
        return;
      }
      if (e.key === "Escape") setCommandOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setView]);

  const selectNote = useCallback(
    (
      id: string | null,
      opts?: { view?: ViewId; repairIssueId?: string | null; askContext?: boolean },
    ) => {
      setSelectedNoteId(id);
      if (id) setMapFocusId(id);
      setRepairIssueId(opts?.repairIssueId ?? null);
      if (opts?.askContext && id) setAskContextId(id);
      if (opts?.view) setView(opts.view);
    },
    [setView],
  );

  const bumpAskHistory = useCallback(() => setAskHistoryVersion((v) => v + 1), []);
  const pickAskEntry = useCallback((entry: AskHistoryEntry) => {
    setAskPick({ entry, nonce: Date.now() });
  }, []);

  const value = useMemo<WorkspaceValue>(
    () => ({
      view,
      setView,
      selectedNoteId,
      selectNote,
      mapFocusId,
      repairIssueId,
      askContextId,
      setAskContextId,
      commandOpen,
      setCommandOpen,
      ready,
      vaultStatus: vault.status,
      folders,
      noteCount,
      chatCount,
      openIssueCount,
      refreshVault,
      folderFilter,
      setFolderFilter,
      askHistoryVersion,
      bumpAskHistory,
      askPick,
      pickAskEntry,
    }),
    [
      view,
      setView,
      selectedNoteId,
      selectNote,
      mapFocusId,
      repairIssueId,
      askContextId,
      commandOpen,
      ready,
      vault.status,
      folders,
      noteCount,
      chatCount,
      openIssueCount,
      refreshVault,
      folderFilter,
      askHistoryVersion,
      bumpAskHistory,
      askPick,
      pickAskEntry,
    ],
  );

  return (
    <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return ctx;
}
