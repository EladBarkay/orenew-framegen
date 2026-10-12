import { describe, expect, it } from "vitest";

import { parts, t } from "./i18n.ts";

describe("t", () => {
  it("fills placeholders", () => {
    expect(t("health.up", { version: "1.2" })).toBe("API is up (version 1.2).");
  });

  it("leaves a placeholder without a value visible", () => {
    expect(t("health.up")).toBe("API is up (version {version}).");
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
