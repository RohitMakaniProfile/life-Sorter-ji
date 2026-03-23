import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

const isPhase2Path = window.location.pathname === '/phase2' || window.location.pathname.startsWith('/phase2/');

async function bootstrap() {
  if (isPhase2Path) {
    const { default: Phase2App } = await import('./Phase2App.jsx')
    createRoot(document.getElementById('root')).render(
      <StrictMode>
        <Phase2App />
      </StrictMode>,
    )
    return
  }

  await import('./index.css')
  const { default: App } = await import('./App.jsx')
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void bootstrap()
