# Plan de SEO y SEO para IA

Auditoría del 2026-11-03 sobre `https://evemarket-analyzer.online`. Objetivo: que el
Screener aparezca en las primeras búsquedas de Google/Bing y sea citado por asistentes
con IA. No hay garantía de posición: EVE es un nicho con competidores establecidos; este
plan mejora las probabilidades y deja medición para ajustar.

## Hallazgos que motivan el plan
| # | Hallazgo | Impacto |
|---|---|---|
| 1 | Una sola URL indexable: la app pinta los datos con JS desde `/api/` (bloqueado en `robots.txt`) | Muy alto |
| 2 | Idiomas por `?lang=` con el mismo `canonical`: Google los trata como una sola página | Alto |
| 3 | `http://` no redirige a `https://` (devuelve 200); `www` devuelve 404 | Medio |
| 4 | `/docs`, `/redoc` y `/openapi.json` públicos (documentan también rutas privadas) | Medio |
| 5 | `og:image` es un icono 512×512; `twitter:card` = `summary` | Medio |
| 6 | `manifest.json` en español; `/favicon.ico` da 404 | Bajo |
| 7 | `/assets/` con `max-age=14400` sin `immutable`; Google Fonts por `@import` bloqueante | Medio |
| 8 | Sin datos reales de rendimiento (PageSpeed sin cuota) ni de indexación (Search Console) | — |

## Fases
Responsable entre paréntesis (zonas del protocolo entre agentes: backend/ops vs. frontend/SEO).

### Fase 0 — Endurecimiento rápido (backend/ops)
- Cloudflare: "Always Use HTTPS" y redirección `www` → dominio sin `www`.
- Desactivar `/docs`, `/redoc`, `/openapi.json` (reactivables con `ENABLE_API_DOCS=1`).
- `Cache-Control: public, max-age=31536000, immutable` para `/assets/*` y `no-cache` para
  el HTML; `X-Robots-Tag: noindex` en `/api/*`.
- Criterio de éxito: `curl -I http://…` redirige a https; `/docs` da 404; cabeceras presentes.

### Fase 1 — Páginas indexables por ítem (backend)
- `GET /items/{type_id}-{slug}`: HTML generado en el servidor, en inglés, con título y
  descripción únicos, `<h1>`, tabla de precios (compra/venta), ROI, spread, volumen y
  operaciones por día, estado de clasificación, fecha de la última evaluación, JSON-LD
  (`WebPage` + `BreadcrumbList`) y `canonical` propio.
- `GET /items`: índice HTML con enlaces a los ítems POTENCIAL / POTENCIAL_SIN_ORDENES
  (hub de rastreo).
- `GET /sitemap.xml` dinámico: portada + variantes de idioma + ítems elegibles, con
  `lastmod` = última evaluación. Anula al `sitemap.xml` estático.
- Anti-contenido-fino: solo se indexan (`index,follow`) los ítems POTENCIAL y
  POTENCIAL_SIN_ORDENES (~1.350); el resto responde pero con `noindex`.
- Tests de rutas, escapado de HTML, 404 y sitemap.
- Criterio de éxito: las URLs responden 200 con el contenido en el HTML crudo (sin JS).

### Fase 2 — Frontend y contenido (otra sesión)
- Idiomas por ruta (`/es/`, `/de/`, `/fr/`, `/it/`) con `hreflang` y `canonical` propios.
- `og:image` 1200×630 + `twitter:card=summary_large_image`; manifest en inglés y
  localizado; `favicon.ico`; fuentes alojadas en el propio sitio.
- Enlazar `/items` desde la app y desde el `<noscript>`; actualizar `llms.txt`.

### Fase 3 — Señales externas (usuario)
- Alta en Google Search Console y Bing Webmaster Tools (verificación TXT en Cloudflare),
  envío del sitemap.
- Compartir en comunidades de EVE (r/Eve, foros, Discord, listas de herramientas).

### Fase 4 — Medición (todos)
- A las 2-4 semanas: consultas, impresiones, páginas indexadas y errores en Search Console;
  PageSpeed/Lighthouse cuando haya cuota. Ajustar qué ítems se indexan.

## Decisiones abiertas
- Si se permite a los rastreadores que entrenan modelos de IA (`robots.txt` hoy lo permite).
- `llms.txt` no tiene soporte oficial en los buscadores grandes: se mantiene por costo bajo,
  sin esperar efecto medible.
