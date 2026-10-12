import { redirect } from "@sveltejs/kit";

import { resolve } from "$app/paths";

import { api, type User } from "./api.ts";

/** The signed-in user, or null when nobody is signed in. Other failures are thrown. */
export async function currentUser(): Promise<User | null> {
  const { data, response } = await api.GET("/v1/me");
  if (data) return data;
  if (response.status === 401) return null;
  throw new Error(`the API answered ${response.status}`);
}

/**
 * For pages that need a session: sends signed-out visitors to sign-in, which brings them
 * back to `here` afterwards.
 */
export async function requireUser(here: URL): Promise<User> {
  const user = await currentUser();
  if (user === null) {
    const next = encodeURIComponent(here.pathname + here.search);
    redirect(307, `${resolve("/signin")}?next=${next}`);
  }
  return user;
}

/** Where to go after signing in: `next` if it is a page of this site, else home. */
export function afterSignIn(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : resolve("/");
}
