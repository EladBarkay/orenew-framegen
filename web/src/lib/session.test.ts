import { beforeEach, describe, expect, it, vi } from "vitest";

const GET = vi.fn();
vi.mock("./api.ts", () => ({ api: { GET } }));
vi.mock("$app/paths", () => ({ resolve: (path: string) => path }));
vi.mock("@sveltejs/kit", () => ({
  error: (status: number, message: string) => {
    throw { status, message };
  },
  redirect: (status: number, location: string) => {
    throw { status, location };
  },
}));

const { afterSignIn, currentUser, requireUser, withNext } = await import("./session.ts");

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
    GET.mockResolvedValue({ data: undefined, response: { status: 500 } });
    await expect(currentUser()).rejects.toMatchObject({ status: 503 });
  });

  it("tells an API that cannot be reached apart", async () => {
    GET.mockResolvedValue({ data: undefined, response: { status: 502 } });
    await expect(currentUser()).rejects.toMatchObject({ status: 502 });
  });

  it("takes no answer at all for an API that cannot be reached", async () => {
    const noAnswer = () => Promise.reject(new TypeError("Failed to fetch"));
    await expect(currentUser(noAnswer)).rejects.toMatchObject({ status: 502 });
  });
});

describe("afterSignIn", () => {
  const site = new URL("http://site/signin");

  it("goes back to a page of this site", () => {
    expect(afterSignIn("/projects?page=2", site)).toBe("/projects?page=2");
  });

  it("never leaves the site", () => {
    const tricks = [
      "//evil.example",
      "https://evil.example",
      "/\\evil.example",
      "/\t/evil.example",
      "javascript:x",
      null,
      "",
    ];
    for (const next of tricks) {
      expect(afterSignIn(next, site), String(next)).toBe("/");
    }
  });
});

describe("withNext", () => {
  it("carries the page to go back to", () => {
    expect(withNext("/signup", "/projects?page=2")).toBe("/signup?next=%2Fprojects%3Fpage%3D2");
    expect(withNext("/signup", null)).toBe("/signup");
  });
});
