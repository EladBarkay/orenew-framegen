import { describe, expect, it } from "vitest";

import { apiState } from "./health";

describe("apiState", () => {
  it("is up with the server version when health is ok", () => {
    expect(apiState({ status: "ok", version: "0.1.0" })).toEqual({ kind: "up", version: "0.1.0" });
  });

  it("is down when there is no answer", () => {
    expect(apiState(undefined)).toEqual({ kind: "down" });
  });
});
