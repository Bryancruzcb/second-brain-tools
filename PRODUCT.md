# Product

## Register

product

## Users

The primary user is the owner of a large Obsidian vault working at a desktop or laptop, often during focused study, research, or planning sessions. They need to find ideas quickly, understand how notes connect, review neglected knowledge, repair vault structure, and ask grounded questions without sending private notes to a hosted AI service.

## Product Purpose

Second Brain turns a local Obsidian vault into an explorable knowledge workspace. A Rust parser maps notes and links, ChromaDB retrieves relevant context, and a local Qwen model synthesizes answers. Success means the user can move fluidly between overview, discovery, reading, editing, and AI-assisted synthesis while staying confident that the system is local, legible, and responsive.

## Brand Personality

Focused, intelligent, and quietly distinctive. The interface should feel like a trusted cartographer's instrument for thought: precise enough for daily work, atmospheric enough to reward exploration, and calm enough to keep the notes—not the chrome—at the center.

## Anti-references

- Generic AI tool landing pages with oversized hero copy, floating gradient orbs, and repetitive metric cards.
- Decorative neon cyberpunk dashboards where every element glows and inactive controls compete for attention.
- Glassmorphism-heavy interfaces that blur hierarchy and reduce text contrast.
- Marketing-page scrolling that loses task context, persistent navigation, or live workspace state.
- Novel controls that replace familiar navigation, search, editing, or dialog behavior without a user benefit.

## Design Principles

1. Make the vault the protagonist: navigation and controls should frame the user's knowledge, never overpower it.
2. Support one continuous loop from search to inspect to connect to ask, with context preserved between views.
3. Reveal depth progressively: keep common actions immediate and place advanced graph or editing tools where they become relevant.
4. Communicate system state plainly, especially scanning, loading, saving, indexing, AI availability, and empty or failed results.
5. Earn atmosphere through structure, typography, and the living graph rather than decorative effects.

## Accessibility & Inclusion

Target WCAG 2.2 AA for text contrast, focus visibility, keyboard access, control sizing, and semantic labeling. Never rely on color alone for status or graph meaning. Respect reduced-motion preferences, preserve usable fallbacks when WebGL is unavailable, and keep the core search, note, and chat workflows viable at narrow desktop and mobile widths.
