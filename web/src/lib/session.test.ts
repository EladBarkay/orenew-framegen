import { beforeEach, describe, expect, it, vi } from "vitest";

const GET = vi.fn();
vi.mock("./api.ts", () => ({ api: { GET } }));

const { currentUser, requireUser } = await import("./session.ts");

const user = { id: "usr_1", email: "a@example.com", name: "A", language: "en" };

describe("session", () => {
  beforeEach(() => GET.mockReset());

  it("returns the signed-in user", async () => {
    GET.mockResolvedValue({ data: user, response: { status: 200 } });
    expect(await requireUser()).toEqual(user);
  });

  it("sends a signed-out visitor to sign-in", async () => {
    GET.mockResolvedValue({ data: undefined, response: { status: 401 } });
    expect(await currentUser()).toBeNull();
    await expect(requireUser()).rejects.toMatchObject({ status: 307, location: "/signin" });
  });

  it("does not take a broken API for being signed out", async () => {
    GET.mockResolvedValue({ data: undefined, response: { status: 503 } });
    await expect(currentUser()).rejects.toThrow("503");
  });
});
