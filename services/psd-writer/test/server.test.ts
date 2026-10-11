import type { AddressInfo } from "node:net";

import { readPsd } from "ag-psd";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { createPsdWriterServer } from "../src/server.js";

const server = createPsdWriterServer();
let base = "";

beforeAll(async () => {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));

describe("psd-writer", () => {
  it("reports health", async () => {
    const res = await fetch(`${base}/health`);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
  });

  it("writes a PSD of the requested size", async () => {
    const res = await fetch(`${base}/v1/documents`, {
      method: "POST",
      body: JSON.stringify({ width: 1200, height: 1800 }),
    });
    expect(res.status).toBe(200);
    const psd = readPsd(new Uint8Array(await res.arrayBuffer()), {
      skipCompositeImageData: true,
      skipLayerImageData: true,
      skipThumbnail: true,
    });
    expect([psd.width, psd.height]).toEqual([1200, 1800]);
  });

  it("rejects an invalid size with an error code", async () => {
    const res = await fetch(`${base}/v1/documents`, {
      method: "POST",
      body: JSON.stringify({ width: -1, height: 10 }),
    });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: { code: "invalid_size" } });
  });

  it("rejects a body that is not JSON", async () => {
    const res = await fetch(`${base}/v1/documents`, { method: "POST", body: "not json" });
    expect(res.status).toBe(400);
  });
});
