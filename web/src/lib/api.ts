import { createFrameGenClient, type components } from "@framegen/sdk";

/**
 * The one client for the API (DESIGN.md section 9.1: the web app uses only the public API).
 * The session cookie travels with every request, as the API is on the same site.
 */
export const api = createFrameGenClient({
  baseUrl: typeof window === "undefined" ? "http://localhost" : window.location.origin,
});

export type User = components["schemas"]["User"];
export type ApiErrorBody = components["schemas"]["ErrorResponse"];
