import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const projectRoot = path.resolve(__dirname, "../../../../..");
const resolveConfig = require("tailwindcss/resolveConfig");
const theme = resolveConfig(require(path.join(projectRoot, "tailwind.config.js"))).theme as {
  colors: Record<string, unknown>;
};

// tw-<utility>-<family>-<shade>, e.g. tw-bg-violet-700, tw-ring-emerald-100, tw-border-t-blue-600
const COLOR_CLASS = /tw-(?:[a-z-]+:)*(?:tw-)?(?:bg|text|border(?:-[xytrbl])?|ring|from|via|to|fill|stroke|shadow|divide|outline|accent|decoration|placeholder)-([a-z]+(?:-[a-z]+)?)-(\d{2,3})\b/g;

describe("Tailwind palette", () => {
  it("generates every colour family the fault-detection screens use", () => {
    // withMT swaps Tailwind's palette for Material Tailwind's; a family missing
    // there produces no CSS at all (1.7.0 shipped invisible violet buttons)
    const missing = new Map<string, Set<string>>();
    for (const file of readdirSync(__dirname).filter((name) => /\.tsx?$/.test(name) && !name.includes(".test."))) {
      const source = readFileSync(path.join(__dirname, file), "utf-8");
      for (const match of source.matchAll(COLOR_CLASS)) {
        const family = match[1];
        if (!(family in theme.colors)) missing.set(family, (missing.get(family) ?? new Set()).add(file));
      }
    }
    expect(Object.fromEntries([...missing].map(([family, files]) => [family, [...files]]))).toEqual({});
  });

  it("keeps the Material Tailwind palette the rest of iMPS relies on", () => {
    for (const family of ["blue-gray", "gray", "blue", "amber", "red", "green", "deep-purple"]) {
      expect(theme.colors, family).toHaveProperty(family);
    }
  });
});
