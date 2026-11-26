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
nuevo para que el `refresh_token` cubra el scope nuevo. No pedir scopes nuevos hasta implementar
la función correspondiente (autorización incremental).

## Notificaciones (opcionales, degradan sin bloquear el pipeline)

- **Telegram**: crear bot con @BotFather, poner `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`
  en `.env`. Sin configurar, simplemente no se envían alertas. Qué se avisa, siempre solo cuando
  hay novedades y sin horario fijo: (1) el estado de tus órdenes de compra y venta (te
  undercutearon, recuperaste la primera posición, ejecuciones, completadas/expiradas/canceladas) y
  (2) fallas del servicio y su recuperación (watchdog, ver más abajo). Los avisos de oportunidades
  nuevas están suspendidos: `TELEGRAM_NOTIFY_OPPORTUNITIES=1` los reactiva.
  Los avisos de los motores se envían en segundo plano (el ciclo no espera a Telegram): timeouts
  de 3 a 5 s y un reintento. Si aun así no salen, quedan en la tabla `notification_outbox` y se
  reintentan en las siguientes corridas durante 30 min (máx. 5 intentos); después se descartan con
  una línea en el log. `SELECT COUNT(*) FROM notification_outbox` dice cuántos esperan.

## Mercados (esquema por mercado)

Las tablas por mercado (`market_history`, `market_snapshot`, `item_status`, `item_status_history`,
`opportunity_log`) llevan `market_id` en la clave; `item_type`, `item_category` y los ajustes son comunes. La
tabla `market` lista los hubs (jita, amarr, dodixie, rens, hek), cada uno con su `region_id`, y `enabled` decide
cuáles analiza el sistema y cuáles acepta la API (`?market=`). Hoy cada mercado es una región, como Jita desde el
principio; `kind = system` queda para mercados de un solo sistema (arbitraje) sin cambiar el esquema.

**Migración desde el esquema anterior** (una sola vez, `init_db` la hace sola y es atómica): renombra las cinco tablas
a `*_pre_market`, crea las nuevas y copia todo con `market_id = jita`; si los conteos no coinciden, revierte. En la
base de producción (2 GB) tardó 88 s y quedó idéntica (conteos y sumas). Las copias `*_pre_market` se conservan hasta
verificar; luego se borran y se compacta:

```
python -c "from storage.db import get_connection, drop_pre_market_tables; c = get_connection(storage/market.db); print(drop_pre_market_tables(c)); c.execute(VACUUM)"
```

Hacerla con los motores y el cron pausados (el VACUUM tarda ~70 s y bloquea la escritura).

### Activar un mercado nuevo

El motor (`scheduler/run.py`) procesa los mercados con `enabled = 1` en la tabla `market`, uno tras otro y
aislados (si uno falla, los demás siguen y el fallo queda en el log). Para sumar uno (p. ej. amarr), de a uno:

1. Rellenar su histórico sin activarlo (tarda varios minutos; guarda solo los últimos 120 días):
   `docker compose --profile cron run --rm engine-history python -m scheduler.run --history-only --backfill --history-days 120 --markets amarr`
2. Un ciclo de precios a mano para ese mercado y revisar el resultado:
   `flock -n .market.lock docker compose --profile cron run --rm engine-market python -m scheduler.run --prices-only --markets amarr`
3. Activarlo: `UPDATE market SET enabled = 1 WHERE market_id = amarr` (con `docker exec evemarket-api python -c` y
   `sqlite3`). Desde ahí entra en cada ciclo y la API lo acepta con `?market=amarr`.
   Para desactivarlo, `enabled = 0` (los datos se conservan).

### Estado y medidas (2026-11-18)

Los cinco mercados están activos. Medido en producción (VM A1, 12 GB): relleno de histórico de 120 días
8,4 min (Amarr), 7 min (Dodixie), 5,5 min (Rens), 6,2 min (Hek); ciclo de precios por mercado: Jita ~35 s,
Amarr ~14 s, Dodixie ~10 s, Rens ~7 s, Hek ~9 s, es decir ~80 s con los cinco (el watchdog avisa por encima
de 4 min). La base pasó de 991 MB a 1,05 GB con el histórico de los cuatro mercados nuevos. El watchdog
(`scripts/healthcheck.sh`, chequeo 2b) revisa además `last_evaluated_at` de cada mercado activo en
`/api/markets` y avisa cuáles se atrasan.

