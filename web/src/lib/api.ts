import { createFrameGenClient, type components } from "@framegen/sdk";

/**
 * The one client for the API (DESIGN.md section 9.1: the web app uses only the public API).
 * Paths are relative to the page, as the API is on the same site, so the session cookie
 * travels with every request.
 */
export const api = createFrameGenClient({ baseUrl: "" });

export type User = components["schemas"]["User"];
export type ApiErrorBody = components["schemas"]["ErrorResponse"];
