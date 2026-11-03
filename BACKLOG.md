# Backlog del proyecto

Todo lo pendiente vive acá, categorizado. Nada de esto está implementado todavía —
se ataca cuando el usuario lo indique explícitamente.

---

## Roadmap — Scopes ESI a futuro

Política: autorización incremental. No se pide un scope hasta que la función que lo
necesita esté en desarrollo activo — así el `refresh_token` guardado en
`credentials/esi_refresh_token.txt` nunca tiene más privilegio del que el código
vigente realmente ejerce. Cuando se implemente cada ítem, correr `scripts/authorize.py`
de nuevo con el scope agregado a `ESI_SSO_SCOPES` en `.env`. Todos ligados a la misma
app ("personal-station-trading-analyzer") — no se crea una app nueva, se reautoriza.

### R1. Alt de trading vía corporación de un solo miembro
Cuando el capital justifique operar desde una corp propia.
- `esi-wallet.read_corporation_wallets.v1` — billeteras por división de la corp.
- `esi-markets.read_corporation_orders.v1` — órdenes de mercado corporativas.
- `esi-assets.read_corporation_assets.v1` — stock en hangares corporativos.

### R2. Trading regional con logística (courier contracts)
Comprar en Jita, revender en Amarr/Dodixie/estructura vía transporte contratado.
- `esi-contracts.read_character_contracts.v1` — estado de contratos de mensajería/subasta.

### R3. Estructuras de jugadores (Keepstars/Fortizars)
Resolver IDs/nombres de estructuras privadas y leer sus mercados.
- `esi-universe.read_structures.v1` — resolver IDs de estructuras privadas.
- `esi-markets.structure_markets.v1` — mercado dentro de una estructura privada.

### R4. ~~Notificaciones y automatización de UI en el cliente~~ (código hecho, falta reautorizar)
Alertas de undercut/venta completada, y atajos hacia el cliente de EVE.

**Corrección aplicada**: `esi-characters.read_notifications.v1` (el scope que se había anotado
originalmente) no cubre esto — son eventos de corp/guerra/facturas, no fills de mercado. El
scope correcto es `esi-markets.read_character_orders.v1`.

- `esi-markets.read_character_orders.v1` — tus órdenes activas + historial, para detectar
  undercut (alguien te ganó el precio) y órdenes completadas/expiradas/canceladas.
- `esi-ui.open_window.v1` — abrir la ventana de mercado de un ítem desde la PWA.

Implementado: `character_order`/`character_order_closed` (SQLite), `analytics/undercut.py`
(función pura, testeada), `check_character_orders()` en `scheduler/run.py`, dos alertas nuevas
de Telegram, endpoint `POST /api/items/{type_id}/open-in-client`, botón "Abrir en cliente EVE"
en la PWA. **Pendiente del usuario**: correr `scripts/authorize.py` de nuevo — `.env` ya tiene
`ESI_SSO_SCOPES` actualizado con los 3 scopes (wallet + orders + ui.open_window).

---

## Tareas Pendientes (funcionalidad, no requieren scope nuevo)

### T1. ~~Paginador en el frontend~~ (hecho)
`/api/items` ahora devuelve `{items, total, limit, offset}` (límite 50/página, tope 500).
`App.tsx` tiene controles Anterior/Siguiente + indicador de página, resetea a la página 1
al cambiar de tab o de filtros.

### T2. ~~Filtros personalizados en el frontend~~ (hecho)
Filtros combinables agregados: categoría del ítem, ROI, spread, precio de compra, precio
de venta, volumen diario (todos con min/max donde aplica). Implementado:
- `item_category` (nueva tabla, cacheada desde `/universe/types|groups|categories/` de
  la ESI — sin endpoint bulk, ~19K llamadas la primera vez, incremental después).
- `item_status` ahora también guarda `best_buy`/`best_sell` para poder filtrar por precio
  sin joinear `market_snapshot`.
- `/api/items` acepta `category_id`, `min_roi`/`max_roi`, `min_spread`/`max_spread`,
  `min_buy`/`max_buy`, `min_sell`/`max_sell`, `min_volume`/`max_volume`.
