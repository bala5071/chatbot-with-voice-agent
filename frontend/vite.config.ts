/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Where the chat backend listens while developing. `npm run dev` proxies /api to it.
const backend = process.env.CHAT_BACKEND_URL ?? "http://127.0.0.1:8100";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    proxy: { "/api": backend },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
