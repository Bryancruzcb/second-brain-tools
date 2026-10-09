# Night Atlas Ask (Obsidian plugin)

Ask the vault a question without leaving Obsidian. The plugin sends it to the
Night Atlas backend's `POST /api/query`, the same endpoint the web UI's Ask view
uses, and shows the grounded answer with links to its source notes.

## Commands

- **Ask vault** — opens a question box, pre-filled with the editor selection
  if there is one. The answer opens in a modal; from there **Insert into note**
  adds it below the selection as a `[!question]` callout with `[[wikilinks]]`
  to the sources, and **Copy** puts the same callout on the clipboard.
- **Ask about current note** — same, but grounded in the active note only
  (sent as `context_nodes`, which skips retrieval).

Bind either to a hotkey under Settings → Hotkeys.

## Settings

- **Backend URL** — default `http://127.0.0.1:8000`.
- **Search scope** — `notes` (default), `chats`, or `all`.

The backend must be running, and Ask needs Ollama (see the root README). Errors
from the backend, such as Ollama being down, show as a notice with the
backend's message.

## Build and install

```bash
bun install
bun run build    # type-checks, then bundles src/ into main.js
bun test         # request logic against a mocked transport
```

Copy `manifest.json` and `main.js` into
`<vault>/.obsidian/plugins/night-atlas-ask/` and enable the plugin under
Settings → Community plugins.

Requests go through Obsidian's `requestUrl` rather than `fetch`: the backend's
CORS list admits only the Next.js frontend on `:3000`, and `requestUrl` is not
subject to CORS, so the backend needs no change.
