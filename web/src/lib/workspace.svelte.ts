/**
 * The workspace the user works in (DESIGN.md section 2): their personal one or a studio.
 * The choice is remembered in this browser; pages that work in a workspace read
 * `workspace.current`.
 */
import { api, type ApiErrorBody } from "./api.ts";
import type { components } from "@framegen/sdk";

export type Workspace = components["schemas"]["Workspace"];

const REMEMBERED = "framegen.workspace";

export const workspace: { current: Workspace | null } = $state({ current: null });

/** Every workspace the user belongs to, following the pages of the list. */
export async function listWorkspaces(): Promise<Workspace[]> {
  const all: Workspace[] = [];
  let cursor: string | undefined;
  do {
    const { data, response } = await api.GET("/v1/workspaces", {
      params: { query: { limit: 100, cursor } },
    });
    if (!data) throw new Error(`the API answered ${response.status}`);
    all.push(...data.items);
    cursor = data.next_cursor ?? undefined;
  } while (cursor);
  return all;
}

/** The remembered workspace if the user still belongs to it, else the personal one. */
export function choose(workspaces: Workspace[], remembered: string | null): Workspace | null {
  return (
    workspaces.find((w) => w.id === remembered) ??
    workspaces.find((w) => w.kind === "personal") ??
    workspaces[0] ??
    null
  );
}

export function remembered(): string | null {
  try {
    return localStorage.getItem(REMEMBERED);
  } catch {
    return null; // storage blocked: choose afresh each visit
  }
}

export function select(chosen: Workspace): void {
  workspace.current = chosen;
  try {
    localStorage.setItem(REMEMBERED, chosen.id);
  } catch {
    // storage blocked: the choice lasts until the page is reloaded
  }
}

/** Creates a studio, with the user as its owner. */
export async function createStudio(name: string): Promise<Workspace | ApiErrorBody | undefined> {
  const { data, error } = await api.POST("/v1/workspaces", { body: { name } });
  return data ?? error;
}
