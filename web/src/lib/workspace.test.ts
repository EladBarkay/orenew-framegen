import { beforeEach, describe, expect, it, vi } from "vitest";

const GET = vi.fn();
vi.mock("./api.ts", () => ({ api: { GET } }));

const { choose, listWorkspaces } = await import("./workspace.svelte.ts");

const personal = { id: "wsp_p", name: "Personal", kind: "personal", role: "owner" } as const;
const studio = { id: "wsp_s", name: "Light & Lace", kind: "studio", role: "admin" } as const;

describe("choose", () => {
  it("keeps the remembered workspace", () => {
    expect(choose([personal, studio], "wsp_s")).toBe(studio);
  });

  it("falls back to the personal workspace when the remembered one is gone", () => {
    expect(choose([studio, personal], "wsp_left")).toBe(personal);
    expect(choose([studio, personal], null)).toBe(personal);
  });

  it("has nothing to choose from an empty list", () => {
    expect(choose([], null)).toBeNull();
  });
});

describe("listWorkspaces", () => {
  beforeEach(() => GET.mockReset());

  it("follows every page", async () => {
    GET.mockResolvedValueOnce({ data: { items: [personal], next_cursor: "c1" }, response: {} });
    GET.mockResolvedValueOnce({ data: { items: [studio], next_cursor: null }, response: {} });
    expect(await listWorkspaces()).toEqual([personal, studio]);
    expect(GET.mock.calls[1]?.[1]).toEqual({ params: { query: { limit: 100, cursor: "c1" } } });
  });
});
