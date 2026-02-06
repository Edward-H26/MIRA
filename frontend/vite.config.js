import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  publicDir: false,
  server: {
    open: true
  },
  build: {
    outDir: "../static",
    emptyOutDir: false,
    rollupOptions: {
      input: "./src/main.js",
      output: {
        entryFileNames: "js/main.js",
        assetFileNames: "css/[name][extname]"
      }
    }
  }
})