- `/api/categories` para poblar el selector.
- Panel de filtros colapsable en `App.tsx` (botón "Filtros ▼"), con "Aplicar"/"Limpiar".

### T3. Ampliar el scope OAuth para endpoints adicionales
Ver sección Roadmap arriba (R1-R4) — es el mismo ítem, no una tarea separada.

### T4. ~~Migrar de scraper a consumo de API~~ (resuelto — malentendido)
El pipeline actual (`ingestion/esi_client.py`) ya consume la ESI oficial de CCP
directamente, sin scraping de HTML en ningún punto del proyecto (se descartó
explícitamente en el Paso 3 de la arquitectura). Usuario confirmó que fue un
malentendido — sin acción pendiente.

### T5. Planificar subida de la aplicación a internet
**Restricción del usuario: solo herramientas gratuitas** (proyecto personal, sin
presupuesto) — descartar de entrada cualquier opción de pago al evaluar proveedor
(VPS pago, PaaS con tier solo pago, Postgres administrado de pago, etc.). Priorizar
free tiers (Railway/Fly.io/Render free tier, Supabase/Neon free tier para Postgres si
hace falta migrar de SQLite, GitHub Pages/Vercel/Netlify free tier para la PWA, etc.).

Hoy todo corre local (SQLite en disco, API en `localhost:8001`, tarea programada de
Windows, PWA servida por Vite dev o un build estático local). Pasar a un entorno web
real implica decidir, entre otras cosas:
- Hosting del backend/API (FastAPI) y si SQLite alcanza o conviene migrar a Postgres.
- Dónde corre el pipeline periódico (`scheduler/run.py`) sin el Programador de Tareas
  de Windows — cron gestionado, worker programado, etc.
- Hosting de la PWA con HTTPS real (requisito para que el service worker/instalación
  funcionen fuera de `localhost`) y su propio dominio.
- Manejo de secretos en el entorno remoto (`.env` hoy es local: ESI SSO, Google
  service account, Telegram bot token) — no subir tal cual, usar el mecanismo de
  secrets del proveedor elegido.
- Costo/proveedor (VPS, PaaS tipo Railway/Fly.io/Render, etc.) — sin definir todavía.
No implementado — solo queda planificarlo cuando se decida encarar. **2026-09-21: el
usuario trajo una épica externa** (`EPIC-001`, PO Isaías) proponiendo migrar a una
Arquitectura Orientada a Eventos completa (RabbitMQ/Redis, Airflow, PostgreSQL,
Django/Flask, Docker Compose, microservicios). Evaluado y descartado ESE nivel de
infraestructura para este proyecto: es para sistemas multi-tenant de alto volumen, no
para un usuario único con 2 corridas programadas (4h/5min) — ningún free tier serio
ofrece un broker o Airflow persistentes gratis, y reescribir FastAPI en Django no
aporta nada. Lo único de la épica que se rescató fue el concepto de "AlertRules"
configurables (ver T6, hecho). El usuario confirmó explícitamente: no migrar a
internet todavía — T5 queda tal cual, pendiente para cuando se decida encarar.

**2026-09-21 (retomado)**: el usuario decidió encarar T5. Camino elegido tras comparar
tres opciones (VM gratis en la nube, PC propia + Cloudflare Tunnel, migrar a
Postgres+serverless): **VM gratis de Oracle Cloud Free Tier**, Docker + cron
reemplazando el Programador de Tareas de Windows, SQLite sin migrar — la opción de
menor reescritura, misma arquitectura que hoy, solo cambia el sistema operativo del
host y quién dispara las corridas programadas. La cuenta de Oracle Cloud está en
proceso de creación por el usuario.

Primeros pasos hechos:
- Repo subido a GitHub: `SukunaRyomenDev/EveMarket-Analyzer-Trading-Tool` (privado).
  Verificado antes de subir que `.env`, `credentials/` y `storage/*.db` nunca
  estuvieron trackeados (ya en `.gitignore` desde antes).
- CI agregado: `.github/workflows/ci.yml`, corre en cada push/PR a `main` — ver
  DEUDA_TECNICA.md D5 (resuelto).