## Tamaño de la base de datos

`opportunity_log` crecía una fila por ítem y por ciclo (~4,7 millones al día con ciclos de 5 min) hasta
ocupar el 75 % de la base. Ahora cada ítem se anota como mucho una vez por hora (cada 12 h si está
DESCARTADO) o al cambiar de estado, y se purga lo de más de 3 días (`OPPORTUNITY_LOG_*` en `.env`). El
archivo no encoge solo al borrar filas: tras una purga grande hay que correr un `VACUUM` con los motores
pausados (ver el procedimiento en el historial de la PR).

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
- `last_evaluated_at` (motor de mercado, ciclo de precios cada 5 min) tiene menos de 15 min;
- el log de hoy del motor de posiciones se tocó hace menos de 20 min;
- el servicio systemd `cloudflared` está activo;
- el ciclo de mercado no dura demasiado: avisa si hay uno corriendo hace más de 4 min o si el último
  tardó más de 4 min (un ciclo de precios normal tarda unos 35 s; ver `MARKET_MAX_RUN_MIN`);
- el histórico diario (`history_*.log`) se tocó hace menos de 36 h (`HISTORY_MAX_AGE_HOURS`);
- a partir de las 13:00 UTC (`HISTORY_DATA_CHECK_HOUR`), cada mercado activo tiene en `market_history` el día
  de ayer (el log se toca aunque la corrida falle, así que solo mirar el log no detecta un día perdido). Si un
  mercado acumula 2 días o más de retraso, el aviso escala con otro texto («histórico de mercado con 2 días o
  más de retraso en: …»), que llega como aviso nuevo; al recuperarse llega el ✅ de siempre;
- una vez al día, desde las 14:00 UTC (`CLASSIFICATION_AUDIT_HOUR`), la auditoría de clasificación
  (`scripts/audit_classification.py`, solo lectura, dentro del contenedor de la API): avisa si hay filas de
  `item_status` que el último ciclo no evaluó o estados que contradicen sus datos. El resultado del día queda
  en `.classification_audit.state` y el informe en `logs/classification_audit.json`; el aviso sigue hasta la
  auditoría siguiente. A mano: `docker exec -i evemarket-api python - --wallet <ISK del log> <
  scripts/audit_classification.py` (`--strict-raw` compara también con el recálculo desde los datos crudos).

**Histórico diario con reintentos y reparación.** El cron lo lanza **cada hora, todo el día** (minuto 35).
`--history-only` omite los mercados cuyo último día publicado ya está completo (`history_is_current`: la ESI
publica el día D-1 a las 11:05 UTC, y la cobertura debe ser ≥ 90 % de los tipos del día anterior), así que
tras una corrida buena las demás no hacen nada y las de madrugada no repiten trabajo. Si la ESI cae (503),
la siguiente hora lo reintenta, aunque el corte dure días: cada corrida guarda todas las filas posteriores a
la última fecha de cada tipo, y si detecta días sin datos en los últimos 30 (`history_gaps`: día vacío o con
menos de la mitad de la cobertura mediana) rellena solo desde el primer hueco (`--backfill` automático).
Auditoría a mano (solo lectura, no llama a la ESI; sale con código 1 si hay huecos):
`docker compose --profile cron run --rm engine-history python -m scheduler.run --audit-history`.
Incidente 2026-11-18: la ESI devolvió 503 a las 11:35 UTC, el único intento falló y el 17-nov quedó sin datos
(recuperado con `--history-only --backfill --history-days 5`). Lo que NO se recupera de un corte son los
snapshots de precios (la ESI solo da el libro actual): hay un hueco en la tendencia y la profundidad.

Avisa por Telegram (mismas variables del `.env` que el resto) solo cuando el estado
cambia: falla nueva, cambio de motivo, o recuperación (✅). El último estado queda en
`.healthcheck.state`. Umbrales sobreescribibles con `MARKET_MAX_AGE_MIN`,
`POSITIONS_MAX_AGE_MIN`, `MARKET_MAX_RUN_MIN`, `HISTORY_MAX_AGE_HOURS`, `HEALTH_URL`. Para probarlo a mano: `./scripts/healthcheck.sh`
(silencioso si todo está bien).

