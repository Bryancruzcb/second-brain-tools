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
| Hero chrome   | `GET /api/recent`                        |

## Notes

- UI look stays the Night Atlas marketing shell; content is real vault titles/counts.
- Map caps ~42 highest-degree nodes for readability; subtitle shows full vault note count.
- Health issue lists come from the backend scan (`broken_links`, `orphaned_notes`, `tagless_notes`). When `vault-core` is missing, `backend/health_hygiene.py` derives those lists from Chroma so Repair is populated; empty lists then mean a clean scan, not a missing binary.
- `frontend/src/data/mock.ts` is no longer consumed by the panels.
