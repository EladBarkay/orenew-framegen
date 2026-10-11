import type { components } from "@framegen/sdk";

export type ApiState = { kind: "checking" } | { kind: "up"; version: string } | { kind: "down" };

/** Turns the result of the health call into what the page shows. */
export function apiState(health: components["schemas"]["Health"] | undefined): ApiState {
  if (health?.status === "ok") return { kind: "up", version: health.version };
  return { kind: "down" };
}
