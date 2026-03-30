import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  /* Same order as `development`: React first, then Tailwind (content scan + transforms). */
  plugins: [react(), tailwindcss()],

  server: {
    watch: {
      ignored: ['**/node_modules/**', '**/.venv/**', '**/dist/**', '**/logs/**', '**/media/**']
    }
  },
})
