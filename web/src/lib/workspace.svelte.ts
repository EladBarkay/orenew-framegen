/**
 * The workspace the user works in (DESIGN.md section 2): their personal one or a studio.
 * The choice is remembered in this browser, for each user; pages that work in a workspace
 * read `workspace.current`.
 */
import type { components } from "@framegen/sdk";

import { api } from "./api.ts";
import { errorKey } from "./errors.ts";
import type { MessageKey } from "./i18n.svelte.ts";
import { answerOf, failed } from "./session.ts";

export type Workspace = components["schemas"]["Workspace"];

const REMEMBERED = "framegen.workspace.";

/** The chosen workspace, and whose choice it is: it only counts for that user. */
export const workspace: { current: Workspace | null; userId: string | null } = $state({
  current: null,
  userId: null,
});

/** Every workspace the user belongs to, following the pages of the list. */
export async function listWorkspaces(here: URL): Promise<Workspace[]> {
  const all: Workspace[] = [];
  const seen: string[] = [];
  let cursor: string | undefined;
  do {
    const { data, response } = await answerOf(() =>
      api.GET("/v1/workspaces", { params: { query: { limit: 100, cursor } } }),
    );
    if (!data) failed(response.status, here);
    all.push(...data.items);
    cursor = data.next_cursor ?? undefined;
    if (cursor && seen.includes(cursor)) failed(500); // the same page again: stop, never loop
    if (cursor) seen.push(cursor);
  } while (cursor);
  return all;
}

/** The first of `preferred` the user still belongs to, else their personal workspace. */
export function choose(workspaces: Workspace[], preferred: (string | null)[]): Workspace | null {
  for (const id of preferred) {
    const found = workspaces.find((w) => w.id === id);
    if (found) return found;
  }
  return workspaces.find((w) => w.kind === "personal") ?? workspaces[0] ?? null;
}

export function remembered(userId: string): string | null {
  try {
    return localStorage.getItem(REMEMBERED + userId);
  } catch {
    return null; // storage blocked: choose afresh each visit
  }
}

export function select(chosen: Workspace, userId: string): void {
  workspace.current = chosen;
  workspace.userId = userId;
  try {
    localStorage.setItem(REMEMBERED + userId, chosen.id);
  } catch {
    // storage blocked: the choice lasts until the page is reloaded
  }
}

/** On signing out: nothing of this user's choice stays in memory for the next one. */
export function forget(): void {
  workspace.current = null;
  workspace.userId = null;
}

/** Whether two workspaces are the same and show the same details. */
export function same(a: Workspace, b: Workspace | null): boolean {
  return b !== null && a.id === b.id && a.name === b.name && a.kind === b.kind && a.role === b.role;
}

/** What to prefer for `userId`: their choice in this tab, then the one remembered. */
export function preferredFor(userId: string): (string | null)[] {
  const inMemory = workspace.userId === userId ? (workspace.current?.id ?? null) : null;
  return [inMemory, remembered(userId)];
}

/** Creates a studio, with the user as its owner; or says why it could not. */
export async function createStudio(name: string): Promise<Workspace | MessageKey> {
  try {
    const { data, error, response } = await api.POST("/v1/workspaces", { body: { name } });
    if (data) return data;
    // An answer with no readable body is "unknown", unless the API could not be reached.
    return errorKey([502, 504].includes(response.status) ? undefined : (error ?? {}));
  } catch {
    return errorKey(undefined);
  }
}
