import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server is server.mjs (Vite in middleware mode); it sets the HMR port and proxies /api and /flower.
export default defineConfig(({ command, isSsrBuild }) => ({
  plugins: [react()],
  ssr: {
    noExternal: command === "build" && isSsrBuild ? true : [],
  },
}));
