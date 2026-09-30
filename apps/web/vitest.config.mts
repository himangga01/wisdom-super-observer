import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";
export default defineConfig({ resolve: { alias: { "server-only": fileURLToPath(new URL("./tests/server-only.ts", import.meta.url)) } } });
