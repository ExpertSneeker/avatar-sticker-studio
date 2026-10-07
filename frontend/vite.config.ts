import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // /media serves the public catalog images (backend/app/guest_media.py); both go to the same FastAPI app.
  server: { proxy: Object.fromEntries(['/api', '/media'].map(path => [path, { target: process.env.STUDIO_API_PROXY || 'http://127.0.0.1:8000', changeOrigin: false }])) },
})
