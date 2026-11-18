# SEO por mercado: plan por fases

Estado al 2026-11-18. Las fases 0 y 1 están hechas (esta rama); las fases 2 y 3 quedan **sin iniciar**
hasta la evaluación del **2026-12-16** (4 semanas después del despliegue de la fase 1).

## Punto de partida (2026-11-18)

- Portadas por idioma: `/`, `/es/`, `/de/`, `/fr/`, `/it/` (generadas por el plugin `language-pages` de Vite).
- Páginas del backend (`backend/api/pages.py`): `/items`, `/items/{id}-{slug}` (solo Jita, solo estados
  `POTENCIAL` y `POTENCIAL_SIN_ORDENES`), `/privacy` y `/sitemap.xml` dinámico.
- **Sitemap en producción: 1.944 URLs** (5 portadas + `/items` + fichas de ítems de Jita).
- El selector de mercado de la SPA (`?market=`) no es una página para los buscadores: hasta la fase 1,
  Amarr, Dodixie, Rens y Hek no tenían ninguna URL propia.

## Fase 0: línea base (medir antes de cambiar)

Hecho por el sistema: el número de URLs del sitemap (arriba). Falta lo que solo da Search Console
(propiedad de dominio, ver `GUIA_SEARCH_CONSOLE_BING.txt`). **Anotar en la tabla antes de que Google
rastree las portadas nuevas** (o, como mucho, dentro de la primera semana tras el despliegue):

| Métrica (Search Console, últimos 28 días) | Valor |
|---|---|
| Impresiones totales | |
| Clics totales | |
| CTR medio | |
| Posición media | |
| Páginas indexadas (Indexación > Páginas) | |
| Páginas "Rastreada: actualmente sin indexar" | |
| Páginas "Descubierta: actualmente sin indexar" | |
| Consultas que contienen "amarr", "dodixie", "rens" o "hek" (impresiones) | |
| Bing Webmaster: URLs indexadas / clics | |

Además, justo después del despliegue: en Search Console, "Inspeccionar URL" → "Solicitar indexación"
de `/amarr/`, `/dodixie/`, `/rens/`, `/hek/`, `/jita/` y de `/es/amarr/`, y `python scripts/indexnow_submit.py`
(envía el sitemap completo a Bing/IndexNow).

## Fase 1: portadas por mercado (hecha)

- 25 URLs: `/{mercado}/` en inglés y `/{es|de|fr|it}/{mercado}/` (5 mercados × 5 idiomas), en
  `backend/api/market_pages.py`. Una ruta fija por mercado e idioma (un parámetro `/{market}/` capturaría `/es/`).
- Contenido propio en el HTML crudo: cifras del mercado (candidatos, ítems analizados, última
  actualización) y los 10 candidatos más operados (ROI, mejor compra/venta, operaciones/día).
- `hreflang` entre los 5 idiomas + `x-default`, canonical propio, JSON-LD (WebPage + BreadcrumbList),
  enlace al screener con `?market=`.
- `noindex, follow` si el mercado no tiene candidatos o sus datos tienen más de 1 h; 404 si el mercado
  no existe o no está activo.
- Entradas en `sitemap.xml` solo para mercados activos con candidatos.
- Las fichas de ítem de los mercados nuevos **no** existen todavía: en la tabla de esos mercados el nombre
  no es un enlace.

## Evaluación del 2026-12-16 (decidir fases 2 y 3)

Comparar con la línea base y mirar, para las 25 portadas nuevas:

1. ¿Están indexadas? (Search Console > Inspección de URL / Indexación). Si siguen en "Descubierta/Rastreada sin
   indexar" tras 4 semanas, **no** avanzar: primero mejorar contenido o enlazado de las portadas.
2. ¿Reciben impresiones y clics, y con qué consultas? (Rendimiento, filtrar por página `/amarr/` etc.)
3. ¿Subió el rastreo sin tirar la VM? (CPU/carga de la API y `docker logs` durante el rastreo.)
4. ¿Qué mercados rinden? Si Rens y Hek no tienen impresiones, su cupo en la fase 2 será mínimo.

