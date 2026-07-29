import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: "../codex_task_monitor/web/static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    css: false,
  },
})
