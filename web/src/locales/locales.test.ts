/**
 * Keeps the interface ready for more languages (DESIGN.md D7):
 * every key used exists and every key exists for a reason, other languages have the same
 * keys, components hold no text of their own, and styles use logical properties only, so
 * right-to-left needs no second layout.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import en from "./en.json";

const SRC = join(import.meta.dirname, "..");
const LOCALES = join(SRC, "locales");

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? files(path) : [path];
  });
}

const sources = files(SRC).filter(
  (path) => /\.(svelte|ts)$/.test(path) && !path.endsWith(".test.ts") && !path.startsWith(LOCALES),
);
const code = sources.map((path) => readFileSync(path, "utf8")).join("\n");
const components = files(SRC).filter((path) => path.endsWith(".svelte"));

describe("locale keys", () => {
  it("every key passed to t() or parts() exists", () => {
    const used = [...code.matchAll(/\b(?:t|parts)\(\s*"([^"]+)"/g)].map((match) => match[1]);
    expect(used.filter((key) => !(key! in en))).toEqual([]);
  });

  it("every key is used somewhere", () => {
    expect(Object.keys(en).filter((key) => !code.includes(`"${key}"`))).toEqual([]);
  });

  it("every language has the same keys as English", () => {
    for (const file of readdirSync(LOCALES).filter((name) => name.endsWith(".json"))) {
      const messages = JSON.parse(readFileSync(join(LOCALES, file), "utf8")) as object;
      expect(Object.keys(messages).sort(), file).toEqual(Object.keys(en).sort());
    }
  });
});

/** The markup of a component, without scripts, styles, comments and {expressions}. */
export function markupText(source: string): { text: string; attributes: string[] } {
  let markup = source
    .replace(/<script[\s\S]*?<\/script>/g, "")
    .replace(/<style[\s\S]*?<\/style>/g, "")
    .replace(/<!--[\s\S]*?-->/g, "");
  let withoutExpressions = "";
  let depth = 0;
  for (const char of markup) {
    if (char === "{") depth += 1;
    else if (char === "}") depth = Math.max(0, depth - 1);
    else if (depth === 0) withoutExpressions += char;
  }
  markup = withoutExpressions;
  const attributes = [
    ...markup.matchAll(/\s(?:title|alt|placeholder|aria-label|label)\s*=\s*"([^"]*)"/g),
  ]
    .map((match) => match[1]!)
    .filter((value) => /\p{L}/u.test(value));
  const text = markup.replace(/<[^>]*>/g, " ").replace(/&\w+;/g, " ");
  return { text: text.replace(/[^\p{L}]+/gu, " ").trim(), attributes };
}

describe("components", () => {
  it.each(components.map((path) => [relative(SRC, path), path]))(
    "%s has no text of its own",
    (_, path) => {
      expect(markupText(readFileSync(path, "utf8"))).toEqual({ text: "", attributes: [] });
    },
  );

  it("finds text that is written straight into markup", () => {
    expect(markupText('<p>Hello {name}</p><img alt="A cat" />')).toEqual({
      text: "Hello",
      attributes: ["A cat"],
    });
    expect(markupText('<p>{t("x")}</p><img alt={t("y")} />')).toEqual({
      text: "",
      attributes: [],
    });
  });
});

const PHYSICAL =
  /\b(?:(?:margin|padding|border|inset)-(?:left|right|top|bottom)|left|right|top|bottom)\s*:|\b(?:text-align|float|clear)\s*:\s*(?:left|right)\b/g;

/** Physical CSS properties in the styles of `source`. */
export function physicalProperties(source: string): string[] {
  const styles = [...source.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]);
  const css = source.includes("<style") ? styles.join("\n") : source;
  return [...css.matchAll(PHYSICAL)].map((match) => match[0]);
}

describe("styles", () => {
  const styled = files(SRC).filter((path) => /\.(svelte|css)$/.test(path));

  it.each(styled.map((path) => [relative(SRC, path), path]))(
    "%s uses logical properties only",
    (_, path) => {
      expect(physicalProperties(readFileSync(path, "utf8"))).toEqual([]);
    },
  );

  it("finds physical properties", () => {
    const css = "<style>a { margin-left: 1px; text-align: right; top: 0; inset-inline: 0 }</style>";
    expect(physicalProperties(css)).toEqual(["margin-left:", "text-align: right", "top:"]);
  });
});
