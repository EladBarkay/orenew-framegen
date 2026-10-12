/**
 * Keeps the interface ready for more languages (DESIGN.md D7):
 * every key used exists and every key exists for a reason, other languages have the same
 * keys, components hold no text of their own, and styles use logical properties only, so
 * right-to-left needs no second layout.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { markupText, physicalProperties, placeholders } from "./checks.ts";
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

  it("every language has the same keys and placeholders as English", () => {
    for (const file of readdirSync(LOCALES).filter((name) => name.endsWith(".json"))) {
      const messages = JSON.parse(readFileSync(join(LOCALES, file), "utf8")) as Record<
        string,
        string
      >;
      expect(Object.keys(messages).sort(), file).toEqual(Object.keys(en).sort());
      for (const [key, english] of Object.entries(en)) {
        expect(placeholders(messages[key] ?? ""), `${file} ${key}`).toEqual(placeholders(english));
      }
    }
  });
});

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
    expect(markupText("<img alt='A dog' title=Hi /><input value=\"Send\" />")).toEqual({
      text: "",
      attributes: ["A dog", "Hi", "Send"],
    });
    expect(markupText('<p>{t("x")}</p><img alt={t("y")} />')).toEqual({
      text: "",
      attributes: [],
    });
  });
});

describe("styles", () => {
  const styled = files(SRC).filter((path) => /\.(svelte|css)$/.test(path));

  it.each(styled.map((path) => [relative(SRC, path), path]))(
    "%s uses logical properties only",
    (_, path) => {
      const source = readFileSync(path, "utf8");
      expect(physicalProperties(source, path.endsWith(".svelte"))).toEqual([]);
    },
  );

  it("finds physical properties, and only properties", () => {
    const component = [
      "<script>const at = { top: 1 };</script>",
      '<p style="padding-right: 2px" style:margin-left={x}></p>',
      "<style>.top:hover { margin-left: 1px; border-left-width: 1px;",
      "  border-top-left-radius: 2px; text-align: right; inset-inline: 0 }</style>",
    ].join("\n");
    expect(physicalProperties(component)).toEqual([
      "margin-left",
      "border-left-width",
      "border-top-left-radius",
      "text-align: right",
      "padding-right",
      "margin-left",
    ]);
    expect(physicalProperties(".a { float: left; margin-inline: 0 }", false)).toEqual([
      "float: left",
    ]);
  });
});
