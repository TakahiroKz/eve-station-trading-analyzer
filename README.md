# EveMarket Screener

Screener de **station trading** para EVE Online, enfocado en The Forge (Jita,
región `10000002`). Ingresa datos de mercado directamente desde la **ESI**
(API oficial de CCP Games — no scraping), calcula demanda, rotación, volumen,
volatilidad y spread por ítem, aplica las fórmulas de **EveCalculator** para
evaluar oportunidades de compra-venta en estación, y clasifica cada ítem en:

- **POTENCIAL** — spread, liquidez y actividad real de mercado (7 días) cumplen. Se
  registra automáticamente en Excel y dispara una alerta de Telegram.
- **POTENCIAL_SIN_ORDENES** — spread y liquidez cumplen, pero el histórico de
  transacciones ejecutadas es demasiado bajo (poco volumen o pocas operaciones/día):
  no hay evidencia de flujo real de compradores. No se registra como oportunidad.
- **EN_OBSERVACIÓN** — borderline, se necesita más historial.
- **DESCARTADO** — spread en pérdida, liquidez inviable, o precio de snapshot
  contaminado por una orden basura.

Dos motores separados, cada uno con su propia tarea programada de Windows: el de
**mercado** corre cada 4 horas (ingesta + screening); el de **posiciones** corre cada
5 minutos (revisa tus órdenes activas contra el libro de órdenes real y notifica solo
cuando cambia tu posición). Se puede consultar por consola, por una API REST, o por
una PWA instalable en el teléfono.

## Arquitectura

```
ESI (esi.evetech.net)
   │  cliente HTTP (paginación, rate-limit, sin scraping)
   ▼
ingestion/                → cliente ESI + OAuth (EVE SSO) para leer wallet/órdenes del personaje
storage/                   → SQLite (histórico, snapshots, clasificación vigente, órdenes propias)
analytics/                 → métricas de mercado + motor EveCalculator + clasificación + posición de órdenes
reporting/                 → registro Excel (fórmulas, append-only)
notifications/             → alertas de Telegram (componente compartido por ambos motores)
scheduler/run.py           → motor de MERCADO, cada 4h (ingesta → analítica → reporting)
scheduler/orders_run.py    → motor de POSICIONES, cada 5 min (tus órdenes vs. libro de órdenes real)
backend/api/               → API REST de solo lectura (FastAPI) sobre la SQLite
frontend/app/              → PWA (React) que consume la API — instalable en el teléfono
scripts/                    → autorización OAuth + registro de ambas tareas programadas de Windows
```

Cada carpeta principal tiene su propio `AGENTS-*.md` con el contrato detallado de esa
parte del sistema, y `AGENTS-Orquestador.md` describe el pipeline de 4 fases completo.

## Requisitos

- Python 3.11+
- Node.js 18+ / npm (solo si vas a tocar la PWA)
- Windows (la automatización usa el Programador de Tareas; el resto es portable)
- Una cuenta de EVE Online y, opcionalmente, una app registrada en
  [developers.eveonline.com](https://developers.eveonline.com/applications) para leer
  tu wallet (no es obligatorio: sin ella, el pipeline usa un volumen de referencia fijo)

## Instalación

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

Editá `.env` con tus valores. Como mínimo no hace falta tocar nada para correr el
screening de mercado — los defaults apuntan a The Forge y a rutas locales. Para
wallet/Telegram/Sheets, ver la sección de cada uno más abajo.

```bash
python -m storage.init_db
```

## Uso básico

```bash
python -m scheduler.run --backfill      # primera vez: trae histórico completo (~1 año)
python -m scheduler.run                 # corridas siguientes: actualiza y reclasifica
python -m scheduler.run --rescreen-only # solo re-evalúa lo ya guardado, sin golpear la ESI
python -m scheduler.orders_run          # motor de posiciones: revisa tus órdenes activas ahora
python -m reporting.status_report       # conteo de ítems por categoría
python -m reporting.status_report --detail POTENCIAL   # lista completa, ordenada por volumen real
```

## Wallet (dimensiona el volumen de compra según tu ISK)

Sin esto, el pipeline usa un volumen de referencia fijo (100 unidades). Con esto,
usa el 10% de tu wallet real / precio de compra de cada ítem.

1. Registrá una app en developers.eveonline.com con Callback URL
   `http://localhost:8765/callback` y el scope `esi-wallet.read_character_wallet.v1`.
2. Poné `ESI_SSO_CLIENT_ID` / `ESI_SSO_CLIENT_SECRET` en `.env`.
3. Corré una vez:

```bash
.venv\Scripts\python.exe scripts\authorize.py
```

Te abre el navegador para que inicies sesión **vos mismo** con tu cuenta de EVE — el
script nunca toca tus credenciales de juego. Guarda un `refresh_token` local y no hay
que repetirlo salvo que lo revoques.

## API REST

```bash
uvicorn backend.api.main:app --port 8001
```

- `GET /api/summary` — conteos por categoría + wallet
- `GET /api/items?status=POTENCIAL&sort=volumen_diario_real&order=desc` — lista
  (por defecto ordenada por volumen real, ROI como desempate)
- `GET /api/items/{type_id}` — detalle: histórico, snapshot, oportunidad
- `GET /api/status-changes` — últimos cambios de categoría

## PWA (web + móvil, un solo código)

```bash
npm --prefix frontend/app install     # una vez
npm --prefix frontend/app run dev     # desarrollo, localhost:5173 (proxy a la API en :8001)
npm --prefix frontend/app run build   # build de producción → frontend/app/dist
```

Se instala en la pantalla de inicio del teléfono desde el navegador (Chrome/Safari →
"Agregar a pantalla de inicio"), sin tienda de apps. El service worker que la hace
instalable **solo se activa en el build de producción** — en `npm run dev` no cachea
nada, así los cambios se ven al instante.

## Automatización (Windows Task Scheduler)

```bash
scripts\setup_task_scheduler.ps1   # registra la tarea, corre cada 4 horas
```

No superpone corridas (`MultipleInstances=IgnoreNew`). Logs diarios en
`logs\scheduler_YYYY-MM-DD.log`. Ver [OPERATIONS.md](OPERATIONS.md) para comandos de
consulta/parada y el resto del manual operativo (Telegram, verificación).

## Notificaciones (opcionales)

- **Telegram**: bot vía @BotFather → `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` en `.env`.

Sin configurar, Telegram degrada sin romper el pipeline.

## Verificación

```bash
python -m pytest tests/ -q
python -m ruff check .
python -m pip_audit -r requirements.txt
npm --prefix frontend/app audit --audit-level=high
npm --prefix frontend/app run build
```

## Documentación adicional

- [OPERATIONS.md](OPERATIONS.md) — manual operativo día a día (comandos, logs, troubleshooting)
- [BACKLOG.md](BACKLOG.md) — roadmap de scopes ESI futuros + tareas pendientes
- `AGENTS-*.md` en cada carpeta — contrato detallado de cada componente del pipeline
