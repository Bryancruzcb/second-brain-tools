# Atlas — second brain prototype

Workspace for a local Obsidian vault: a persistent sidebar (sections, recent notes, backend status) beside one continuous scroll — Overview with the recent-notes reel and inline reader, the link Map drawn straight on the page, the Repair queue, and Ask. Everything is fed by the FastAPI backend; see [`../ATLAS_MOCK.md`](../ATLAS_MOCK.md) for the endpoint table.

```bash
bun install
bun run dev
```

Open http://localhost:3000

Below 1024px the sidebar gives way to a sticky top bar with the same section links.
