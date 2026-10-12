/**
 * Turns API error codes into messages people can read (DESIGN.md D7: the API sends codes,
 * never text). Codes without a message of their own get the general one.
 */
import type { ApiErrorBody } from "./api.ts";
import type { MessageKey } from "./i18n.svelte.ts";

const MESSAGES: Record<string, MessageKey> = {
  invalid_credentials: "error.invalid_credentials",
  email_taken: "error.email_taken",
  validation_failed: "error.validation_failed",
  cross_site_request: "error.cross_site_request",
  unauthenticated: "error.unauthenticated",
};

/** The message key for an API error answer, or for a request that got no answer. */
export function errorKey(error: unknown): MessageKey {
  if (error === undefined) return "error.network";
  const code = (error as Partial<ApiErrorBody>)?.error?.code;
  return (code && MESSAGES[code]) || "error.unknown";
}
