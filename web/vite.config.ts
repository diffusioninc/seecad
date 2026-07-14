import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  build: {
    // The WebGL inspection rig is intentionally lazy-loaded as its own specialized chunk.
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      input: {
        workbench: resolve(webRoot, "index.html"),
        importedAssembly: resolve(webRoot, "import.html"),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
