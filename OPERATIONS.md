# Operación — EveMarket Screener

## Producción: VM de Oracle Cloud (desde 2026-09-22)

La automatización real corre en la VM (`141.148.60.142`, Oracle Free Tier) vía Docker +
cron — ver `CONTRIBUTING.md` para el flujo de CI/CD y `docker-compose.yml` /
`scripts/setup_cron.sh` para cómo están armados los dos motores ahí. Las tareas de
Windows (abajo) están **desactivadas** (`Disable-ScheduledTask`, no eliminadas) desde
que la VM quedó operativa — tenerlas las dos activas duplica cada notificación de
Telegram, porque las dos le pegan al mismo bot/chat con su propia SQLite separada.

Reactivarlas (ej. para volver a correr algo localmente sin la VM):
```powershell
Enable-ScheduledTask -TaskName "EveMarketScreener_Pipeline"
Enable-ScheduledTask -TaskName "EveMarketScreener_Positions"
```
Si se reactivan, desactivar primero el deploy/cron de la VM (o al revés) para no volver
a duplicar avisos.

## Automatización local (Windows, Fase 1 — hoy desactivada, ver arriba)

Dos tareas programadas de Windows, corriendo mientras tengas sesión iniciada (no
requieren contraseña guardada ni cuenta de servicio), cada una con su propia cadencia:

- **Motor de mercado** (`scheduler/run.py`, tarea `EveMarketScreener_Pipeline`) — cada
  4 horas: ingesta ESI + screening EveCalculator + Excel/Sheets + alertas de
  oportunidades nuevas. No toca tus órdenes de personaje.
- **Motor de posiciones** (`scheduler/orders_run.py`, tarea `EveMarketScreener_Positions`)
  — cada 5 minutos: revisa tus órdenes activas contra el libro de órdenes REAL de cada
  ítem (cuántas te compiten por delante y por cuánto precio), detecta cierres, y
  notifica solo cuando cambia tu posición.

Ambos motores comparten el mismo componente de notificación
(`notifications/telegram_bot.py`).

```powershell
Get-ScheduledTaskInfo -TaskName "EveMarketScreener_Pipeline"    # estado / próxima corrida (mercado)
Get-ScheduledTaskInfo -TaskName "EveMarketScreener_Positions"   # estado / próxima corrida (posiciones)
Start-ScheduledTask -TaskName "EveMarketScreener_Pipeline"      # correr ahora
Start-ScheduledTask -TaskName "EveMarketScreener_Positions"     # correr ahora
Unregister-ScheduledTask -TaskName "EveMarketScreener_Pipeline" -Confirm:$false   # eliminar
Unregister-ScheduledTask -TaskName "EveMarketScreener_Positions" -Confirm:$false  # eliminar
```

Reinstalar/reconfigurar ambas tareas (ej. si cambia algún intervalo):
```powershell
scripts\setup_task_scheduler.ps1
```

Logs: uno por día en `logs\scheduler_YYYY-MM-DD.log` (mercado) y
`logs\orders_YYYY-MM-DD.log` (posiciones). No hay purga automática de logs viejos
todavía — revisar periódicamente si conviene limpiar `logs/`.

`MultipleInstances=IgnoreNew` en ambas tareas: si una corrida sigue activa cuando toca
la siguiente, esa siguiente se salta (no se superponen dos corridas contra la misma
SQLite).

## Comandos manuales

```bash
python -m scheduler.run                    # motor de mercado: ingesta completa + screening
python -m scheduler.run --rescreen-only     # solo re-evalúa lo ya guardado en SQLite (rápido)
python -m scheduler.run --backfill          # histórico completo (~1 año), usar rara vez
python -m scheduler.orders_run              # motor de posiciones: revisa tus órdenes activas ahora
python -m reporting.status_report           # conteos por categoría
python -m reporting.status_report --detail POTENCIAL
```

## Servicios (no automatizados — arrancar manualmente cuando se quieran usar)

```bash
uvicorn backend.api.main:app --port 8001         # API REST (solo lectura sobre market.db)
npm --prefix frontend/app run dev                # PWA en desarrollo (localhost:5173)
npm --prefix frontend/app run build              # build de producción (frontend/app/dist)
```

## Wallet, órdenes propias y ventana del cliente (OAuth EVE SSO)

```bash
.venv\Scripts\python.exe scripts\authorize.py    # una vez, o si el refresh_token se invalida/amplía
```

Requiere que el Callback URL de la app en developers.eveonline.com sea exactamente
`http://localhost:8765/callback` (ver `.env`, `ESI_SSO_CALLBACK_URL`). Guarda el
`refresh_token` en `credentials/esi_refresh_token.txt` (gitignored).

Scope actual (`.env`, `ESI_SSO_SCOPES`): `esi-wallet.read_character_wallet.v1` (10% ISK →
volumen por ítem) + `esi-markets.read_character_orders.v1` (undercut y órdenes
completadas/expiradas/canceladas — alertas de Telegram) + `esi-ui.open_window.v1` (botón
"Abrir en cliente EVE" en la PWA). Si cambiás `ESI_SSO_SCOPES`, corré `authorize.py` de
nuevo para que el `refresh_token` cubra el scope nuevo. Ampliaciones futuras documentadas
en [BACKLOG.md](BACKLOG.md) (sección Roadmap) — no pedir scopes nuevos hasta implementar
la función correspondiente (autorización incremental).

