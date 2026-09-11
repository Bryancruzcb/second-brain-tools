# Atlas / Night Atlas frontend

Night Atlas (`frontend/`) is wired to the live FastAPI backend instead of demo fixtures.

## Requirements

- Backend must be running at `http://127.0.0.1:8000` (override with `NEXT_PUBLIC_API_URL`).
- Vault index / health cache should be populated (`/api/ready`, `/api/health`, `/api/graph`).
- Ask uses `POST /api/query` (Ollama). If Ollama is down, Ask shows a clear error.

## Endpoints used

| UI            | API                                      |
|---------------|------------------------------------------|
| Recent reel   | `GET /api/recent`, `GET /api/note/{ref}` |
| Map           | `GET /api/graph` (client-side layout)    |
| Repair/Health | `GET /api/health`                        |
| Ask           | `POST /api/query`                        |
| Sidebar       | `GET /api/recent`, `GET /api/ready`      |

## Notes

- Persistent sidebar (sections, recent notes, backend status) beside one continuous scroll: Overview, Map, Repair, Ask. Below 1024px the sidebar becomes a sticky top bar.
- Map ranks notes by real wikilinks (ghost/suggested links are neither counted nor drawn), caps the 42 most-linked (24 below 640px wide), and draws them straight on the page. Labels go to the active note, its neighbours, then the most-linked notes, skipping any that would overlap; every other node shows its title on hover or focus.
- Health issue lists come from the backend scan (`broken_links`, `orphaned_notes`, `tagless_notes`). When `vault-core` is missing, `backend/health_hygiene.py` derives those lists from Chroma so Repair is populated; empty lists then mean a clean scan, not a missing binary.
- `frontend/src/data/mock.ts` is no longer consumed by the panels.
