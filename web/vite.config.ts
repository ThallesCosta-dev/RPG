import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// Em dev, o FastAPI roda em :8000 e o Vite faz proxy de API, WS, áudio e mapas.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/audio": "http://localhost:8000",
      "/mapas": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 700, // o chunk do pixi.js sozinho passa de 500 kB
    rollupOptions: {
      output: {
        manualChunks: {
          pixi: ["pixi.js"],
          react: ["react", "react-dom", "react-router-dom", "zustand"],
        },
      },
    },
  },
})
