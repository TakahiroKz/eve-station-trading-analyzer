# Puntaje de oportunidad (0-100) — fase 1

Motor determinista y explicable que **complementa** a los estados (`POTENCIAL`, `POTENCIAL_SIN_ORDENES`,
`EN_OBSERVACION`, `DESCARTADO`): los estados no cambian; el puntaje responde "¿cuánto mejor es esta operación
que otra?". Sin IA. Mismos datos + misma configuración ⇒ mismo resultado.

- Cálculo: `analytics/scoring.py` (factores y total) y `analytics/opportunity.py` (filtros duros, elegibilidad,
  recomendación, códigos de motivo). `evaluate_item()` es el único punto de cálculo: lo usa el ciclo de mercado
  (`scheduler/run.py::screen_opportunities`, que guarda el resultado en `item_status`) y la API del detalle.
- Persistencia: columnas `score`, `score_class`, `eligibility`, `recommendation`, `score_version`, `score_inputs`
  en `item_status` (una fila vigente por mercado e ítem; no hay historial por ciclo para no inflar la base).
  `score_inputs` guarda solo lo que no está ya en la fila (volatilidad, antigüedad del dato, coherencia de
  precios); la explicación completa se recalcula al consultar el detalle.
- Versión: `score_version` = versión del algoritmo + huella de la configuración (cambia al tocar pesos o límites
  en Ajustes → categoría «Puntaje»). Si cambia entre ciclos, el detalle marca `config_changed`.

## Factores (pesos iniciales, configurables; se normalizan para sumar 1)

| Factor | Peso | Qué mide | Curva (resumen) |
|---|---|---|---|
| Rentabilidad neta | 25 | ROI neto | 100 entre 20 % y 40 %; baja desde el 60 % (45 a 100 %, 0 a 300 %) |
| Liquidez | 20 | posición de referencia / volumen diario (30 d) | 95 con < 10 %; 40 con 50 %; 0 con ≥ 200 % |
| Volumen negociado | 15 | ISK negociados al día (7 d) | 0 a 1 M, 60 a 100 M, 100 a 10 000 M |
| Libro y actividad | 15 | operaciones/día (7 d); libro fino (< 3 órdenes en un lado) = ×0,5 | 20 con 3, 60 con 10, 90 con 30 |
| Estabilidad | 15 | volatilidad (CV 30 d) y volumen 7 d / 30 d | CV ≤ 5 % = 100; 40 % = 0 |
| Eficiencia del capital | 10 | ROI diario = ROI (máx. 60 %) / días de rotación | 100 con 5 % diario |

Capital de referencia: 1 000 M ISK × 10 % por posición = 100 M ISK (`score_reference_capital` y
`position_size_pct_wallet`). Días de rotación = cantidad / (volumen 7 d × participación capturable 10 %); la
participación capturable es un supuesto, no un dato observado.

Topes: `DESCARTADO` ≤ 29; ROI neto > 100 % (atípico, típico de libros finos) ≤ 64. Bandas: ≥ 90 EXCELLENT,
80-89 HIGH, 65-79 MODERATE, 50-64 LOW, < 50 DISCARDED.

## Elegibilidad y recomendación

Filtros duros (cualquiera incumplido ⇒ `NO_ELIGIBLE`, aunque el puntaje sea alto): estado no descartado, precios
coherentes con el histórico, órdenes válidas en ambos lados, beneficio neto positivo, datos frescos (≤ 30 min),
volumen mínimo (el mismo de `classify`), beneficio neto mínimo de la posición de referencia, riesgo ≤ 60
(riesgo = 100 − estabilidad). Con datos viejos la acción es `WAIT`; con otro filtro incumplido, `REJECT`.

`RECOMMENDED` (`BUY_CANDIDATE`): pasa los filtros y además puntaje ≥ 65, ROI ≥ 5 %, liquidez ≥ 60 y rotación
≤ 7 días. Si no, `ELIGIBLE` / `WAIT` con los códigos que faltan y **qué tendría que cambiar** (valor actual y
umbral). Son evaluaciones del motor, no órdenes; `HOLD` y `SELL_CANDIDATE` necesitan las posiciones del usuario y
quedan para otra fase.

