import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Fonts served from this site (no request to Google Fonts, which blocked the first render).
import '@fontsource/space-grotesk/latin-500.css'
import '@fontsource/space-grotesk/latin-600.css'
import '@fontsource/space-grotesk/latin-700.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'
import '@fontsource/ibm-plex-mono/latin-600.css'
import '@fontsource/ibm-plex-mono/latin-700.css'
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
