import { describe, expect, it } from "vitest";

import { errorKey } from "./errors.ts";

describe("errorKey", () => {
  it("names the message for a known code", () => {
    const answer = { error: { code: "email_taken", message: "…", detail: null } };
    expect(errorKey(answer)).toBe("error.email_taken");
  });

  it("falls back for codes without their own message", () => {
    expect(errorKey({ error: { code: "something_new", message: "…" } })).toBe("error.unknown");
    expect(errorKey("not an error body")).toBe("error.unknown");
  });

  it("says so when there was no answer", () => {
    expect(errorKey(undefined)).toBe("error.network");
  });
});