## Notificaciones y sync externos (opcionales, degradan sin bloquear el pipeline)

- **Telegram**: crear bot con @BotFather, poner `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`
  en `.env`. Sin configurar, simplemente no se envían alertas.
- **Google Sheets**: poner `GOOGLE_SERVICE_ACCOUNT_JSON` en `.env` apuntando a una
  service account con acceso al Sheet "EveCalculator - Registro". Sin configurar, cada
  fila queda pendiente en `reporting/pending_gsheets_sync.log` (nunca se pierde,
  se puede sincronizar después).

## Backup de la base de datos (D10)

`scripts/backup_db.sh` corre por cron en la VM (03:17 UTC, ver `scripts/setup_cron.sh`)
y sube un dump comprimido de `storage/market.db` a un bucket de Oracle Object Storage
vía una Pre-Authenticated Request (PAR) de solo-escritura — así, aunque la VM se
pierda o se corrompa, no hay que repetir la ingesta masiva de ~19K ítems desde cero
(ver D12). Una Lifecycle Policy del propio bucket borra automáticamente los backups de
más de 60 días — el script no maneja retención, solo sube.

**Setup inicial (una sola vez, Oracle Cloud Console):**
1. Storage → Buckets → Create Bucket (ej. `evemarket-backups`, tier Standard).
2. Adentro del bucket → Pre-Authenticated Requests → Create Pre-Authenticated Request:
   PAR Target = `Bucket`, Access Type = `Permit object writes`, una fecha de
   vencimiento lejana (ej. 1-2 años, y agendarse renovarla antes de que expire).
   Oracle muestra la URL **una sola vez** — copiarla al toque, no se puede volver a
   ver después (si se pierde, hay que crear una PAR nueva).
3. Bucket → Lifecycle Policy Rules → Create Rule: Action = `Delete`, Time period =
   `60 days` (retención acordada con el usuario).
4. En la VM, agregar la URL copiada en el paso 2 a `.env` (`ORACLE_BACKUP_PAR_URL=...`,
   terminada en `/o/` tal como la da Oracle) — nunca pegarla en el chat ni commitearla,
   es un secreto de escritura sobre el bucket.
5. `chmod +x scripts/backup_db.sh` y re-correr `scripts/setup_cron.sh` para instalar
   la entrada nueva del cron.

**Restaurar un backup:**
1. Descargar el objeto (`market-YYYY-MM-DD.db.gz`) desde la consola de Oracle Object
   Storage (el PAR de este script es de solo-escritura, no sirve para bajarlo).
2. `gunzip market-YYYY-MM-DD.db.gz`.
3. Con los motores/la API detenidos (`docker compose down`), reemplazar
   `storage/market.db` por el archivo restaurado, o inspeccionarlo aparte primero con
   `sqlite3 market-YYYY-MM-DD.db ".tables"` si se quiere verificar antes de pisar la
   base en uso.

## Monitoreo continuo (D11)

Dos capas complementarias — ninguna reemplaza a la otra:

**1. Watchdog en la VM — `scripts/healthcheck.sh`** (cron cada 10 min, ver
`scripts/setup_cron.sh`; re-correr ese script para instalar la entrada). Detecta lo que
un ping externo no ve: la API responde pero los motores dejaron de correr. Chequea:
- la API responde en `http://127.0.0.1:8001/api/summary`;
- `last_evaluated_at` (motor de mercado) tiene menos de 5 h;
- el log de hoy del motor de posiciones se tocó hace menos de 20 min;
- el servicio systemd `cloudflared` está activo.

Avisa por Telegram (mismas variables del `.env` que el resto) solo cuando el estado
cambia: falla nueva, cambio de motivo, o recuperación (✅). El último estado queda en
`.healthcheck.state`. Umbrales sobreescribibles con `MARKET_MAX_AGE_HOURS`,
`POSITIONS_MAX_AGE_MIN`, `HEALTH_URL`. Para probarlo a mano: `./scripts/healthcheck.sh`
(silencioso si todo está bien).

**2. Ping externo — UptimeRobot (plan gratis, setup manual una sola vez).** Cubre lo que
el watchdog no puede ver porque corre en la misma VM: VM entera caída, túnel o DNS rotos.
1. Crear cuenta en uptimerobot.com → Add New Monitor → tipo `HTTP(s)`.
2. URL: la pública de la app (`https://<dominio>/api/summary`), intervalo 5 min.
3. Alert Contacts: agregar el email (o el bot de Telegram) donde se quiera recibir el aviso.

## Datos

- `storage/market.db` — SQLite: histórico, snapshots, clasificación vigente por ítem
  (`item_status`), historial de cambios de estado (`item_status_history`), log de
  evaluaciones (`opportunity_log`).
- `reporting/eve-calculator-registro.xlsx` — registro acumulativo de oportunidades
  POTENCIAL (append-only, con fórmulas de Excel).

**Nota de calidad de datos:** las filas del Excel/Sheets/`opportunity_log` generadas
ANTES del filtro de sanidad (`analytics/sanity.py`, agregado 2026-09-18) pueden tener
spreads irreales por órdenes basura de mercado. Corridas posteriores a esa fecha ya
están filtradas correctamente.

## Verificación

```bash
python -m pytest tests/ -q
python -m ruff check .
python -m pip_audit -r requirements.txt
npm --prefix frontend/app audit --audit-level=high
```
