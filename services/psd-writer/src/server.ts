import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";

import { parseDocumentRequest, writeDocument } from "./psd.js";

const MAX_BODY_BYTES = 1024 * 1024;

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > MAX_BODY_BYTES) throw new Error("body_too_large");
    chunks.push(chunk as Buffer);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  if (req.method === "GET" && req.url === "/health") {
    sendJson(res, 200, { status: "ok" });
    return;
  }
  if (req.method === "POST" && req.url === "/v1/documents") {
    let body: unknown;
    try {
      body = await readJson(req);
    } catch {
      sendJson(res, 400, { error: { code: "invalid_body" } });
      return;
    }
    const request = parseDocumentRequest(body);
    if ("error" in request) {
      sendJson(res, 400, { error: { code: request.error } });
      return;
    }
    const psd = writeDocument(request);
    res.writeHead(200, { "content-type": "image/vnd.adobe.photoshop" });
    res.end(psd);
    return;
  }
  sendJson(res, 404, { error: { code: "not_found" } });
}

export function createPsdWriterServer(): Server {
  return createServer((req, res) => {
    handle(req, res).catch(() => sendJson(res, 500, { error: { code: "internal" } }));
  });
}
