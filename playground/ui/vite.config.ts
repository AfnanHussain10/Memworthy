import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds into ../web, which the FastAPI backend serves. `npm run dev` proxies the API.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../web", emptyOutDir: true, chunkSizeWarningLimit: 700 },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8765", "/results": "http://localhost:8765" },
  },
});
