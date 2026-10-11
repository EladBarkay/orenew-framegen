import adapter from "@sveltejs/adapter-static";
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    sveltekit({
      // A static single-page app: all work happens in the API (DESIGN.md section 9.1).
      adapter: adapter({ fallback: "index.html" }),
    }),
  ],
  server: {
    proxy: { "/v1": process.env.FRAMEGEN_API_URL ?? "http://localhost:8000" },
  },
  test: { include: ["src/**/*.test.ts"] },
});
