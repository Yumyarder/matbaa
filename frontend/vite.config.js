import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    // `npm run build` drops the production bundle straight into the
    // backend, where main.py mounts it as static files. This is what
    // makes a single `python run_server.py` (or the packaged .exe) serve
    // both the API and the UI from one process/port.
    outDir: path.resolve(__dirname, "../backend/app/frontend_dist"),
    emptyOutDir: true,
  },
});
