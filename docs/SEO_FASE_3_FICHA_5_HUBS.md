# Plan de la fase 3: ficha de ítem con los 5 hubs

Estado: **plan, sin implementar** (2026-11-18). Contexto y fases 0-2 en `docs/SEO_MERCADOS.md`.
Motivo de adelantarla: en Search Console (28 días hasta el 2026-11-16) casi todo el tráfico entra por
fichas de ítem concretas (consultas como "afterburner market" o "titanium carbide price"), y los 895 + 216
URLs "descubiertas/rastreadas sin indexar" indican que Google no ve suficiente valor propio en cada ficha.
Dar a cada ficha un dato que no tienen las demás páginas (su precio y ROI en los cinco hubs) ataca las dos cosas.

## Objetivo
Que `/items/{id}-{slug}` pase de "ficha de Jita" a "ficha del ítem en los cinco hubs", sin crear URLs nuevas
y sin multiplicar el índice por 5.

## Estado actual (leído en `backend/api/pages.py::item_page`)
- Una consulta de `item_status` solo para `DEFAULT_MARKET` (Jita); título, h1, descripción y resumen dicen "Jita".
- Se indexa solo si el estado en Jita es `POTENCIAL` o `POTENCIAL_SIN_ORDENES` (≈ 2.081 ítems); el resto sale `noindex, follow`.
- Las portadas de mercado (`/amarr/` etc.) muestran el nombre de los ítems **sin enlace** salvo en Jita.
- `item_status` ya tiene una fila por (mercado, ítem) con precios, ROI, spread, operaciones/día, estado y tendencia 7 d:
  no hacen falta tablas ni cambios de motor.

## Diseño
1. **Misma URL, más contenido.** Sección nueva "Prices across the 5 trade hubs" con una tabla de hasta 5 filas:
   hub, mejor compra, mejor venta, spread bruto, ROI después de comisiones, operaciones/día (7 d), clasificación
   y tendencia 7 d. Los hubs sin datos frescos (> 1 h) o sin fila del ítem muestran "—".
2. **Frase de resumen generada (GEO):** una o dos frases con cifras reales, por ejemplo "Today the highest ROI for
   Tritanium is in Amarr (14.2 %), and the most traded hub is Jita (1,240 trades/day)." Es el texto que más
   probablemente cite un asistente de IA.
3. **Título, h1 y descripción neutros:** "{ítem}: price and ROI in EVE's 5 trade hubs | EveMarket", h1 "{ítem} — station
   trading in EVE's 5 trade hubs". Jita queda como referencia en la tabla, ya no en el título.
4. **Enlazado:** el nombre de cada ítem en las portadas `/amarr/`, `/dodixie/`, `/rens/`, `/hek/` pasa a enlazar a su
   ficha; la ficha enlaza de vuelta a las 5 portadas de mercado (ya están en el pie) y a los ítems relacionados.
5. **Criterio de indexación:** hoy "Potencial en Jita". Opción B: "Potencial en **cualquier** hub" (la ficha existe
   para ítems que solo rinden en Amarr, por ejemplo). Decidir tras medir (paso 0).
6. **Sitemap:** mismas URLs (o la unión de la opción B); `lastmod` = última evaluación entre los hubs.
7. **JSON-LD:** se mantiene `WebPage` + `BreadcrumbList`. No se añade `Product` ni `Offer` (no se vende nada) para no
   provocar datos estructurados engañosos.
8. **Brecha de precio entre hubs: opcional y con cuidado.** Mostrar "precio de venta en A frente a compra en B" es el
   germen del arbitraje, pero ignora transporte, riesgo y volumen real. Si se incluye, va rotulado como informativo
   ("no incluye transporte ni riesgo; no es asesoramiento") y sin ordenar ni sugerir rutas. Si hay dudas, se deja para
   una fase de arbitraje propia.

