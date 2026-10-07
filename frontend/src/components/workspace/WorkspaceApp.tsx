"use client";

import { LeftRail } from "./LeftRail";
import { CommandBar } from "./CommandBar";
import { NotesView } from "./NotesView";
import { MapView } from "./MapView";
import { RepairView } from "./RepairView";
import { AskView } from "./AskView";
import { WorkspaceProvider, useWorkspace } from "./context";

function Stage() {
  const { view } = useWorkspace();
  return (
    <div className="workspace-stage relative">
      {view === "notes" && <NotesView />}
      {view === "map" && <MapView />}
      {view === "repair" && <RepairView />}
      {view === "ask" && <AskView />}
    </div>
  );
}

export function WorkspaceApp() {
  return (
    <WorkspaceProvider>
      <div className="workspace">
        <LeftRail />
        <div className="workspace-main">
          <CommandBar />
          <Stage />
        </div>
      </div>
    </WorkspaceProvider>
  );
}
