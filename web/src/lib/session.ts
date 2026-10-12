import { redirect } from "@sveltejs/kit";

import { api, type User } from "./api.ts";

/** The signed-in user, or null when nobody is signed in. Other failures are thrown. */
export async function currentUser(): Promise<User | null> {
  const { data, response } = await api.GET("/v1/me");
  if (data) return data;
  if (response.status === 401) return null;
  throw new Error(`the API answered ${response.status}`);
}

/** For pages that need a session: sends signed-out visitors to sign-in. */
export async function requireUser(): Promise<User> {
  const user = await currentUser();
  if (user === null) redirect(307, "/signin");
  return user;
}
