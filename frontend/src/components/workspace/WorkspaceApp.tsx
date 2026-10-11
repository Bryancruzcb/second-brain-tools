"use client";

import { TopBar } from "./TopBar";
import { CommandBar } from "./CommandBar";
import { NotesView } from "./NotesView";
import { MapView } from "./MapView";
import { RepairView } from "./RepairView";
import { AskView } from "./AskView";
import { WorkspaceProvider, useWorkspace } from "./context";

function Stage() {
  const { view } = useWorkspace();
  // Notes scrolls with the page (chart, dock, reading pane); the other views
  // fill the window and scroll inside their own panes.
  return (
    <main className={`workspace-stage${view === "notes" ? "" : " fixed"}`} id="main">
      {view === "notes" && <NotesView />}
      {view === "map" && <MapView />}
      {view === "repair" && <RepairView />}
      {view === "ask" && <AskView />}
    </main>
  );
}

export function WorkspaceApp() {
  return (
    <WorkspaceProvider>
      <div className="workspace">
        <TopBar />
        <Stage />
        <CommandBar />
      </div>
    </WorkspaceProvider>
  );
}
