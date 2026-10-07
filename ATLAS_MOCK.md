# Atlas / Night Atlas frontend

Night Atlas (`frontend/`) is the DESIGN.md workspace: left rail, command search, and one active view. Panels load from the live FastAPI backend.

The Vercel `atlas-prototype` project is a separate marketing mock (`_atlas-mock-extract`), not this app.

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
| Command search | `GET /api/search`                       |
| Save note      | `POST /api/note/{ref}`                  |

## Notes

- UI look stays the Night Atlas marketing shell; content is real vault titles/counts.
- Map shows ~24 notes across vault folders (Home, School, Projects, …), not KMeans blobs. Chat archives stay off until you toggle them; subtitle shows the hidden count.
- Health issue lists come from the backend scan (`broken_links`, `orphaned_notes`, `tagless_notes`). When `vault-core` is missing, `backend/health_hygiene.py` derives those lists from Chroma so Repair is populated; empty lists then mean a clean scan, not a missing binary.
- Inspector can edit and save notes unless the file is a OneDrive placeholder (`read_only_fallback`).