**2. Ping externo — UptimeRobot (plan gratis, setup manual una sola vez).** Cubre lo que
el watchdog no puede ver porque corre en la misma VM: VM entera caída, túnel o DNS rotos.
1. Crear cuenta en uptimerobot.com → Add New Monitor → tipo `HTTP(s)`.
2. URL: la pública de la app (`https://<dominio>/api/summary`), intervalo 5 min.
3. Alert Contacts: agregar el email (o el bot de Telegram) donde se quiera recibir el aviso.

## Donaciones (botón de PayPal + página de agradecimiento)

- El link de donación va en `frontend/app/src/config.ts` (`DONATE_URL`); vacío = no se
  muestra ningún botón. Es un link público, no un secreto.
- **Página de agradecimiento:** la app la muestra en `https://evemarket-analyzer.online/?gracias=1`.
  Para que PayPal mande ahí al donante al terminar: PayPal → Herramientas → botones
  Donar → editar el botón → "Después de donar, redirigir a" → esa URL. Funciona solo con
  el botón Donar (cuenta Business); **PayPal.me no permite redirección**, así que con
  ese link el donante se queda en PayPal.
- La página no confirma el pago (cualquiera con la URL puede abrirla); es solo un
  agradecimiento. Si algún día hace falta confirmar donaciones, hay que usar webhooks de
  PayPal, que es otro trabajo.

## Frontend: idiomas por ruta, SEO y desarrollo local

- **Un HTML por idioma.** `npm run build` genera `dist/index.html` (inglés) y
  `dist/{es,de,fr,it}/index.html` (plugin `language-pages` en `frontend/app/vite.config.ts`),
  cada uno con su `<title>`, descripción, `canonical`, `hreflang`, Open Graph y bloque
  `<noscript>` en su idioma, más un `manifest.json` localizado por idioma. La API los sirve con
  el mismo `StaticFiles(html=True)` de siempre (`/es/` → `es/index.html`). Los textos salen de
  `src/i18n/*.ts`: una clave nueva se agrega en los cinco archivos o no compila.
- **La app elige el idioma así:** ruta (`/es/`) > `?lang=xx` (formato viejo: se reescribe a
  `/es/` al cargar) > elección guardada > idioma del navegador > inglés. Cambiar de idioma en
  el selector cambia la URL.
- **Fuentes propias:** Space Grotesk e IBM Plex Mono vienen de `@fontsource/*` (versión fija en
  `package.json`), ya no de Google Fonts.
- **`og-image.png`** (1200×630) está dibujada a mano; no se regenera sola. Si cambia la marca o
  el lema, hay que rehacerla.
- **Desarrollo local contra producción:** poner `API_PROXY=https://evemarket-analyzer.online`
  en `frontend/app/.env` (no se versiona) para que `npm run dev` use la API de producción sin
  levantar el backend. Solo sirve para endpoints públicos; los privados piden login de Access.

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

## Cuentas de visitantes (EVE SSO)

Apagadas hasta que existan `EVE_LOGIN_CLIENT_ID`, `EVE_LOGIN_CLIENT_SECRET` y `USERS_ENC_KEYS` en `.env` (ver `.env.example`).
Mientras tanto `/api/auth/status` responde `enabled:false`, el botón no aparece y el resto del sitio no cambia.

**Activarlas (una vez):**
1. Registrar la aplicación en https://developers.eveonline.com (callback `https://evemarket-analyzer.online/api/auth/callback`,
   scopes `esi-skills.read_skills.v1`, `esi-characters.read_standings.v1`, `esi-wallet.read_character_wallet.v1`). Es una app
   distinta de la local del propietario (`ESI_SSO_*`).
2. `python scripts/users_admin.py genkey` → `USERS_ENC_KEYS`; copiar también a un gestor de secretos: **sin la clave no se pueden
   leer los tokens** (los usuarios tendrían que volver a entrar).
3. Reiniciar la API (`docker compose up -d api`). `users.db` se crea en `storage/` con permisos 600.

**Mantenimiento:** `python scripts/users_admin.py purge` (sesiones caducadas y usuarios sin uso en 12 meses; conviene un cron
diario) y `rotate` tras anteponer una clave nueva. `users.db` entra en la copia diaria (`backup_db.sh`) como `users-AAAA-MM-DD.db.gz`.
Borrado a petición: el usuario lo hace desde el menú de la cuenta (`DELETE /api/auth/me`).

Nota: las copias diarias conservan 60 días; un usuario que borra sus datos desaparece de las copias al caducar (menos de 60 días).
