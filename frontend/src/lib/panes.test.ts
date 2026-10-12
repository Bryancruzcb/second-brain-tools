import { describe, expect, test } from "bun:test";
import { ALL_OPEN, MAP_ONLY, isMapOnly, parsePanes, toggleMapOnly } from "./panes";

describe("Notes panes", () => {
  test("parsePanes keeps a saved choice and treats anything else as open", () => {
    expect(parsePanes(JSON.stringify({ recent: false, reader: true }))).toEqual({ recent: false, reader: true });
    expect(parsePanes(JSON.stringify(MAP_ONLY))).toEqual(MAP_ONLY);
    expect(parsePanes(null)).toEqual(ALL_OPEN);
    expect(parsePanes("")).toEqual(ALL_OPEN);
    expect(parsePanes("not json")).toEqual(ALL_OPEN);
    expect(parsePanes("null")).toEqual(ALL_OPEN);
    expect(parsePanes("[]")).toEqual(ALL_OPEN);
    expect(parsePanes(JSON.stringify({ recent: "no" }))).toEqual(ALL_OPEN);
  });

  test("Map only folds both panes, and opens both when they are already folded", () => {
    expect(isMapOnly(MAP_ONLY)).toBe(true);
    expect(isMapOnly({ recent: false, reader: true })).toBe(false);
    expect(toggleMapOnly(ALL_OPEN)).toEqual(MAP_ONLY);
    expect(toggleMapOnly({ recent: true, reader: false })).toEqual(MAP_ONLY);
    expect(toggleMapOnly(MAP_ONLY)).toEqual(ALL_OPEN);
  });
});
