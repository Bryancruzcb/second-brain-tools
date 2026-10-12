"use client";

import { useSyncExternalStore } from "react";
import { ALL_OPEN, parsePanes, type Panes } from "@/lib/panes";

/**
 * The Notes view's folded panes, remembered in this browser. One shared cell:
 * every reader re-renders when it changes. The server render and the first
 * client render use "all open", so hydration always matches.
 */
const STORAGE_KEY = "atlas.notes.panes";
const listeners = new Set<() => void>();
let current: Panes | null = null;

function snapshot(): Panes {
  if (current === null) {
    let raw: string | null = null;
    try {
      raw = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      // Storage blocked (private window, site data off): panes start open.
    }
    current = parsePanes(raw);
  }
  return current;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function setPanes(next: Panes) {
  current = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Not saved; the choice still holds until the page reloads.
  }
  listeners.forEach((listener) => listener());
}

export function usePanes(): readonly [Panes, (next: Panes) => void] {
  const panes = useSyncExternalStore(subscribe, snapshot, () => ALL_OPEN);
  return [panes, setPanes];
}
