import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { wayfinderPlugin } from "./plugin.ts";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "../..");

export default defineConfig({
  plugins: [react(), wayfinderPlugin(repoRoot)],
  server: {
    host: true,
    port: 5175,
    strictPort: true,
    fs: { allow: [repoRoot] },
    watch: {
      ignored: ["**/node_modules/**", "**/.git/**"],
    },
  },
});
