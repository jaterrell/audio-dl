import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { TanStackRouterVite } from "@tanstack/router-vite-plugin";

export default defineConfig({
  plugins: [TanStackRouterVite(), react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:9000",
      "/jobs": { target: "http://localhost:9000", changeOrigin: true, ws: false },
      "/thumbs": "http://localhost:9000",
      "/reveal": "http://localhost:9000",
    },
  },
  resolve: { alias: { "@": "/src" } },
  // @ts-ignore — vitest config extends vite config
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
  },
});
