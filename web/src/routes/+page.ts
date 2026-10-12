import { requireUser } from "#lib/session.ts";
import { listWorkspaces } from "#lib/workspace.svelte.ts";

import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ url }) => {
  const [user, workspaces] = await Promise.all([requireUser(url), listWorkspaces(url)]);
  return { user, workspaces };
};
