import { beforeEach, describe, expect, it, vi } from "vitest";

const GET = vi.fn();
vi.mock("./api.ts", () => ({ api: { GET } }));
vi.mock("$app/paths", () => ({ resolve: (path: string) => path }));
vi.mock("@sveltejs/kit", () => ({
  error: (status: number) => {
    throw { status };
  },
  redirect: (status: number, location: string) => {
    throw { status, location };
  },
}));

const { choose, forget, listWorkspaces, preferredFor, select } =
  await import("./workspace.svelte.ts");

const personal = { id: "wsp_p", name: "Personal", kind: "personal", role: "owner" } as const;
const studio = { id: "wsp_s", name: "Light & Lace", kind: "studio", role: "admin" } as const;
const here = new URL("http://site/");

describe("choose", () => {
  it("keeps the first preferred workspace the user still belongs to", () => {
    expect(choose([personal, studio], ["wsp_s"])).toBe(studio);
    expect(choose([personal, studio], ["wsp_left", "wsp_s"])).toBe(studio);
  });

  it("falls back to the personal workspace", () => {
    expect(choose([studio, personal], ["wsp_left", null])).toBe(personal);
  });

  it("has nothing to choose from an empty list", () => {
    expect(choose([], [null])).toBeNull();
  });
});

describe("listWorkspaces", () => {
  beforeEach(() => GET.mockReset());

  it("follows every page", async () => {
    GET.mockResolvedValueOnce({ data: { items: [personal], next_cursor: "c1" }, response: {} });
    GET.mockResolvedValueOnce({ data: { items: [studio], next_cursor: null }, response: {} });
    expect(await listWorkspaces(here)).toEqual([personal, studio]);
    expect(GET.mock.calls[1]?.[1]).toEqual({ params: { query: { limit: 100, cursor: "c1" } } });
  });

  it("stops when the same page comes back", async () => {
    GET.mockResolvedValue({ data: { items: [personal], next_cursor: "same" }, response: {} });
    await expect(listWorkspaces(here)).rejects.toMatchObject({ status: 503 });
    expect(GET).toHaveBeenCalledTimes(2);
  });

  it("sends a visitor whose session ended to sign-in", async () => {
    GET.mockResolvedValue({ data: undefined, response: { status: 401 } });
    await expect(listWorkspaces(here)).rejects.toMatchObject({ location: "/signin?next=%2F" });
  });
});

describe("preferredFor", () => {
  beforeEach(() => forget());

  it("prefers this tab's choice for the same user", () => {
    select(studio, "usr_a");
    expect(preferredFor("usr_a")[0]).toBe("wsp_s");
  });

  it("ignores another user's choice", () => {
    select(studio, "usr_a");
    expect(preferredFor("usr_b")[0]).toBeNull();
  });
});
