/**
 * Checks behind src/locales/locales.test.ts (DESIGN.md D7): finding text written straight
 * into components, and physical CSS properties.
 */

/** Attributes whose values people read or hear. */
const TEXT_ATTRIBUTES =
  /\s(?:title|alt|placeholder|label|value|aria-(?:label|description|placeholder|roledescription|valuetext))\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>{}]+))/g;

/** The text of a component's markup, without scripts, styles, comments and {expressions}. */
export function markupText(source: string): { text: string; attributes: string[] } {
  const markup = withoutExpressions(
    source
      .replace(/<script[\s\S]*?<\/script>/g, "")
      .replace(/<style[\s\S]*?<\/style>/g, "")
      .replace(/<!--[\s\S]*?-->/g, ""),
  );
  const attributes = [...markup.matchAll(TEXT_ATTRIBUTES)]
    .map((match) => match[1] ?? match[2] ?? match[3] ?? "")
    .filter((value) => /\p{L}/u.test(value));
  const text = markup.replace(/<[^>]*>/g, " ").replace(/&\w+;/g, " ");
  return { text: text.replace(/[^\p{L}]+/gu, " ").trim(), attributes };
}

function withoutExpressions(markup: string): string {
  let kept = "";
  let depth = 0;
  for (const char of markup) {
    if (char === "{") depth += 1;
    else if (char === "}") depth = Math.max(0, depth - 1);
    else if (depth === 0) kept += char;
  }
  return kept;
}

const PHYSICAL_PROPERTY =
  /^(?:(?:margin|padding|inset|border)-(?:left|right|top|bottom)(?:-.*)?|border-(?:top|bottom)-(?:left|right)-radius|left|right|top|bottom)$/;
const PHYSICAL_VALUE = /^(?:text-align|float|clear)$/;

/** Physical properties among CSS declarations such as "margin-left: 1px; color: red". */
function physicalDeclarations(declarations: string): string[] {
  return declarations.split(";").flatMap((declaration) => {
    const colon = declaration.indexOf(":");
    if (colon < 0) return [];
    const property = declaration.slice(0, colon).trim().toLowerCase();
    const value = declaration
      .slice(colon + 1)
      .trim()
      .toLowerCase();
    if (PHYSICAL_PROPERTY.test(property)) return [property];
    if (PHYSICAL_VALUE.test(property) && /^(?:left|right)\b/.test(value)) {
      return [`${property}: ${value}`];
    }
    return [];
  });
}

/** Declarations inside the {blocks} of a style sheet; selectors are left out. */
function declarationsOf(css: string): string[] {
  const blocks: string[] = [];
  let current = "";
  let depth = 0;
  for (const char of css.replace(/\/\*[\s\S]*?\*\//g, "")) {
    if (char === "{") {
      depth += 1;
      current = "";
    } else if (char === "}") {
      blocks.push(current);
      current = "";
      depth = Math.max(0, depth - 1);
    } else if (depth > 0) current += char;
  }
  return blocks;
}

/**
 * Physical CSS properties in a component (its style blocks, style="" attributes and
 * style: directives) or, for a .css file, in the whole sheet.
 */
export function physicalProperties(source: string, isComponent = true): string[] {
  if (!isComponent) return declarationsOf(source).flatMap(physicalDeclarations);
  const styles = [...source.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]!);
  const markup = source
    .replace(/<script[\s\S]*?<\/script>/g, "")
    .replace(/<style[\s\S]*?<\/style>/g, "");
  const inline = [...markup.matchAll(/\sstyle\s*=\s*(?:"([^"]*)"|'([^']*)')/g)].map(
    (match) => match[1] ?? match[2] ?? "",
  );
  const directives = [...markup.matchAll(/\sstyle:([\w-]+)/g)].map((match) => `${match[1]}: x`);
  return [
    ...styles.flatMap(declarationsOf).flatMap(physicalDeclarations),
    ...inline.flatMap(physicalDeclarations),
    ...directives.flatMap(physicalDeclarations),
  ];
}

/** The {placeholders} of a message, sorted. */
export function placeholders(message: string): string[] {
  return [...message.matchAll(/\{(\w+)\}/g)].map((match) => match[1]!).sort();
}
