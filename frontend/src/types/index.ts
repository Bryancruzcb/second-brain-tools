export type Note = {
  id: string;
  title: string;
  path: string;
  tags: string[];
  excerpt: string;
  body: string;
  updatedAt: string;
  links: string[];
  backlinks: string[];
};

export type HealthIssueKind = "broken-link" | "orphan" | "tagless";

export type HealthIssue = {
  id: string;
  kind: HealthIssueKind;
  noteId: string;
  title: string;
  detail: string;
  action: string;
};

export type GraphNode = {
  id: string;
  x: number;
  y: number;
  r: number;
  cluster: string;
};
