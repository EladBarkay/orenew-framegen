import { writePsdUint8Array, type Psd } from "ag-psd";

export interface DocumentRequest {
  width: number;
  height: number;
}

/** Checks a request body; returns an error code or the parsed request. */
export function parseDocumentRequest(body: unknown): DocumentRequest | { error: string } {
  if (typeof body !== "object" || body === null) return { error: "invalid_body" };
  const { width, height } = body as Record<string, unknown>;
  const valid = (n: unknown): n is number =>
    Number.isInteger(n) && (n as number) > 0 && (n as number) <= 30000;
  if (!valid(width) || !valid(height)) return { error: "invalid_size" };
  return { width, height };
}

/**
 * Writes an empty PSD of the given size. Layers, including text layers, come in T-41;
 * this proves the service and ag-psd work end to end.
 */
export function writeDocument(request: DocumentRequest): Uint8Array {
  const psd: Psd = { width: request.width, height: request.height, children: [] };
  return writePsdUint8Array(psd);
}
