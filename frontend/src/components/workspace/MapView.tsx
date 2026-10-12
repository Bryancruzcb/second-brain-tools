"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError, fetchGraph } from "@/lib/api";
import {
  buildGlobe,
  clusterNames,
  isShown,
  matchesQuery,
  type Globe,
  type GlobeFilter,
} from "@/lib/vaultGlobe";
import { useWorkspace } from "./context";
import { NoteInspector } from "./NoteInspector";
import { GlobeLegend, VaultGlobe } from "./VaultGlobe";

type Vault =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; globe: Globe };

/** The whole vault as a 3D map, with filters, and the note you pick in a side pane. */
export function MapView() {
  const { mapFocusId, selectNote, selectedNoteId } = useWorkspace();
  const [vault, setVault] = useState<Vault>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [cluster, setCluster] = useState("all");
  const [includeChats, setIncludeChats] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchGraph()
      .then((g) => {
        if (!cancelled) setVault({ status: "ready", globe: buildGlobe(g.nodes || [], g.edges || []) });
      })
      .catch((e) => {
        if (!cancelled)
          setVault({ status: "error", message: e instanceof ApiError ? e.message : "Could not load vault graph." });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const globe = vault.status === "ready" ? vault.globe : null;
  const filter: GlobeFilter = useMemo(() => ({ cluster, includeChats }), [cluster, includeChats]);
  const clusters = useMemo(() => (globe ? clusterNames(globe) : []), [globe]);
  const shown = useMemo(
    () =>
      globe
        ? globe.nodes.filter(
            (n) => (n.kind === "chat" || n.kind === "note") && isShown(n, filter) && matchesQuery(n, query),
          ).length
        : 0,
    [globe, filter, query],
  );
  const filtering = cluster !== "all" || !includeChats || query.trim() !== "";

  const subtitle =
    vault.status === "loading"
      ? "Loading vault graph…"
      : vault.status === "error"
        ? "Backend unavailable"
        : `${vault.globe.counts.chats} AI chats · ${vault.globe.counts.notes} notes · ${vault.globe.counts.links} links${
            filtering ? ` · showing ${shown}` : ""
          }`;

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="view-head">
          <div>
            <h1>Map</h1>
            <p className="sub" role="status">{subtitle}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="search"
              className="control focus-ring w-44"
              placeholder="Highlight by name"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Highlight notes by name"
            />
            <select
              className="control focus-ring"
              value={cluster}
              onChange={(e) => setCluster(e.target.value)}
              aria-label="Show one folder"
            >
              <option value="all">All folders</option>
              {clusters.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <label className="check-control text-[14px]">
              <input
                type="checkbox"
                checked={includeChats}
                onChange={(e) => setIncludeChats(e.target.checked)}
              />
              Chats
            </label>
          </div>
        </header>
        <div className="map-field">
          <VaultGlobe
            className="globe-fill"
            label="3D map of your vault"
            globe={globe}
            state={vault.status}
            errorText={vault.status === "error" ? vault.message : undefined}
            selectedId={mapFocusId}
            turnToId={mapFocusId}
            filter={filter}
            query={query}
            onPick={(id) => selectNote(id, { askContext: true })}
          />
        </div>
        {globe && (
          <div className="map-legend">
            <GlobeLegend showSource={false} />
          </div>
        )}
      </section>
      {selectedNoteId && (
        <aside className="w-[min(26rem,38%)] shrink-0 border-l border-hairline bg-panel max-md:absolute max-md:inset-0 max-md:z-10 max-md:w-full max-md:border-l-0">
          <NoteInspector onClose={() => selectNote(null)} />
        </aside>
      )}
    </div>
  );
}