Pendiente: Dockerfile del backend, forma de correr los dos motores como jobs de cron
dentro de Docker, `docker-compose.yml` con volumen persistente para `market.db`,
workflow de CD (deploy por SSH a la VM al mergear a `main`), y del lado del usuario —
terminar de crear la VM de Oracle y generar el par de llaves SSH para el deploy.

**2026-09-22 (T5 — funcionando en producción)**: pipeline de CI/CD completo, verificado
de punta a punta contra la VM real (`<IP-DE-LA-VM>`), con la primera corrida real del
motor de mercado poblando datos reales (16.089 ítems clasificados, 699 POTENCIAL).

- `Dockerfile` (build de dos etapas: Node compila la PWA, imagen final Python
  3.11-slim la sirve junto con la API desde el mismo proceso — sin CORS en
  producción) + `docker-compose.yml` (servicios `api`, `engine-market`,
  `engine-positions`, los dos motores detrás del profile `cron`) +
  `scripts/setup_cron.sh` (cron con `flock` para no superponer corridas).
- Workflow de CD (`deploy.yml`): build + push a GHCR + deploy SSH + health check
  post-deploy. Deploy key dedicado (separado del que usa la VM para `git pull`),
  generado y cargado directo a GitHub/VM sin pasar por el chat.
- `CONTRIBUTING.md`: adaptación de un framework de "sistema multi-agente" que trajo
  el usuario — branch protection real en GitHub no se pudo activar (plan Free +
  repo privado no lo permite), documentado como disciplina en vez de control técnico;
  QA = subagente de revisión independiente en vez de simular roles.
- **Bug real encontrado y corregido en producción**: `ingest()`/`ingest_categories()`
  (scheduler/run.py) tenían 20 threads concurrentes hardcodeados — en la VM de 1GB
  RAM eso causaba swap thrashing y estancamientos reales (visto en vivo, hubo que
  matar la corrida dos veces). Nuevo `MAX_INGEST_WORKERS` configurable por entorno;
  la VM quedó en 4 (2 solo tuvo que usarse puntualmente para la primera carga masiva
  de categorías, ~19K ítems sin cachear todavía).
- Firewall de la VM: hubo que abrir el puerto 8001 en dos capas (iptables del propio
  SO, que Oracle deja bloqueando todo salvo SSH por defecto, y el Network Security
  Group de Oracle a nivel de nube) — ninguna alcanza sola.
- Pendiente real: por qué el push de un merge no siempre dispara `deploy.yml` al
  toque (una vez hubo que lanzarlo a mano con `workflow_dispatch`; en el merge
  siguiente sí disparó solo — parece demora de entrega del webhook, no una falla
  sistemática, pero queda para confirmar en el próximo merge real).

**2026-09-22 (HTTPS + dominio propio — cerrado)**: dominio `evemarket-analyzer.online`
(GoDaddy) apuntado a Cloudflare (nameservers cambiados, gratis) + **Cloudflare
Tunnel** (`cloudflared`, instalado como servicio systemd en la VM) en vez de abrir
más puertos o gestionar certificados a mano — Cloudflare termina el TLS en su borde,
el túnel conecta saliente desde la VM sin necesitar el puerto 8001 abierto al público
para este acceso (sigue abierto por ahora para acceso directo por IP, sin tocar).
`https://evemarket-analyzer.online` sirve la API + la PWA completas, service worker
incluido (antes no era instalable como PWA de verdad sin contexto seguro). Config del
túnel en `/etc/cloudflared/config.yml` en la VM (no versionado, es específico del
host — solo mapea el hostname al `localhost:8001` del contenedor `api`).

**2026-09-23 (primera noche completa — bug real encontrado y corregido)**: revisando
los logs de la primera noche corriendo sola, 14 de 150 corridas del motor de
posiciones (~9.3%) habían fallado con `sqlite3.OperationalError: database is locked`
en el primer write de `main()` — la corrida entera se abortaba sin revisar ni una
orden. Causa confirmada con los números: el motor de mercado mantenía transacciones
de escritura abiertas hasta ~40s entre commits (cada 500 filas, corrida de ~22 min) —
22min/240min ≈ 9.2% del ciclo de 4h, casi exacto al 9.3% observado. El
`busy_timeout` de 5s (agregado en T6 para este mismo tipo de choque) se quedaba corto
para esa ventana. Corregido con tres cambios: intervalo de commit bajado de 500/1000
a 100/200 filas en los tres loops de escritura de `scheduler/run.py`, `busy_timeout`
subido a 30s, y un reintento (`_init_db_with_retry`) en `orders_run.py` como red de
seguridad extra. 87 tests pasando (3 nuevos), desplegado y confirmado en producción.

