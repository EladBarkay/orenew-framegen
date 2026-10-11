import { describe, expect, it } from "vitest";

import { createFrameGenClient } from "../src/index.js";

describe("createFrameGenClient", () => {
  it("calls the health endpoint and returns typed data", async () => {
    const requested: string[] = [];
    const client = createFrameGenClient({
      baseUrl: "http://framegen.test",
      fetch: async (request: Request) => {
        requested.push(request.url);
        return Response.json({ status: "ok", version: "0.1.0" });
      },
    });
    const { data } = await client.GET("/v1/health");
    expect(requested).toEqual(["http://framegen.test/v1/health"]);
    expect(data?.status).toBe("ok");
  });
});
