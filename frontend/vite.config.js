import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/airport':     'http://localhost:8000',
      '/airports':    'http://localhost:8000',
      '/leaderboard': 'http://localhost:8000',
      '/ingest':      'http://localhost:8000',
      '/health':      'http://localhost:8000',
      '/map-data':    'http://localhost:8000',
    },
  },
})
