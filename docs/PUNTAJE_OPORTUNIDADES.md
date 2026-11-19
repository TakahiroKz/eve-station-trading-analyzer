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

## Capital propio (fase 3)

El puntaje guardado se mide con un capital de referencia (1.000 M ISK, 100 M por posición). Cada visitante puede indicar el suyo con el selector **Tu capital** (50 M / 250 M / 1.000 M por defecto / 5.000 M / otro, guardado en su navegador) y la API recalcula el puntaje para ese capital:

- `GET /api/items?capital=ISK` y `GET /api/items/{id}?capital=ISK` (entre 1 M y 10 billones; sin `capital` se devuelve el puntaje guardado). El servidor lo redondea a 2 cifras significativas (123 M → 120 M) y devuelve el valor usado en `capital`; el puntaje apenas cambia un 5 % y así las peticiones comparten caché.
- Con capital cambian solo los factores que dependen de él: liquidez, profundidad del libro (dentro de «libro y actividad»), eficiencia del capital, beneficio mínimo y días de rotación. Margen, volumen, estabilidad y el estado (POTENCIAL…) no cambian.
- Los filtros y el orden por puntaje (`min_score`, `score_class`, `eligibility`, `recommendation`, `sort=score`) se aplican después de recalcular. Recalcular un mercado entero (~17 mil ítems en Jita) cuesta ~1,4 s, así que se guarda por (mercado, capital, ajustes, ciclo): caduca con el siguiente ciclo (5 min), hay como máximo 6 entradas y solo se calcula un mercado a la vez. Sin filtros de puntaje solo se recalcula la página pedida (decenas de ms).
- El panel «¿Por qué este puntaje?» y el número de la cabecera del detalle usan el mismo capital.

### Selector, monto por posición y recomendación de unidades

- El selector **Tu capital** usa el mismo lenguaje visual que el de mercado (etiqueta en mayúsculas + píldoras: 50 M, 250 M, 1.000 M por defecto, 5.000 M y «Otro…» con un campo de millones de ISK). Debajo, una línea fija dice **cuánto va por posición** (10 % del capital) y para qué capital está calculado todo; cada píldora lo repite como `title`. El campo personalizado redondea a 2 cifras como el servidor.
- `GET /api/items/{id}` devuelve además un bloque `recommendation` (`UnitRecommendationOut`): con el capital elegido (o el de referencia), la posición = capital × `position_size_pct_wallet` y la misma cuenta del motor (`evaluar_oportunidad`, que ya recorta por liquidez) dan `unidades_sugeridas`, la inversión (unidades × precio de compra × comisión), el beneficio neto estimado y los días de rotación (unidades ÷ (volumen 7 d × participación capturable)). Si la evaluación del motor con ese capital es `REJECT`, las unidades son 0 y `blocked_by` lista los filtros que bloquean; con `WAIT` se muestran las unidades con el aviso de que valen solo si se decide comprar.
- El recuadro «Recomendación» del detalle muestra ese bloque. El propietario con sesión y **sin** capital elegido sigue viendo la recomendación en vivo con su wallet (`/api/private/items/{id}/recommendation`); si elige un capital, manda el del selector. `latest_opportunities` (historial del motor, dimensionado con el wallet del propietario) ya no se usa como recomendación.

- Las unidades sugeridas nunca superan lo que cabe en la posición **con la comisión de compra** (`posición ÷ (precio × comisión)`, redondeado hacia abajo), así que la inversión no excede la posición. Si no cabe ni una unidad (`alcanza = false`, p. ej. un ítem de 200 M ISK con 100 M por posición), las unidades son 0 y el recuadro explica cuánto cuesta una unidad frente a la posición; `precio_unidad_isk` lo expone.

## Pruebas y auditoría de veracidad (recomendación y capital)

Qué se comprueba y con qué (todo se puede repetir):

- **`tests/test_unit_recommendation.py`, `test_unit_recommendation_robustness.py`, `test_capital_api.py`, `test_recomendar_truthfulness.py`**: exactitud de unidades, inversión, beneficio (con el beneficio unitario exacto, no redondeado), rotación (volumen de 7 d), recorte por liquidez y por lo que cabe en la posición; rechazo y espera; límites (capital mínimo y máximo, precios de 0,01 a 1 billón de ISK, mercado invertido, sin volumen); JSON estricto (sin NaN ni Infinity); determinismo; peticiones en paralelo iguales a las secuenciales; coherencia lista, detalle y evaluación; y equivalencia del filtrado y orden por puntaje con una referencia a fuerza bruta (paginación incluida). `test_recomendar_truthfulness.py` recorre todas las combinaciones de spread y liquidez y 20.000 casos aleatorios: la frase nunca contradice las unidades, las unidades nunca superan lo deseado y «capital inmovilizado» solo sale con liquidez mala.
- **`scripts/audit_recommendation.py`** (solo lectura): recalcula con fórmulas escritas aparte (sin importar código del proyecto) 1.200 consultas (5 mercados × 4 estados × 6 capitales) y compara cifras y tipo de frase con la API; con `--esi` compara además los mejores precios y los volúmenes diarios guardados con la ESI en vivo. Para no tocar producción ni su límite de peticiones se ejecuta contra una copia de la base (`sqlite3 .backup`) servida por una API desechable sin límite.
- **`scripts/mutation_check.py`**: introduce 14 fallos a propósito (sin comisión, sin tope por posición, beneficio redondeado, rechazado con unidades, capital sin redondear, caché sin capital…) y exige que alguna prueba los detecte. Resultado: 14 de 14 detectados (dos pruebas se añadieron porque al principio sobrevivían).

Resultados de la auditoría del 2026-11-19 (VM de producción, copia de la base de las 14:50 UTC):

- **Datos de origen frente a la ESI en vivo**: 137 mejores precios comparados en los cinco mercados, diferencia mediana 0,00 %, 99 % dentro del 5 % (el resto, movimientos entre ciclos); 490 volúmenes diarios, **los 490 idénticos**.
- **Entradas hostiles** (`nan`, `inf`, `1e400`, texto, vacío, negativo, límites exactos, inyección SQL, parámetro repetido): siempre 422 o 404, nunca 500.
- **Fallos encontrados y corregidos**: (1) el beneficio neto estimado usaba el beneficio unitario ya redondeado a 2 decimales (error de hasta ~1 % en ítems baratos); (2) con liquidez excelente y spread pequeño el motor heredado caía en la rama de liquidez mala y decía «Baja el volumen… capital inmovilizado» con una posición del 1 % del volumen (16 de 1.200 casos); (3) un ítem sin volumen diario habría dado error 500; (4) podía mostrarse «candidato a compra» con 0 unidades; (5) rendimiento: las peticiones con filtro u orden por puntaje y capital costaban ~350 ms de CPU cada una (mediana de 9 s con 8 clientes a la vez); ahora ~55 ms, la misma carga pasó de 88 s a 17 s y la memoria del proceso de 877 MB a 146 MB.
- Tras las correcciones: 0 discrepancias en las 1.200 consultas (contra la versión anterior la misma auditoría detectaba 137).

Límites conocidos (no son fallos de cálculo): el beneficio y la inversión usan las tasas por defecto del motor (0,901 de venta y 1,024 de compra) y no las habilidades reales del personaje (T16/T17 pospuesto); los precios son el mejor precio de la región completa, no de una estación; y entre ciclos (5 min) los precios se mueven.
