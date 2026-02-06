import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  publicDir: false,
  server: {
    open: true
  },
  build: {
    outDir: "static/dist",
    emptyOutDir: true,
    rollupOptions: {
      input: "src/main.js",
      output: {
        entryFileNames: "main.js",
        assetFileNames: "[name][extname]"
      }
    }
  }
})
