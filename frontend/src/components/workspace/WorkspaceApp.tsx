"use client";

import { Sidebar } from "./Sidebar";
import { CommandBar } from "./CommandBar";
import { NotesView } from "./NotesView";
import { MapView } from "./MapView";
import { RepairView } from "./RepairView";
import { AskView } from "./AskView";
import { WorkspaceProvider, useWorkspace } from "./context";
import { VIEW_META } from "@/lib/workspace";

function Stage() {
  const { view } = useWorkspace();
  return (
    <main
      className="workspace-stage relative"
      aria-label={VIEW_META[view].label}
    >
      {view === "notes" && <NotesView />}
      {view === "map" && <MapView />}
      {/* Restyled into HealthView in the Health step; same detections. */}
      {view === "health" && <RepairView />}
      {view === "ask" && <AskView />}
    </main>
  );
}

export function WorkspaceApp() {
  return (
    <WorkspaceProvider>
      <div className="workspace">
        <Sidebar />
        <div className="workspace-main">
          <Stage />
        </div>
      </div>
      <CommandBar />
    </WorkspaceProvider>
  );
}