## API (pública, solo lectura)

- `GET /api/items`: campos `score`, `score_class`, `eligibility`, `recommendation`; filtros `min_score`,
  `score_class`, `eligibility`, `recommendation`; orden `sort=score` (sin puntaje siempre al final).
- `GET /api/items/{id}`: `assessment` con factores (puntos / máximo / valor / frase), topes, filtros pasados y
  fallados, códigos de motivo, `to_change` y la posición de referencia.

## Calibración (2026-11-19)

Sobre 42.926 ítems reales de los cinco mercados (exportados de `item_status` en la VM, solo lectura): con el capital de referencia, el
puntaje medio por estado fue POTENCIAL 64, POTENCIAL_SIN_ORDENES 56, EN_OBSERVACION 49, DESCARTADO 18; 484 ítems
`BUY_CANDIDATE` (457 de los 1.649 POTENCIAL), ninguno con ROI > 100 %.

## Pendiente (fases siguientes)

Profundidad de libro y competencia (fase 2), capital del usuario por petición (fase 3), interfaz con la explicación
(fase 4); mercados por estación, comisiones por habilidades, HOLD/SELL y arbitraje.

## Interfaz (fase 4)

- Tabla del Screener: columna **Puntaje** (ordenable; en pantallas estrechas el chip va junto a las operaciones/día) con chip de color por banda; el orden por defecto no cambia.
- Filtros: **Puntaje mínimo** y **Elegibilidad** (Recomendado / Elegible / No elegible); opción de orden "Puntaje".
- Detalle del ítem: panel **¿Por qué este puntaje?** con el total, la banda, la elegibilidad y la acción del motor, una barra por factor (puntos / máximo, la cifra medida y su frase), los topes aplicados, los filtros que lo bloquean, las condiciones y "qué tendría que cambiar".
- Todo se calcula en el backend. La API envía códigos estables y cifras (`code`, `metrics`, códigos de filtros y motivos) y la web los traduce a los cinco idiomas (`frontend/app/src/ScorePanel.tsx`, claves `score.*`); un test (`tests/test_score_i18n.py`) comprueba que cada código tiene texto en en/es/de/fr/it.

## Profundidad del libro (fase 2, algoritmo 1.1.0)

Cada ciclo guarda por ítem y lado (en `market_snapshot`, enteros pequeños y **de la región completa**, como los precios): unidades dentro del 5 % del mejor precio (`*_depth_5pct`), distancia al siguiente nivel de precio en puntos básicos (`*_gap_bp`) y parte del volumen en el mejor precio por mil (`*_top_permille`). Se calculan en `analytics/market_aggregation.py` y se muestran en el detalle del ítem.

Uso en el puntaje (versión 1.1.0, calibrado con 10.477 ítems reales el 2026-11-19):

- **Factor «libro y actividad»**: con datos de profundidad pasa a 60 % actividad (operaciones/día) + 40 % profundidad, donde profundidad = unidades del lado menos profundo / cantidad de la posición de referencia (0 → 0 pts, 0,1× → 30, 0,5× → 60, 1× → 80, 3× o más → 100). Sin dato, el factor es solo la actividad, como antes. Nota `BOOK_SHALLOW` si la razón es menor que 0,25×.
- **Filtro duro `INSUFFICIENT_DEPTH`**: la razón de profundidad debe ser al menos `min_depth_ratio` (Ajustes, 0,10 por defecto; 0 lo desactiva). Sin dato de profundidad no se aplica.
- Efecto medido: puntaje medio +2,2 (rango −6…+5, ningún cambio mayor de 10 puntos); 682 de 10.477 ítems (6,5 %) quedan bloqueados por el filtro, casi todos ya en «esperar».
- `gap` y `top_permille` se guardan y se muestran como información, pero todavía no puntúan: su lectura (guerra de centavos frente a un libro aislado) pide más datos.