### T6. ~~AlertRules configurables (umbrales de clasificación)~~ (hecho)
Del análisis de `EPIC-001` (ver nota en T5): lo único aplicable a un proyecto personal
de un solo usuario era el concepto de "Panel de Control API" con CRUD de reglas de
alerta — el resto de la épica (broker de eventos, Airflow, Postgres, Django, Docker)
se descartó por sobredimensionado.

Reemplaza las constantes hardcodeadas `MIN_DAILY_VOLUME_7D`/`MIN_DAILY_ORDER_COUNT_7D`
de `analytics/classification.py` (que ya estaban documentadas como "ajustables si el
screening resulta muy laxo/estricto") por una fila configurable en SQLite:
- `classification_settings` (fila única, id=1) — `min_daily_volume_7d`,
  `min_daily_order_count_7d`, `updated_at`.
- `GET`/`PUT /api/settings/classification` en la API.
- `classify()` ahora recibe los umbrales como parámetro (default = las constantes de
  siempre, para no romper los tests existentes); `scheduler/run.py` los lee de la DB
  al arrancar cada corrida del motor de mercado (cada 4h) y se los pasa.
- Pantalla nueva "Ajustes" en la PWA (navbar) para editarlos sin tocar código ni la API
  a mano — avisa que el cambio se aplica en la próxima corrida, no retroactivamente.

**Bug de concurrencia encontrado y corregido de paso**: las conexiones SQLite (API y
motores) no tenían `PRAGMA busy_timeout`, así que dos procesos escribiendo al mismo
tiempo (ej. guardar Ajustes mientras corre el motor de mercado) tiraban `database is
locked` al toque en vez de esperar y reintentar. Ahora ambas (`storage.db.get_connection`
y `backend/api/main._db`) esperan hasta 5s antes de fallar — reproducido en vivo
(corrida de re-screening simultánea con un guardado desde la PWA) y verificado que ya
no falla.

### T7. ~~Fase 1 de EPIC-001: auditoría SOLID + patrón de eventos interno~~ (hecho)
Siguiente paso del análisis de `EPIC-001` (ver T5): con AlertRules (T6) resuelto, el
usuario pidió encarar los otros dos candidatos de refactor liviano que quedaron
anotados — sin agregar infraestructura nueva (nada de broker externo todavía).

- **Auditoría SOLID en `ingestion/`**: revisados `esi_client.py`, `session.py`,
  `wallet.py`, `esi_auth.py` — los cuatro son 100% extracción/auth, sin cálculo de
  negocio mezclado. Sin cambios ahí. Sí se encontró la MISMA mezcla que la auditoría
  buscaba, pero en el orquestador: `build_orders_by_type()` (reduce el libro de
  órdenes crudo a best_buy/best_sell/volúmenes por ítem) vivía como función suelta en
  `scheduler/run.py` en vez de `analytics/`, y no tenía tests. Movida a
  `analytics/market_aggregation.py` con 5 tests nuevos.
- **Patrón de eventos interno**: nuevo `notifications/events.py` — `NewOpportunity`,
  `PositionChanged`, `OrderClosed` (dataclasses) + `dispatch(events)`. Antes cada motor
  llamaba `notify_*()` directo, intercalado con la lógica de cada corrida. Ahora
  acumulan eventos en una lista local y llaman `dispatch()` una sola vez al final —
  mismo comportamiento (mismas notificaciones, misma corrida), pero `dispatch()` queda
  como el ÚNICO punto que conoce `notifications/telegram_bot.py`. El día que haga falta
  un bus de eventos de verdad (Redis/RabbitMQ, si T5 lo justifica), ese cambio queda
  contenido en `dispatch()` — publicar en la cola en vez de llamar `notify_*()`
  directo — sin tocar `scheduler/run.py` ni `scheduler/orders_run.py`.
- Verificado en vivo: `scheduler.orders_run` real (14 activas, 1 cerrada, notificación
  de cierre disparada vía el nuevo `dispatch()`). 58 tests pasando (10 nuevos), `ruff`
  limpio.

### T8. ~~Notificación de oportunidades: cantidad sugerida de unidades~~ (hecho)
Pedido del usuario: que la notificación de una oportunidad nueva tenga en cuenta el ISK
de la cuenta y sugiera cuántas unidades comprar, según el análisis ya hecho (spread,
liquidez, volumen diario real). El cálculo wallet-aware (`resolve_volumen_deseado`, 10%
del wallet / precio de compra) YA EXISTÍA desde el principio — el problema era que el
número nunca se mostraba en la notificación de Telegram.

Al agregarlo, apareció un desacuerdo latente: `recomendar()` (texto libre, ej. "bajá el
volumen a ~X unidades" cuando la liquidez del ítem no aguanta el 10% del wallet) nunca
alimentaba de vuelta al número real sugerido — mostrar el `volumen_deseado` crudo al
lado de un texto que pide recortarlo se habría visto contradictorio. `recomendar()`
ahora devuelve `(texto, unidades_sugeridas)` desde el mismo cálculo, así que nunca
pueden desacordar: `unidades_sugeridas` solo puede recortar el volumen wallet-based
cuando la liquidez lo obliga, nunca escalarlo por encima del 10% de riesgo. Nuevo campo
`EveCalculatorResult.unidades_sugeridas`.

`notify_new_opportunity` ahora suma "💰 Comprá ~X unidades (~Y ISK)" + "Beneficio total
estimado: ~Z ISK" antes de la recomendación en texto. Verificado con dos casos reales
(liquidez holgada y liquidez forzando recorte) sin disparar Telegram de verdad
(`_send_message` interceptado). 64 tests pasando (6 nuevos), `ruff` limpio.

**Nota histórica, resuelta en DEUDA_TECNICA.md D1**: el 10% de wallet se calculaba
igual para CADA oportunidad detectada en una corrida, usando el wallet de la corrida
de 4h (podía quedar horas desactualizado). Ver D1 para el detalle de la solución: el
detalle de ítem ahora recalcula la recomendación contra el wallet en vivo en cada
consulta, en vez de leer el valor guardado.

### T9. ~~Parametrizar todo el análisis (Ajustes categorizado + reset a default)~~ (hecho)
Pedido del usuario: sacar TODOS los umbrales/factores hardcodeados del análisis a
"Ajustes", categorizados, editables desde la PWA, con botón de "restablecer valores
por defecto". Iba más allá de las 2 AlertRules de T6/T8 (`min_daily_volume_7d`/
`min_daily_order_count_7d`) — auditoría completa encontró 19 parámetros en 7
categorías repartidos por `analytics/`:

- **Clasificación** (ya existían, migrados): volumen/operaciones mínimas diarias.
- **Fees de EVE**: `sales_tax_factor` (0.901), `buy_fee_factor` (1.024) — eran las
  constantes que el usuario había dado como fijas en la sesión original de
  EveCalculator; ahora configurables porque el pedido de esta sesión fue explícito
  ("todos los parámetros"), pero el default sigue siendo ese valor exacto.
- **Umbrales de spread** (5) y **Umbrales de liquidez** (4): los techos de
  `evaluar_spread()`/`evaluar_liquidez()` que definen las etiquetas 🟢/🟡/❌.
- **Tamaño de posición** (2): `position_size_pct_wallet` (10% del wallet),
  `volumen_deseado_fallback` (100 u. si no hay wallet).
- **Recomendación de volumen** (2): los % de `recomendar()` que topean
  `unidades_sugeridas` según liquidez.
- **Filtro de órdenes basura** (2): los ratios de `analytics/sanity.py`.

Reemplaza la tabla de fila única `classification_settings` (T6) por una tabla genérica
`app_settings` (fila por parámetro: key/category/label/description/value/
default_value) — agregar un parámetro nuevo en el futuro es agregar una entrada en
`storage/settings_registry.py`, no tocar schema/API/PWA. Migración automática: si
existía la tabla vieja, sus 2 valores pasan al sistema nuevo antes de sembrar el resto
con los defaults del registro (verificado en vivo contra `market.db` real — no se
perdió la edición del usuario).

`analytics/eve_calculator.py` y `analytics/sanity.py` ahora reciben un `config`
(`EveCalculatorConfig`/`SanityConfig`, dataclasses con los defaults de siempre) en vez
de leer constantes de módulo — los nombres de campo son iguales a las keys del
registro a propósito, así `scheduler/run.py` arma cada config con `**kwargs`
filtrados por `dataclasses.fields()`, sin mapeo manual.

API: `GET /api/settings` (todos, categorizados), `PUT /api/settings/{key}` (404 si no
existe, 422 si negativo o si es una key indispensable —`min_daily_order_count_7d`,
`sales_tax_factor`, `buy_fee_factor`— y se manda 0), `POST /api/settings/reset`
(resetea TODOS a `default_value`). Pantalla "Ajustes" de la PWA reescrita para ser
genérica: agrupa por categoría, un input+hint por parámetro, "Guardar cambios" (solo
manda PUT de lo que cambió) + "Restablecer valores por defecto".

Verificado en vivo end-to-end: migración contra `market.db` real, GET/PUT/reset por
API, y la pantalla Ajustes en el navegador (editar, guardar, resetear, confirmado
contra la DB real en cada paso). 69 tests pasando (10 nuevos, incluye tests que
prueban que un `config` no-default de verdad cambia el resultado, no solo que el
default coincide con antes), `ruff` limpio.

### T10. ~~Bug: reprice no se reflejaba en "Mis Órdenes" tras Refrescar~~ (hecho)
El usuario reajustó el precio de varias órdenes (reprice, sin cancelar/recrear) para
quedar primero en el libro, pero seguían apareciendo como undercuteadas después de
"Refrescar". Diagnóstico en vivo con datos reales, no reproducible por lógica —
confirmado contra la ESI directamente:

- `/characters/{character_id}/orders/` (mis órdenes) devolvía el precio VIEJO
  (3.95) para una orden que el usuario ya había reajustado.
- `/markets/{region_id}/orders/?type_id=...` (libro público de la región, lo que el
  motor de posiciones usa para calcular `orders_ahead`) YA tenía el precio nuevo
  (3.93) para esa misma `order_id`.

Es un lag real del lado de la ESI en el endpoint personal después de un reprice — no
un bug de cálculo. `compute_position()` (`analytics/order_position.py`) ahora resuelve
esto solo: si la propia orden ya aparece en `book` (el libro que igual se trae para
calcular la competencia), usa ESE precio en vez del pasado por parámetro — más
confiable que el del endpoint personal. `OrderPosition` gana un campo `my_price` con
el precio efectivamente usado, que `scheduler/orders_run.py` ahora también usa para lo
que persiste/muestra como precio de la orden (antes solo corregía el cálculo interno,
dejando el precio mostrado desactualizado).

Verificado en vivo con las órdenes reales del usuario: antes del fix, 2 órdenes de
"Ionic Solutions" (type_id 2309) y 1 de otro ítem quedaban marcadas undercuteadas con
precio viejo pese a estar repreciadas; después del fix, las 3 pasan a "Vas primero"
con el precio correcto — confirmado contra la DB y en la PWA real (botón Refrescar).
71 tests pasando (2 nuevos), `ruff` limpio.

### T11. ~~Notificación de ejecuciones (compra/venta) sobre órdenes activas~~ (hecho)
Pedido del usuario: avisar cuando se detecte una compra o venta de las órdenes que
tiene puestas. Hasta ahora el motor de posiciones solo notificaba dos cosas: cambios
de posición (undercut) y el cierre final de una orden (completada/expirada/cancelada)
— un llenado PARCIAL (alguien te compra/vende una parte, la orden sigue activa con
`volume_remain` más bajo) no generaba ningún aviso; el usuario se enteraba recién
cuando la orden se vaciaba del todo y desaparecía.

`scheduler/orders_run.py` ahora compara `volume_remain` de la corrida anterior contra
el de la corrida actual para cada orden todavía activa: si bajó, hubo una ejecución.
Nuevo evento `OrderFilled` (`notifications/events.py`) con `filled_units` (la
diferencia) y `volume_remain` (lo que queda) — despachado a `notify_order_filled()`
(`notifications/telegram_bot.py`), que trae el saldo del wallet igual que
`notify_order_closed` (solo para ventas, ahí sí entró ISK). Una ejecución que deja
`volume_remain` en 0 NO pasa por acá — la orden desaparece de las activas y la agarra
`OrderClosed` en la corrida siguiente (ya con su propio wallet_balance), evitando dos
notificaciones para el mismo evento.

Verificado en vivo con datos reales sin arriesgar la DB de producción ni mandar un
Telegram real: se corrió `check_character_orders()` contra una COPIA de `market.db`
con el `volume_remain` de una orden real inflado a mano (simulando que ya se habían
ejecutado 500 unidades) y `dispatch()` interceptado — el evento salió exacto
(`filled_units=500`, `volume_remain` real, `wallet_balance` real de la cuenta por ser
una venta). 73 tests pasando (4 nuevos), `ruff` limpio.

### T12. ~~Refresco manual sin spam de Telegram + wallet desactualizado + reloj EVE/local~~ (hecho)
Tres pedidos del usuario juntos:

1. El botón "Refrescar" de Mis Órdenes reusaba `check_character_orders()` tal cual
   (misma lógica que el motor de 5 min), incluyendo el `dispatch()` — cada refresco
   manual reenviaba los mismos avisos de Telegram que ya manda el motor programado.
   `check_character_orders()` ganó un parámetro `notify: bool = True`; el endpoint
   `POST /api/character-orders/refresh` ahora lo llama con `notify=False` (persiste
   los cambios igual, solo omite el `dispatch`).
2. El wallet del topbar (`summary.wallet_balance`) se pedía una sola vez al cargar la
   página y nunca más — quedaba desactualizado apenas refrescabas órdenes.
   `refreshOrders()` en el frontend ahora también vuelve a pedir `/api/summary` al
   terminar.
3. Se agregó un reloj en vivo (tick cada segundo) bajo el valor del wallet: hora EVE
   (UTC) y hora local del navegador.

### T13. ~~Timer de próxima corrida de los dos motores en Mis Órdenes~~ (hecho)
Pedido del usuario: mostrar en Mis Órdenes cuándo corre la próxima notificación de
cada motor (mercado, cada 4h; posiciones, cada 5 min).

Se descartó estimarlo desde datos propios de la app (ej. último item evaluado + 4h)
porque el trigger de cada tarea programada de Windows es fijo desde que se registró
(`scripts/setup_task_scheduler.ps1`) — un refresco manual, por ejemplo, no mueve el
próximo disparo real de la tarea de 5 min, así que una estimación local daría un valor
incorrecto. En cambio, nuevo módulo `ingestion/schedule.py` le pregunta directamente
al Programador de Tareas de Windows (`Get-ScheduledTaskInfo` vía subprocess a
powershell) el `NextRunTime` real de `EveMarketScreener_Pipeline` y
`EveMarketScreener_Positions`; degrada a `None` sin bloquear si powershell falla o las
tareas no están registradas todavía. Nuevo `GET /api/schedule`.

En el frontend, Mis Órdenes pide `/api/schedule` al entrar a la vista y cada 60s
mientras el usuario se queda ahí (el disparo real puede ocurrir en cualquier momento;
sin este refresco periódico el timer se quedaría mostrando "en curso…" para siempre),
y cuenta regresivamente en vivo contra el reloj de un segundo ya agregado en T12.

Verificado en vivo: `Get-ScheduledTaskInfo` confirmado devolviendo el `NextRunTime`
real de ambas tareas; countdown probado tickeando hacia abajo segundo a segundo en el
navegador, y la transición a "en curso…" cuando el timer de posiciones llegó a cero.
73 tests pasando, `ruff` limpio.

### T14. ~~Login de seguridad — que solo el usuario pueda acceder~~ (hecho)
Pedido del usuario (2026-09-22, después de cerrar T5/HTTPS): hoy `https://evemarket-
analyzer.online` no tiene ningún control de acceso — cualquiera que encuentre la URL
ve el wallet real, las órdenes activas, y puede tocar "Refrescar" o cambiar Ajustes.
Con dominio público + HTTPS real ya en producción (antes, al menos, la URL no era
"encontrable" fácilmente), esto pasa de ser un detalle a un gap de seguridad activo.
Pedido explícito: que el login en sí no sea vulnerable — no alcanza con "agregar
cualquier login", tiene que ser uno bien hecho.

**Recomendación para cuando se encare** (no implementado todavía, solo la dirección):
dado que ya se armó Cloudflare Tunnel hoy (BACKLOG.md T5), la opción de menor riesgo y
menor esfuerzo es **Cloudflare Access** (Zero Trust, plan free hasta 50 usuarios) —
Cloudflare exige el login (magic link/OTP a tu email, restringido a tu dirección
específica) ANTES de que el tráfico llegue al túnel/la app. Evita:
- Programar autenticación a mano en FastAPI (superficie real de bugs de seguridad —
  justo lo que el usuario pidió evitar).
- Tocar el código de la app para nada — el control queda 100% en la capa de Cloudflare,
  ya integrada con el túnel existente.

Alternativa si en algún momento se quiere login propio (más esfuerzo, más riesgo, solo
si Cloudflare Access no alcanza para algún caso de uso futuro): OAuth contra un
proveedor externo (ej. "Sign in with GitHub/Google" restringido a un email específico)
en vez de usuario/contraseña propios — nunca implementar hashing/sesiones a mano salvo
que sea estrictamente necesario.

**2026-09-23 — Cerrado, confirmado en producción.** El usuario pidió explícitamente
una vista pública parcial en vez de gatear el dominio entero: sin login solo Screener
(con filtros) + reloj EVE/local + cuentas regresivas; con login, todo (+ Mis Órdenes,
Ajustes, Wallet). Implementado:
- Rutas sensibles movidas a `/api/private/*` (`backend/api/private.py`): wallet,
  órdenes propias, ajustes, abrir-en-cliente, y la recomendación de sizing en vivo
  (antes mezclada en `GET /api/items/{id}`, ahora en
  `/api/private/items/{id}/recommendation`). `/api/summary` y `/api/items/{id}` ya no
  filtran nada derivado del wallet.
- Defensa en profundidad liviana (`deps.require_cf_access_header`): sin verificar
  firma, decisión tomada con el usuario — ver D16 en DEUDA_TECNICA.md.
- Frontend (`App.tsx`): probe de sesión (`/api/private/auth/ping`) gatea Wallet/Mis
  Órdenes/Ajustes/recomendación en vivo; Screener + reloj quedan siempre visibles.
- De paso se cerró D9 (puerto 8001 ya no expuesto públicamente) — necesario para que
  Cloudflare Access no sea saltable pegándole directo a la IP.
- Botón "Iniciar sesión" visible en la navbar (solo sin sesión): la primera versión
  no tenía ningún elemento clickeable que disparara el login, porque la app solo
  pegaba a `/api/private/*` vía `fetch()` (que no puede mostrar la pantalla de
  Cloudflare Access por CORS en el redirect). El link hace una navegación real de
  página a `GET /api/private/login`, que además redirige de vuelta a `/` al volver
  del OTP (si no, el usuario terminaba viendo el JSON crudo de `auth/ping`).

Del lado del usuario: se creó la Access Application en Cloudflare Zero Trust
(`evemarket-analyzer.online`, path `/api/private`, policy con su email) y se
verificó el flujo completo en producción — OTP por email, WALLET/Mis Órdenes/Ajustes
visibles después de loguearse. Funciona igual en PC y celular (cookie de navegador
estándar, no depende del dispositivo). Queda como nota menor, no bloqueante: la
regla del NSG de Oracle para el 8001 sigue sin sacarse (D9 ya cerrado igual, porque
`docker-compose.yml` dejó de publicar el puerto — la regla del NSG hoy no tiene nada
detrás a lo que conectarse).
