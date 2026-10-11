# DESIGN.md: Atlas (Observatory)

This is the UI style file for the Atlas frontend (`frontend/`). It replaces the earlier design system, "The Night Atlas" (chartreuse on ink, Instrument Sans, a left rail), which is still in git history before the `ui/makeover-observatory` branch. The product keeps its Night Atlas name; only the look changed.

## The look in one sentence
Your notes as a night sky: iA Writer's black starfield with one strong idea (a star chart of recent notes), and Linear's near-black precision, with Ask docked at the bottom like a command menu.

## References
- iA Writer, dark section (`iawriter-dark` in Bryan's taste picks): a black sky, mono type, one strong idea carrying the screen. Take the star chart and the mono labels.
- Linear (`linear-hero`): near-black surfaces, small precise gray type, a docked command panel where the answer sits above the input. Take the Ask dock and the quiet gray hierarchy.
- The approved mockup: `ui-makeover-2026-10/second-brain/c/index.html` (direction C, "Observatory"), outside this repo.

## Colors
Dark only, by Bryan's choice: `color-scheme: dark`, tokens defined once on `:root` in `frontend/src/app/globals.css`. There is no light theme and no theme toggle.

| Token | Light | Dark | Used for |
|---|---|---|---|
| background (`--page`) | none | `#06080B` | page background, top bar |
| night (`--night`) | none | `#080B10` | the star chart and the Map field |
| surface (`--panel`) | none | `#0D1117` | Recent list, reading pane, dock, palette |
| raised (`--raised`) | none | `#131922` | selected rows, composer, hover |
| text (`--ink`) | none | `#E8ECF1` | body text, titles |
| text-muted (`--muted`) | none | `#A6B0BE` | secondary text, star labels |
| text-dim (`--dim`) | none | `#8A95A5` | dates, ring labels, file names |
| border (`--hairline`) | none | `#1E2632` | dividers |
| border-strong (`--hairline-strong`) | none | `#2D3747` | input and button borders, age rings |
| star (`--star`) | none | `#F4EFE3` | stars (notes), links between them |
| field (`--field`) | none | `#3B4554` | decorative background dots (no meaning) |
| primary (`--accent`) | none | `#74C7EF` | Ask button, selection, focus ring, the source bracket |
| success (`--success`) | none | `#82D6A3` | index ready, nothing to fix |
| warning (`--warning`) | none | `#E6C07B` | orphan notes, read-only cloud placeholder |
| danger (`--danger`) | none | `#F29B8B` | errors, broken links |
| info (`--info`) | none | `#74C7EF` | tips, neutral notices (same as primary) |

`--accent-ink` (`#04121B`) is the text color on a filled accent button. Every text color above passes WCAG AA (4.5:1) on every surface from `--page` to `--raised`; the dimmest pair, `--dim` on `--raised`, is about 5.8:1. `--hairline-strong` is a border color, not a text background, except under `--ink` (the pressed scope button, 10:1).

## Type
- Interface, headings and note text: **Bricolage Grotesque** (variable, optical sizes), weights 500/600/700.
- Labels, dates, file names, star names, shortcuts: **Martian Mono** at 75% width, 12px, letter-spacing 0.02em.
- Both load through `next/font/google` in `frontend/src/app/layout.tsx`, so they are self-hosted at build time (no request to Google from the browser).
- Body: 16px, line height 1.5 (1.6 to 1.7 for answers and note text).
- Scale: 12 / 14 / 16 / 20 / 28. Nothing under 12px.
- Numbers that line up (counts, dates in lists): tabular figures (`.num`).

## Spacing and shape
- Spacing steps: 4 / 8 / 12 / 16 / 24 / 32 / 48.
- Radius: 6px for small controls and chips, 8px for buttons and rows, 14px for the chart, the dock and the palette.
- Shadows: none, except the Ctrl K palette (`--shadow`), which floats over the page.
- Borders do the layering: one hairline between panes, a stronger line around inputs and the dock.

## Components
- The app keeps its own small component set: CSS classes in `globals.css` plus Tailwind utilities, and React components in `frontend/src/components/workspace/`. It does not use shadcn/ui; adding it would be a new dependency for a handful of parts.
- Buttons: primary = filled accent (`.btn-primary`, one per area: Ask, Save), secondary = outline (`.btn`), quiet = text only (`.btn-quiet`). Destructive actions use words ("Remove", "Clear history") and a confirm where they delete many things.
- Top bar: brand, four tabs (Notes, Ask, Map, Repair, each with its Ctrl shortcut), the index status outside Notes, and the Ctrl K search button.
- Star chart (`StarChart.tsx`, layout in `lib/starChart.ts`): each recent note is a star. Distance from the center = time since the last edit, on the same square-root scale as the dashed age rings. Star size = note length in words. Constellation = folder (`folderCluster()`), one wedge per folder. Lines only where the graph data has a link. The angle inside a constellation means nothing. A bracket marks the latest answer's source. The legend only states what is true of what is drawn.
- Ask dock and Ask view: the answer above, numbered citations ([1]) that point to a source list with the note title, file name and quoted text, then suggested questions or Find results, then the input with the scope choice and the privacy line.
- Reading pane: title once, file name, folder and edit time in mono, then the note with headings rendered. Edit and Save stay here.
- Status words: Broken / Orphan / Tagless pills always carry the word; color is extra.
- Cards: no cards inside cards. The chart, the dock and the reading pane are flat panels side by side.

## Motion
- CSS only, no motion library.
- One playful moment: the bracket locks onto the answer's source star when it appears (260 ms, ease-out).
- Hover color changes at 150 ms. Skeletons pulse while loading.
- `prefers-reduced-motion` turns all of it off (`globals.css`).

## Icons and art
- Small UI icons: Lucide (`lucide-react`, already a dependency). No emoji.
- No decorative art: the stars are data. The faint background dots are seeded and fixed, and carry no meaning.
- Empty states: a Lucide icon, one bold line, one plain sentence.

## Rules (every screen, always)
1. Skeleton loaders that match the final layout for anything that loads data (no layout shift). Skip them for near-instant loads.
2. Semantic colors (success, warning, danger, info) from the table above. Never use color as the only signal; pair it with an icon or text.
3. No clutter: no subtitle that restates a heading, no redundant helper text, no decorative dividers, no duplicate labels. If it isn't useful, remove it.
4. Accessibility, WCAG 2.2 AA: 4.5:1 text contrast (3:1 for large text and controls), full keyboard navigation with visible focus, a label on every input, aria-labels on icon-only buttons, alt text on meaningful images, semantic HTML, targets at least 24×24px, prefers-reduced-motion respected.
