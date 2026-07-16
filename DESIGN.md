---
name: The Night Atlas
version: 1.0.0
colors:
  ink-950: "#0D1117"
  ink-900: "#161B22"
  ink-850: "#1C222B"
  paper-50: "#F4F1E8"
  paper-300: "#AEB6C2"
  signal: "#C9F568"
  sky: "#61A8FF"
  success: "#68D9B0"
  warning: "#E8B94F"
  danger: "#F06F62"
typography:
  sans: Instrument Sans
  mono: IBM Plex Mono
radii:
  small: 7px
  medium: 11px
  large: 16px
---

# Overview

The Night Atlas is a quiet, precise desktop instrument for navigating a personal knowledge system. The vault remains the protagonist; the interface supplies orientation, state, and a small number of purposeful actions. Atmosphere comes from near-black ink, ivory text, disciplined rules, cartographic labels, and the living graph—not decorative gradients or excessive glow.

# Colors

Use `ink-950` for the app field, `ink-900` for primary panels, and `ink-850` only for elevated or interactive surfaces. `paper-50` carries primary text and `paper-300` carries supporting text. Chartreuse `signal` is rare and reserved for primary actions, active navigation, and focus. `sky` indicates AI or semantic activity. Success, warning, and danger colors always appear with text or an icon so state never depends on color alone.

# Typography

Instrument Sans is the working face for navigation, controls, titles, and prose. IBM Plex Mono is used for short system labels, counts, shortcuts, timestamps, and graph metadata. Headings are compact and sentence-case; avoid oversized marketing typography. Body text favors comfortable line height and restrained measure, especially in rendered Markdown.

# Elevation

Hierarchy is built with borders, tonal steps, and spacing before shadows. Primary panels use a one-pixel cool-gray border. Floating search results, dialogs, tooltips, and the note panel may use a concentrated shadow. Blur and translucent glass are not default surfaces. Rounded corners are modest: 7px for controls, 11px for panels, and 16px only for major containers.

# Components

The app shell uses a persistent left rail, command search top bar, and one continuous scroll surface linking Overview, Knowledge Graph, and Ask Qwen. Sidebar selection follows the visible section and navigation scrolls without unmounting workspace state. Buttons have primary, secondary, ghost, text, compact, and icon forms with consistent focus-visible rings. The graph owns its search, filters, camera controls, direct node labels, and stats. Note and chat panels preserve context as users move between discovery, reading, editing, and asking.

# Do’s and Don’ts

- Do keep common actions visible and advanced graph controls contextual.
- Do write plain status copy for scanning, indexing, loading, saving, and failures.
- Do maintain keyboard access, reduced-motion behavior, responsive layouts, and WCAG AA contrast.
- Do use the chartreuse signal sparingly so it retains meaning.
- Don’t let the continuous scroll behave like a marketing page; preserve live state, task density, and persistent navigation.
- Don’t use gradient text, neon bloom on every element, or glassmorphism as the visual system.
- Don’t hide essential navigation or replace familiar controls with novelty.