## Pasos
0. **Medir (sin código):** con una consulta sobre `item_status`, calcular cuántos ítems son candidatos en al menos un
   hub (unión) frente a los ≈ 2.081 de Jita (por mercado hoy: Jita 2.081, Amarr 987, Dodixie 524, Rens 316, Hek 303,
   máximo teórico 4.211) y cuántos tienen datos frescos en 3 o más hubs. Resultado: decidir opción A o B del punto 5.
**Resultado del paso 0 (producción, 2026-11-18 17:30 UTC; las cifras varían en cada ciclo):**

| Medida | Ítems |
|---|---|
| Candidatos en Jita (opción A) | 2.307 |
| Unión: candidatos en algún hub (opción B) | 3.461 |
| Candidatos solo fuera de Jita (lo que añadiría la opción B) | 1.154 |
| Candidatos en 2 o más hubs / 3 o más / los 5 | 894 / 317 / 9 |
| Candidatos de Jita con fila en 3 o más hubs / en los 5 | 1.646 (71 %) / 789 (34 %) |
| Unión con fila en 3 o más hubs | 2.781 |
| Filas de candidatos con datos de más de 1 h (Jita / Amarr / Dodixie / Hek / Rens) | 20 / 1 / 2 / 4 / 0 |

Lectura: los datos viejos casi no afectan a los candidatos (las 995 filas viejas son sobre todo ítems descartados de
Jita), así que los "—" por antigüedad serán raros; y solo un tercio de los candidatos de Jita tiene fila en los 5 hubs,
por lo que la tabla tendrá a menudo 3 o 4 filas. **Recomendación: opción A primero** (misma cantidad de URLs, sin crecer el
índice mientras hay ~1.100 URLs sin indexar) y ampliar a la opción B (+1.154, dentro del techo de ~4.000-4.500) cuando las
fichas actuales se indexen mejor.

1. **Backend:** una función que, dado un `type_id`, lee `item_status` de todos los mercados activos (la clave primaria
   `(market_id, type_id)` la hace barata) y devuelve las filas ordenadas por `sort_order`; plantilla de la tabla y de la
   frase de resumen en `pages.py`.
2. **Copy:** título, h1, descripción y `STATUS_BLURB` neutros; `/items` (índice) también deja de decir "Jita".
3. **Enlaces desde las portadas de mercado:** pasar a enlazar los nombres de la tabla a la ficha en todos los hubs.
4. **Tests:** tabla con 5 hubs; hub inactivo no aparece; hub sin fila del ítem o con datos viejos muestra "—"; frase de
   resumen elige el hub correcto; ítem sin fila en Jita sigue funcionando (según la opción); canonical y robots; escapado de HTML.
5. **Despliegue y revisión:** PR con los 3 checks, revisión visual de 3 fichas (con y sin datos en todos los hubs),
   pedir indexación de 5 fichas representativas en Search Console y Bing, y reenviar el sitemap si cambia.

## Riesgos
- **Fichas casi iguales entre sí:** mitigado porque la tabla y la frase son datos propios de cada ítem y cambian con él.
- **Datos viejos en HTML:** mostrar la hora de la última evaluación por hub y "—" si pasa de 1 h.
- **Carga de rastreo:** una consulta ligera por ficha con `Cache-Control` de 1 h; vigilar la carga de la API tras el despliegue.
- **Brecha entre hubs mal interpretada:** ver punto 8; por defecto no se incluye.

## Métricas de éxito (comparar con la línea base de `docs/SEO_MERCADOS.md`)
Páginas indexadas y "sin indexar" en Search Console; impresiones y clics de las fichas de ítem; consultas nuevas
que comparan hubs; en Bing, URLs indexadas. Revisar a las 4 semanas del despliegue.

## Esfuerzo y relación con la fase 2
Medio: un PR de backend con tests (sin tocar motor ni base de datos). Si la fase 3 funciona, la fase 2 (fichas por mercado)
se reduce al top por mercado o no se hace, porque las fichas ya cubren los 5 hubs.

## Fuera de alcance
Traducir las fichas (siguen en inglés); rutas de transporte o arbitraje; nuevas tablas o cambios de motor.
