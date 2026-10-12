/**
 * Interface text (DESIGN.md D7). Every word the app shows lives in src/locales/<language>.json;
 * components only name keys. Adding a language is adding a file with the same keys
 * (src/locales/locales.test.ts checks that) and listing it in LANGUAGES.
 *
 * A message may hold `{name}` placeholders, filled from `values`.
 */
import en from "../locales/en.json";

export type MessageKey = keyof typeof en;
type Messages = Record<MessageKey, string>;

export const LANGUAGES = { en: { messages: en as Messages, direction: "ltr" } } as const;
export type Language = keyof typeof LANGUAGES;

// Reactive, so everything shown with t() or parts() changes when the language does.
let current: Language = $state("en");

export function setLanguage(language: Language): void {
  current = language;
  document.documentElement.lang = language;
  document.documentElement.dir = LANGUAGES[language].direction;
}

/** The message for `key`, with its `{name}` placeholders filled from `values`. */
export function t(key: MessageKey, values: Record<string, string | number> = {}): string {
  return LANGUAGES[current].messages[key].replace(/\{(\w+)\}/g, (whole, name: string) =>
    Object.hasOwn(values, name) ? String(values[name]) : whole,
  );
}

export type Part = { text: string } | { slot: string };

/**
 * The message split around its placeholders, for messages that contain markup such as a
 * link: the component renders `{ slot }` parts itself, so the sentence stays whole in the
 * locale file and translators can move the link.
 */
export function parts(key: MessageKey): Part[] {
  return LANGUAGES[current].messages[key]
    .split(/(\{\w+\})/)
    .filter((piece) => piece !== "")
    .map((piece) => {
      const slot = /^\{(\w+)\}$/.exec(piece);
      return slot ? { slot: slot[1] as string } : { text: piece };
    });
}
