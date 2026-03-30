import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],

  server: {
    proxy: {
      // Send *all* API calls to FastAPI
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
    watch: {
      ignored: ['**/node_modules/**', '**/.venv/**', '**/dist/**', '**/logs/**', '**/media/**']
    }
  },
})