Criterio sugerido: pasar a fase 2 o 3 solo si al menos 3 de las 5 portadas del idioma inglés están
indexadas y hay impresiones crecientes. Elegir la fase 3 antes que la 2 si las consultas comparan hubs
("jita vs amarr", "arbitraje") o si las fichas por ítem de los mercados menores salen como "rastreada sin indexar".

## Fase 2: fichas de ítem por mercado, acotadas (pendiente)

- Rutas `/{mercado}/items/{id}-{slug}` (y el índice `/{mercado}/items`) solo para los ~300–500 ítems más
  líquidos de cada mercado (ordenar por `avg_daily_order_count_7d`, estados indexables). El resto no se
  enlaza y sirve `noindex, follow`.
- Estimación: +1.200 a 2.000 URLs. Techo razonable del sitio: ~4.000–4.500 URLs indexables.
- Reutilizar la plantilla de `item_page` con `market_id` y el nombre del mercado en título, h1 y JSON-LD;
  `hreflang` no aplica (las fichas son solo en inglés).
- Riesgo principal: páginas casi iguales entre mercados (mismo ítem, otro mercado) → se mitiga con datos
  propios del mercado (precios, spread, operaciones, tendencia 7 d) y con el umbral de liquidez.
- Sitemap: entradas por mercado; si crece, dividir en un índice de sitemaps (`sitemap-jita.xml`, ...).
- Pruebas: 404 para mercado inactivo, `noindex` fuera del top, canonical por mercado, sin mezclar datos.

## Fase 3: ficha de ítem con los 5 hubs (pendiente)

**Desplegada (opción A) el 2026-11-18** (PR #69 y corrección de la frase de resumen en PR #70): sin URLs nuevas, la ficha
muestra la tabla de los 5 hubs. Enlaces internos y FAQ de la portada: PR #66 (2026-11-18). La evaluación del 2026-12-16
mide portadas de mercado, enlaces y fichas juntos; la opción B (+1.154 fichas) y la fase 2 siguen pendientes de esos datos.

**Plan detallado: `docs/SEO_FASE_3_FICHA_5_HUBS.md`.** Adelantada respecto a la fase 2 tras revisar Search Console (2026-11-18):
el tráfico llega por fichas de ítem y hay ~1.100 URLs sin indexar.

- Una página por ítem (las mismas ~1.800 de Jita o las del top de liquidez global) que compara en los
  cinco mercados: mejor compra/venta, spread, ROI, operaciones/día y tendencia 7 d. Contenido
  genuinamente distinto de las fichas por mercado, y base visual del futuro arbitraje.
- Ruta sugerida: `/items/{id}-{slug}` ya existente se amplía con una sección "En los 5 hubs" (no crea
  URLs nuevas) o `/compare/{id}-{slug}` si se prefiere separar. Decidir según la evaluación.
- Si se hace la fase 3 primero, la fase 2 puede quedar reducida al top 100 por mercado o no hacerse.
- Aviso de producto: es una comparación informativa de precios (no es asesoramiento ni un plan de ruta).
- Pruebas: mercados inactivos no aparecen, ítem sin datos en algún hub muestra "—", datos frescos.

## Fase 4: contenido y enlazado (pendiente, opcional)

Guías cortas ("qué es el station trading en Amarr", "diferencias entre hubs"), enlaces internos entre
mercados y desde las fichas, y actualización de `llms.txt`. Solo si las fases 1–3 muestran tracción.

## Notas operativas

- Los textos de las portadas viven en `T` de `backend/api/market_pages.py` (5 idiomas); la cabecera y el
  pie localizados, en `T[lang]["chrome"]`. Las fichas de ítem y `/items` siguen en inglés.
- Una ruta por mercado se genera de `MARKETS_SEED` (`storage/db.py`): un hub nuevo se añade ahí y aparece
  solo, sin tocar rutas.
- No se indexa contenido vacío o viejo: el criterio está en `_render` (`MAX_AGE`, candidatos > 0).
