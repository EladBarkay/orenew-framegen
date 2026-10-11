import createClient, { type ClientOptions } from "openapi-fetch";

import type { paths } from "./schema.js";

export type { components, paths } from "./schema.js";

/** A typed client for the FrameGen API. `baseUrl` is the server root, without `/v1`. */
export function createFrameGenClient(options: ClientOptions = {}) {
  return createClient<paths>(options);
}

export type FrameGenClient = ReturnType<typeof createFrameGenClient>;
