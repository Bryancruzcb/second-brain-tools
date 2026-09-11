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
import { fetchReady } from "@/lib/api";
import { VIEWS, type ViewId } from "@/lib/workspace";

type ReadyState = {
  ready: boolean;
  components: Record<string, boolean>;
} | null;

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
};

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<ViewId>("notes");
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [mapFocusId, setMapFocusId] = useState<string | null>(null);
  const [repairIssueId, setRepairIssueId] = useState<string | null>(null);
  const [askContextId, setAskContextId] = useState<string | null>(null);
  const [commandOpen, setCommandOpen] = useState(false);
  const [ready, setReady] = useState<ReadyState>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetchReady();
        if (!cancelled) setReady(res);
      } catch {
        if (!cancelled) setReady({ ready: false, components: {} });
      }
    };
    void poll();
    const id = window.setInterval(poll, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

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
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
    [],
  );

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
    }),
    [
      view,
      selectedNoteId,
      selectNote,
      mapFocusId,
      repairIssueId,
      askContextId,
      commandOpen,
      ready,
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
