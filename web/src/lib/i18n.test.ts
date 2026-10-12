import { describe, expect, it } from "vitest";

import { parts, t } from "./i18n.svelte.ts";

describe("t", () => {
  it("fills placeholders", () => {
    expect(t("home.signed_in_as", { name: "Noa" })).toBe("Signed in as Noa.");
  });

  it("leaves a placeholder without a value visible", () => {
    expect(t("home.signed_in_as")).toBe("Signed in as {name}.");
  });
});

describe("parts", () => {
  it("splits a message around its placeholders", () => {
    expect(parts("footer.licence")).toEqual([
      { text: "FrameGen is free software under the " },
      { slot: "licence" },
      { text: "." },
    ]);
  });
});
