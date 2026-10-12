import { beforeEach, describe, expect, it, vi } from "vitest";

const GET = vi.fn();
vi.mock("./api.ts", () => ({ api: { GET } }));
vi.mock("$app/paths", () => ({ resolve: (path: string) => path }));

const { afterSignIn, currentUser, requireUser } = await import("./session.ts");

const user = { id: "usr_1", email: "a@example.com", name: "A", language: "en" };
const here = new URL("http://site/projects?page=2");

describe("session", () => {
  beforeEach(() => GET.mockReset());

  it("returns the signed-in user", async () => {
    GET.mockResolvedValue({ data: user, response: { status: 200 } });
    expect(await requireUser(here)).toEqual(user);
  });

  it("sends a signed-out visitor to sign-in, to come back afterwards", async () => {
    GET.mockResolvedValue({ data: undefined, response: { status: 401 } });
    expect(await currentUser()).toBeNull();
    await expect(requireUser(here)).rejects.toMatchObject({
      status: 307,
      location: "/signin?next=%2Fprojects%3Fpage%3D2",
    });
  });

  it("does not take a broken API for being signed out", async () => {
    GET.mockResolvedValue({ data: undefined, response: { status: 503 } });
    await expect(currentUser()).rejects.toThrow("503");
  });
});

describe("afterSignIn", () => {
  it("goes back to a page of this site", () => {
    expect(afterSignIn("/projects?page=2")).toBe("/projects?page=2");
  });

  it("never leaves the site", () => {
    for (const next of ["//evil.example", "https://evil.example", "javascript:x", null, ""]) {
      expect(afterSignIn(next), String(next)).toBe("/");
    }
  });
});
