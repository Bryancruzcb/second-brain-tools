/** Folder helpers shared by the Recent list, the map, and the Map's folder filter. */

function normalizePath(id: string): string {
  return id.replace(/\\/g, "/");
}

export function isChatNote(id: string): boolean {
  const path = normalizePath(id);
  return path.startsWith("05 AI Chats/") || path.includes("/05 AI Chats/");
}

export function folderCluster(id: string): string {
  const path = normalizePath(id);
  if (isChatNote(path)) return "Chats";
  const slash = path.indexOf("/");
  if (slash < 0) return "Vault";
  const first = path.slice(0, slash);
  const stripped = first.replace(/^\d+\s+/, "").trim();
  return stripped || "Vault";
}
