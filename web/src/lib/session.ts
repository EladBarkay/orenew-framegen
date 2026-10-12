import { error, redirect } from "@sveltejs/kit";

import { resolve } from "$app/paths";

import { api, type User } from "./api.ts";

/**
 * The signed-in user, or null when nobody is signed in. When the API cannot be reached
 * (no answer, or Caddy answers 502/504) this fails with status 502; when it answers with
 * another error, with 503. The error page tells the two apart.
 */
export async function currentUser(ask = () => api.GET("/v1/me")): Promise<User | null> {
  let answer;
  try {
    answer = await ask();
  } catch {
    error(502, "no answer");
  }
  const { data, response } = answer;
  if (data) return data;
  if (response.status === 401) return null;
  error([502, 504].includes(response.status) ? 502 : 503, `the API answered ${response.status}`);
}

/**
 * For pages that need a session: sends signed-out visitors to sign-in, which brings them
 * back to `here` afterwards.
 */
export async function requireUser(here: URL): Promise<User> {
  const user = await currentUser();
  if (user === null) redirect(307, withNext(resolve("/signin"), here.pathname + here.search));
  return user;
}

/** `path` with `?next=` set, when there is a page to go back to. */
export function withNext(path: string, next: string | null): string {
  return next ? `${path}?next=${encodeURIComponent(next)}` : path;
}

/**
 * Where to go after signing in: `next` if it is a page of this site, else home. `next` is
 * resolved the way the browser would resolve it, so tricks such as "/\\evil.example"
 * cannot lead off the site.
 */
export function afterSignIn(next: string | null, site: { href: string; origin: string }): string {
  if (next) {
    const target = new URL(next, site.href);
    if (target.origin === site.origin) return target.pathname + target.search + target.hash;
  }
  return resolve("/");
}
