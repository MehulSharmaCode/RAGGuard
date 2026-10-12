/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true },
  build: {
    // The lazily loaded 3D chunk (three.js + React Three Fiber, ~915 kB min / ~245 kB gzip) is the
    // largest; three.js cannot be tree-shaken under R3F. The limit flags growth beyond that.
    chunkSizeWarningLimit: 1000,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // Only the token file is processed (the contrast test reads it); other CSS is stubbed.
    css: { include: [/tokens\.css/] },
    restoreMocks: true,
    unstubGlobals: true,
  },
});
