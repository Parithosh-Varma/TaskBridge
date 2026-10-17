import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Portable static build: relative base so dist/ works on any host or subfolder.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: 'dist',
    assetsInlineLimit: 4096,
  },
})
