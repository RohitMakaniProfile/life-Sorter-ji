import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/**
 * Vite plugin: convert POST requests on SPA routes to GET.
 *
 * Payment gateways (HDFC SmartGateway / JusPay) POST to the return_url
 * after payment. Vite's dev server only serves index.html for GET requests
 * (SPA history-api-fallback). This plugin intercepts non-GET requests that
 * don't match static files or API routes, rewrites them as GET, and lets
 * Vite's normal SPA fallback serve index.html.
 */
function postToGetFallback() {
  return {
    name: 'post-to-get-fallback',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (
          req.method !== 'GET' &&
          req.method !== 'HEAD' &&
          !req.url.startsWith('/api') &&
          !req.url.includes('.')
        ) {
          req.method = 'GET'
        }
        next()
      })
    },
  }
}

export default defineConfig({
  /* Same order as `development`: React first, then Tailwind (content scan + transforms). */
  plugins: [postToGetFallback(), react(), tailwindcss()],

  server: {
    watch: {
      ignored: ['**/node_modules/**', '**/.venv/**', '**/dist/**', '**/logs/**', '**/media/**']
    }
  },
})
