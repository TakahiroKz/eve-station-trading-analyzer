import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { I18nProvider } from './i18n/I18nProvider.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <App />
    </I18nProvider>
  </StrictMode>,
)

// Solo en producción: en `npm run dev` el service worker cachea el bundle de Vite y
// sirve código viejo después de cada reinicio del servidor (causó una sesión entera
// de "el frontend no carga nada" hasta encontrar que era caché, no un bug real).
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((err) => {
      console.error('SW registration failed', err)
    })
  })
}
