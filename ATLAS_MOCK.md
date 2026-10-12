# Atlas / Night Atlas frontend

Night Atlas (`frontend/`) follows the Observatory style in `DESIGN.md`: four tabs at the top (Notes, Ask, Map, Repair), a Ctrl K search palette, and one active view. The Notes view is the Recent list, a 3D map of the whole vault with the Ask dock under it, and the reading pane. Panels load from the live FastAPI backend.

The Vercel `atlas-prototype` project is a separate marketing mock (`_atlas-mock-extract`), not this app.

## Requirements

- Backend must be running at `http://127.0.0.1:8000`. The browser calls same-origin `/api/...` and Next.js proxies it there; change the target with `ATLAS_BACKEND_URL` (server-side), or set `NEXT_PUBLIC_API_URL` to have the browser call a backend directly.
- Vault index / health cache should be populated (`/api/ready`, `/api/health`, `/api/graph`).
- Ask uses `POST /api/query/stream` (Ollama, NDJSON: sources first, then the answer). `POST /api/query` is the same Ask returned whole. If Ollama is down, Ask shows a clear error.

## Endpoints used

| UI            | API                                      |
|---------------|------------------------------------------|
| Notes (Recent, 3D vault map, reading pane) | `GET /api/recent`, `GET /api/note/{ref}`, `GET /api/graph` |
| Ask dock (latest answer) | `GET /api/ask/history?limit=1`, `DELETE /api/ask/history/{id}` |
| Map           | `GET /api/graph` (3D layout in the browser) |
| Repair/Health | `GET /api/health`                        |
| Ask           | `POST /api/query/stream`, `POST /api/query` |
| Command search | `GET /api/search`                       |
| Save note      | `POST /api/note/{ref}`                  |

## Notes

- The look is the Observatory system in `DESIGN.md` (dark only); content is real vault titles/counts.
- The 3D vault map (Notes and Map) draws every note and AI chat from `/api/graph` as a dot: its distance from the middle is its age (from the date in the file name), and its slice of the circle is its folder. Wikilinks show as lines for the picked dot (ghost links are skipped). A chat's project copies fold into the chat. It reads no note text; the reading pane fetches only the note you open.
- Map is the same 3D map full size, with a name highlight, a one-folder filter and a Chats toggle (on by default); the subtitle counts chats, notes and links, and how many are showing when a filter is on.
- Health issue lists come from the backend scan (`broken_links`, `orphaned_notes`, `tagless_notes`). When `vault-core` is missing, `backend/health_hygiene.py` derives those lists from Chroma so Repair is populated; empty lists then mean a clean scan, not a missing binary.
- Inspector can edit and save notes unless the file is a OneDrive placeholder (`read_only_fallback`).
