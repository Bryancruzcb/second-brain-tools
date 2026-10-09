/**
 * Folder colors. Known vault folders get their design color; any other folder
 * gets a stable color from the same family (hashed by name).
 */
const KNOWN: Record<string, string> = {
  career: "var(--folder-career)",
  vault: "var(--folder-vault)",
  school: "var(--folder-school)",
  projects: "var(--folder-projects)",
  memory: "var(--folder-memory)",
  "imported files": "var(--folder-imported)",
  imported: "var(--folder-imported)",
  home: "var(--folder-home)",
};

const FAMILY = [
  "#7AA7FF",
  "#B59BFF",
  "#5FD3A0",
  "#F5A35C",
  "#62CBE0",
  "#F08DB2",
  "#E6C86E",
  "#8FD18A",
  "#FF9E8A",
  "#A5B4FC",
];

export function folderColor(name: string): string {
  const known = KNOWN[name.trim().toLowerCase()];
  if (known) return known;
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return FAMILY[h % FAMILY.length];
}
