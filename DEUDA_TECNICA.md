# Deuda técnica

Inventario de deuda técnica y de proceso detectado en el proyecto (auditoría del
2026-09-21). Es un registro, no un plan de ataque — se ataca cuando el usuario lo pida
explícitamente, igual que BACKLOG.md.

Prioridad:
- **Alta**: riesgo de correctness/negocio o de romper la superficie principal sin que
  nadie se entere.
- **Media**: riesgo real pero acotado, o gap de proceso que depende de disciplina manual.
- **Baja**: cosmético o de limpieza, sin riesgo funcional.

---

### D1. ~~Sizing wallet-aware no descuenta capital ya comprometido~~ (hecho) — **Alta**
Diagnóstico original: el 10% del wallet sugerido se calcula sobre el wallet TOTAL, sin
restar lo comprometido en órdenes de compra abiertas ni en otras oportunidades de la
misma corrida.

Al diseñarlo con el usuario, dos correcciones importantes:
1. **El wallet de la ESI ya viene neto de órdenes de compra abiertas** — en EVE el ISK
   de una orden de compra se escrowa al instante al crearla (las de venta escrowan el
   ítem, no ISK). No hacía falta restar `character_order` por separado — esa mitad del
   diagnóstico original era incorrecta.
2. El usuario rechazó explícitamente repartir presupuesto algorítmicamente entre
   oportunidades simultáneas de una corrida. Lo que pidió: que toda recomendación
   mostrada se calcule contra el ISK actual, y que comprar algo en EVE se refleje sin
   esperar a la próxima corrida de 4h.

Implementado: `GET /api/items/{type_id}` ahora recalcula `recomendacion`/
`unidades_sugeridas`/`volumen_deseado` al vuelo con un wallet recién pedido a la ESI
(campo nuevo `live_recommendation`), en vez de devolver el valor guardado de la última
corrida del motor de mercado. La clasificación (POTENCIAL/DESCARTADO) sigue viniendo
del motor de 4h, sin tocar — son conceptos distintos. `resolve_volumen_deseado` y
`_config_from_settings` (antes en `scheduler/run.py`, sin tests) se movieron a
`analytics/eve_calculator.py` para que el backend no importe helpers privados de
`scheduler` — de paso quedaron testeadas (6 tests nuevos).

### D2. ~~Sin tests para la superficie REST~~ (hecho) — **Alta**
Diagnóstico original: cero cobertura automatizada sobre `/api/items`, `/api/summary`,
`/api/schedule`, `/api/character-orders/*`, `/api/settings/*`, etc. — la capa de la
que depende directamente el frontend, sin que `pytest` agarrara una regresión ahí.

Resuelto con `tests/conftest.py` (fixture `client`: `TestClient` + DB temporal por
test, más el helper `seed_item`) y dos archivos nuevos:
- `tests/test_api_main.py`: toda la superficie pública de `backend/api/main.py` —
  `/api/summary`, `/api/schedule`, `/api/items` (filtros, orden, límites inválidos,
  paginación), `/api/categories`, `/api/items/{id}` (404, historial, snapshot,
  ausencia de `live_recommendation`), `/api/status-changes`.
- `tests/test_api_private.py`: el chequeo de header de `/api/private/*` sobre cada
  ruta, más el comportamiento real de cada una una vez pasado ese chequeo —
  wallet, recomendación en vivo, órdenes/cierres/fills, CRUD de ajustes (incluida la
  validación de valores negativos/estrictamente positivos), y `refresh`/
  `open-in-client` (mockeando `check_character_orders`/`EsiClient` para no pegarle a
  la ESI real).

Ya corre como parte de `ci.yml` sin tocar nada — el job `backend` ya ejecuta
`pytest -q` en cada push/PR a `main`, así que estos tests quedan en el gate de
CI/CD automáticamente.

### D3. ~~Sin tests para la orquestación de los motores~~ (hecho) — **Media**
Diagnóstico original: `scheduler/run.py` (motor de mercado) y `scheduler/orders_run.py`
(motor de posiciones) no tenían test propio — llaman a funciones puras que sí están
testeadas (`analytics/*`), pero la orquestación en sí (qué se persiste, cuándo se
dispara cada evento, el flag `notify`) solo se verificaba a mano.

Resuelto con `tests/test_scheduler_run.py` (nuevo) y una extensión de
`tests/test_orders_run.py`, mockeando las funciones puras (`classify`,
`is_price_sane`) y los side effects externos (ESI, Telegram) para aislar solo la
orquestación:
- `ingest()`: persiste `item_type`/`market_snapshot` para cada tipo activo, y
  `market_history` completo en `--backfill` vs. solo el punto más reciente en una
  corrida normal.
- `ingest_categories()`: saltea ítems ya cacheados, y reusa el cache de
  grupo→categoría dentro de una misma corrida (no repite `get_group()` para ítems
  del mismo grupo).
- `screen_opportunities()`: persiste `opportunity_log`/`item_status`; solo agrega una
  fila a `item_status_history` cuando el status realmente cambia (no en cada
  corrida); solo dispara `NewOpportunity` la primera vez que un ítem pasa a
  POTENCIAL, no en corridas subsiguientes donde ya lo era; `is_price_sane=False`
  fuerza DESCARTADO sin importar lo que diga `classify()`.
- `check_character_orders()`: retorno inmediato sin sesión ESI (sin tocar el
  cliente); `PositionChanged` se dispara solo cuando aparece/cambia un undercut, no
  en la corrida que solo establece la posición inicial; `notify=False` nunca llama a
  `dispatch()` aunque haya eventos reales (fill parcial incluido); cierre de orden
  infiere "completada" cuando `volume_remain` llegó a 0 y desaparece de las activas,
  y "cancelada" cuando el historial de la ESI así lo marca.

### D4. ~~Sin tests para `storage/db.py`~~ (hecho) — **Media**
Diagnóstico original: migraciones, seed de defaults, y el CRUD de `app_settings`
(get/update/reset) no tenían test dedicado — se verificaron a mano vía la API cuando
se implementó T9, sin regresión automática si algo se rompía.

Resuelto con `tests/test_storage_db.py` (nuevo):
- **Seed de defaults**: `init_db()` siembra exactamente los valores de
  `storage/settings_registry.py`, y una segunda corrida no pisa un valor ya editado
  por el usuario (solo refresca `default_value`/`label`/`category` — `_seed_defaults()`
  usa `INSERT OR IGNORE` para `value` a propósito).
- **Migraciones** (`_migrate_schema`, `_migrate_classification_settings`, ambas
  probadas directamente, no solo a través de `init_db()`): agregan las columnas que
  faltan en `market_snapshot`/`character_order` sobre una tabla vieja; dropean
  `item_status` cuando el CHECK constraint no tiene `POTENCIAL_SIN_ORDENES`; son
  no-op sobre una DB ya al día (no duplican columnas ni fallan); la vieja tabla
  `classification_settings` traspasa sus valores a `app_settings` antes de borrarse.
- **CRUD de `app_settings`**: `get_app_settings_dict`, `update_app_setting`
  (persiste, y `KeyError` para una key inexistente), `reset_app_settings` (todos los
  parámetros vs. una lista explícita de keys).
- De paso, un par de helpers que no tenían ningún test directo:
  `upsert_item_type` (update on conflict), `get_cached_group` (None si no está
  cacheado), y que `get_connection()` deja las foreign keys realmente activas.

### D5. ~~Sin CI~~ (hecho) — **Media**
No había `.github/workflows` ni ningún otro pipeline — `pytest`, `ruff` y `npm run build`
solo corrían cuando se ejecutaban manualmente en una sesión de trabajo.

Resuelto como parte de T5 (subir la app a internet, ver BACKLOG.md): el repo ahora
vive en GitHub (`SukunaRyomenDev/EveMarket-Analyzer-Trading-Tool`, privado) y
`.github/workflows/ci.yml` corre en cada push/PR a `main` — job `backend` (`ruff
check .` + `pytest -q`) y job `frontend` (`npm run lint` con oxlint + `npm run
build`), en paralelo. De paso deja corriendo el lint del frontend en cada cambio,
cerrando también la mitad de D8.

### D6. ~~Módulos de `analytics/` sin test dedicado~~ (hecho) — **Media/Baja**
Diagnóstico original: `demand.py`, `rotation.py`, `spread.py`, `volatility.py`,
`volume.py` no tenían archivo de test propio, a diferencia del resto de `analytics/`.
**Corrección al diagnóstico**: no es que "alimenten la clasificación de ítems" —
al encararlo se confirmó que ninguno de los cinco está importado desde ningún otro
módulo del proyecto (`scheduler/run.py` usa `classify`/`eve_calculator`/`sanity`/
`market_aggregation`, no estos). Es código muerto hoy, listo para engancharse a un
ranking futuro (demanda/rotación/volatilidad/volumen por ítem) que todavía no
existe. Decisión tomada con el usuario: testear igual en vez de borrar, ya que son
funciones puras sin costo de mantenimiento real.

Resuelto con `tests/test_demand.py`, `tests/test_rotation.py`, `tests/test_spread.py`,
`tests/test_volatility.py`, `tests/test_volume.py` (nuevos). De paso, escribir el test
de `demand_summary()` con un DataFrame vacío encontró un bug real: reventaba con
`ValueError: 'type_id' is both an index level and a column label` en vez de devolver
un DataFrame vacío como el resto de los casos borde ya manejados — arreglado
agregando el mismo guard temprano (`if history.empty: return ...`) que ya tenían los
demás módulos de `analytics/`.

### D7. Dependencia muerta: `apscheduler` — **Baja**
Listada en `requirements.txt` pero no se importa en ningún lado del código — quedó de
antes de adoptar el Programador de Tareas de Windows para las corridas programadas.
Limpieza directa: sacarla de `requirements.txt`.

### D8. Lint del frontend (`oxlint`) no forma parte de la verificación habitual — **Baja**
`npm run lint` está configurado en `package.json` pero no se corría como parte del flujo
de verificación (solo `npm run build`). Al correrlo aparecen:
- 5 warnings `react(set-state-in-effect)` en `App.tsx` (líneas 168, 172, 178, 216, 291
  al cerrar T14) — patrón usado en varios `useEffect` de carga/sincronización de
  estado; no es un bug, pero React recomienda evitarlo.
- 1 warning de parámetro sin usar en `public/sw.js:16`.

### D9. ~~Puerto 8001 seguía abierto públicamente en paralelo al túnel~~ (hecho) — **Media**
Al armar el Cloudflare Tunnel (HTTPS real, ver BACKLOG.md T5) no se había cerrado el
acceso directo por HTTP a `http://141.148.60.142:8001` — seguía permitido tanto en el
NSG de Oracle como en el iptables de la VM, y el túnel no lo necesita para nada
(conecta saliente). Cerrado al implementar T14 (login): `docker-compose.yml` publica
el puerto solo en loopback (`127.0.0.1:8001:8001`), se sacó la regla de ingress del
NSG y la de iptables para el 8001 en la VM, y el health check de `deploy.yml` se movió
a correr desde dentro de la VM (antes pegaba directo a la IP pública, dependía de que
el puerto quedara abierto).

### D10. ~~Sin backup de `storage/market.db` en la VM~~ (hecho) — **Media**
Diagnóstico original: toda la base (histórico de mercado, screening, órdenes) vivía
solo en el disco de la VM — perderla implicaba repetir la ingesta masiva de ~19K
ítems desde cero (ver D12/BACKLOG.md).

Resuelto: `scripts/backup_db.sh` corre por cron todos los días a las 03:17 UTC, sube
un dump gzippeado de `market.db` (vía `sqlite3.Connection.backup()` de Python, una
foto consistente aunque los motores estén escribiendo en simultáneo) a un bucket de
Oracle Object Storage (`evemarket-backups`) mediante una Pre-Authenticated Request de
solo-escritura. Retención de 60 días manejada por una Lifecycle Policy del propio
bucket (requirió además una política de IAM — `allow service objectstorage to manage
object-family in tenancy` — sin la cual Oracle rechaza las reglas de auto-borrado con
`InsufficientServicePermissions`). Avisa por Telegram si la subida falla. Verificado
en producción de punta a punta: backup real corrido y subido (19MB), confirmado en
el bucket. Ver `OPERATIONS.md` para el procedimiento de restauración.

### D11. ~~Sin monitoreo continuo entre deploys~~ (hecho) — **Media**
Diagnóstico original: el health check de `deploy.yml` solo corre EN el momento del
deploy — si el contenedor, `cloudflared`, o el cron se caen en cualquier otro momento,
nadie se entera hasta que el usuario nota que la app no responde.

Resuelto: `scripts/healthcheck.sh` corre por cron cada 10 min en la VM y avisa por
Telegram, sin spam (solo en cambios de estado), si la API no responde, si el motor de
mercado (`last_evaluated_at` > 5 h) o el de posiciones (log sin tocar > 20 min) dejaron
de correr, o si `cloudflared` está caído. Instalado en la VM el 2026-11-03 y verificado en
producción: avisó que el motor de mercado llevaba 326 h sin correr, y mandó el aviso de
recuperación cuando la corrida terminó. Además hay un monitor de UptimeRobot sobre
`/api/summary` (cubre VM/túnel/DNS caídos). Las incidencias que lo hicieron necesario
(motores colgados desde el 20-21 de octubre) están en D19.

### D12. Reconstrucción de la VM no es reproducible — **Media**
Todo el setup de hoy (Docker, cron, `.env`/`credentials/` copiados a mano, cloudflared,
el túnel) se hizo a mano por SSH durante esta sesión — no quedó capturado en un script
único ni en un `cloud-init`/Terraform que permita recrear la VM desde cero si se
pierde. Si hay que reemplazar la VM, hay que rehacer manualmente cada paso de esta
sesión (varias horas de trabajo), no correr un solo comando.

### D13. Tags de imagen en GHCR se acumulan sin límite — **Baja**
`deploy.yml` etiqueta cada build con `:latest` Y `:<sha del commit>` (a propósito,
para poder hacer rollback manual — ver CONTRIBUTING.md), pero nada borra los tags
`:<sha>` viejos. Con el tiempo esto acumula imágenes indefinidamente en el registry.
No es urgente (el free tier de GHCR para repos privados es generoso), pero es
crecimiento sin límite sin ninguna razón real para conservar imágenes de hace meses.

### D14. Constantes de horario en `ingestion/schedule.py` desacopladas del cron real — **Baja**
`_MARKET_INTERVAL_MINUTES`/`_POSITIONS_INTERVAL_MINUTES` están hardcodeadas para
coincidir con lo que instala `scripts/setup_cron.sh` (`0 */4 * * *`, `*/5 * * * *`),
pero nada las mantiene sincronizadas automáticamente — si alguna vez se cambia el
intervalo del cron sin tocar estas constantes, `/api/schedule` va a mostrar una
cuenta regresiva que ya no coincide con la realidad, sin ningún aviso de que quedaron
desalineadas.

### D15. `latest_opportunities[].volumen_deseado` sigue siendo un valor derivado del wallet — **Baja**
Al cerrar T14 (Screener público sin login), `GET /api/items/{type_id}` quedó público a
propósito y sin `live_recommendation` (que sí era un leak en vivo, movido a
`/api/private/items/{type_id}/recommendation`). Pero `latest_opportunities` — el
histórico de hasta 20 evaluaciones pasadas del motor de 4h, que sí sigue siendo
público porque es dato de clasificación del Screener — todavía trae `volumen_deseado`
por fila, y ese campo se calculó en su momento contra el wallet real de esa corrida
(`resolve_volumen_deseado`, ver `scheduler/run.py`). Es una fuga mucho más indirecta y
stale (hasta 4h vieja) que la que este trabajo cerró, pero técnicamente un visitante
anónimo podría inferir un orden de magnitud del wallet mirando el histórico de
cualquier ítem. Fix futuro: sacar `volumen_deseado` del `OpportunityOut` usado para
`latest_opportunities` también (no del usado para la recomendación privada en vivo).

### D16. `/api/private/*` no verifica la firma del JWT de Cloudflare Access — **Media (riesgo aceptado)**
La protección real de `/api/private/*` (T14) es 100% Cloudflare Access en el borde;
`deps.require_cf_access_header` solo confirma que venga *algún* header con forma de
JWT (3 segmentos), sin validar la firma contra las claves públicas de Cloudflare ni el
email del claim. Es una red de seguridad contra "la Access Application se borró o el
path rule se rompió", no contra "la policy de Access se aflojó a permitir cualquier
email". Decisión tomada explícitamente con el usuario al planear T14: verificación
completa del JWT sumaría una dependencia nueva y código de verificación real — la
clase de superficie que el pedido original de login pedía evitar — para un proyecto
personal de un solo usuario. Aceptado como riesgo residual, no requiere volver a
preguntar salvo que cambie el contexto (ej. más de un usuario con acceso).

### D17. ~~Regla del NSG de Oracle para el puerto 8001 sigue sin sacarse~~ (hecho) — **Baja**
Al cerrar D9 (T14) se sacó la regla de iptables en la VM y se cambió
`docker-compose.yml` para publicar el 8001 solo en loopback — verificado que el
puerto ya no responde externamente. Pero la regla de ingress del **NSG/Security List
de Oracle Cloud** que permite TCP 8001 desde `0.0.0.0/0` nunca se sacó (requiere el
Oracle Cloud Console, fuera del alcance de lo que se puede hacer por SSH o desde
este repo). Hoy no representa un riesgo real — no hay nada escuchando en ese puerto
del lado del host para que la regla del NSG sirva de algo — pero es una regla de
firewall abierta sin ninguna razón, y si en el futuro algo volviera a publicar ese
puerto por error (ej. un cambio accidental en `docker-compose.yml`), el NSG dejaría
de ser la segunda barrera que debería ser. Cierre simple: Oracle Cloud Console → la
instancia → su VCN → Security List/NSG → sacar la regla de ingress para TCP 8001.

**Resuelto el 2026-11-03** con el CLI de OCI: se borraron las reglas de ingress TCP
8001 desde 0.0.0.0/0 de los dos NSG `evemarketanalyzer-NSGNSG` (la Security List por
defecto de la VCN ya no la tenía). Verificado: `https://evemarket-analyzer.online`
responde 200 y `http://<IP-de-la-VM>:8001` ya no responde.

### D18. `DeprecationWarning` de pandas en `demand.py`/`rotation.py`/`volatility.py`/`volume.py` — **Baja**
Las cuatro comparten el patrón `history.groupby("type_id", group_keys=False).apply(lambda g: g.tail(window_days))`,
que en la versión de pandas del proyecto ya avisa: *"DataFrameGroupBy.apply operated
on the grouping columns... pass `include_groups=False`"*. No es un bug hoy (los tests
nuevos de D6 pasan igual), pero en una futura versión de pandas ese comportamiento
cambia — agregar `include_groups=False` a ciegas rompería el `type_id` que el código
de después necesita (queda excluido del grupo), así que el fix real requiere revisar
cada uno de los cuatro con cuidado, no un sed masivo. Como estos módulos hoy no están
enganchados a nada (ver D6), no es urgente.


### D19. ~~Motores colgados por falta de memoria; `market.db` crecía sin límite~~ (hecho) — **Alta**
Incidente del 2026-10-20 al 2026-11-03: los dos motores quedaron colgados (el de
posiciones por un fallo de DNS sin timeout, el de mercado al cargar en pandas las tablas
`market_snapshot` y `market_history` completas) y, como el cron usa `flock -n`, cada
corrida nueva se descartaba en silencio; los datos quedaron 13 días sin actualizar.
`market.db` pesaba 1,3 GB en una VM de 954 MB de RAM con el swap lleno.

Resuelto: el screening lee solo el último snapshot por ítem y las últimas 30 filas de
histórico por ítem (PR #2); cada corrida poda los snapshots de más de
`SNAPSHOT_RETENTION_DAYS` (default 7) por lotes de filas (PR #4: la primera versión
borraba un `captured_at` por vez, recorría toda la tabla cada vez y la API devolvía 500
por `database is locked`); y la base está en modo WAL. Verificado en producción: la poda
borró 2 millones de filas en 3 min y la corrida completa terminó en ~32 min. El hueco de
histórico (20-oct a 1-nov) se rellenó con una corrida `--backfill`.
Queda como mejora opcional, no urgente: el archivo sigue ocupando 1,3 GB (borrar filas
no lo achica; un `VACUUM` con los motores parados lo reduciría) y un timeout explícito en
las llamadas a la ESI evitaría otro cuelgue como el del motor de posiciones.

### D20. Google Sheets — **Resuelta (2026-11-05)**
Nunca estuvo configurado en la VM; se eliminó la funcionalidad (`reporting/gsheets_sync.py`, `gspread`).
El registro útil son la base, el Excel y las alertas de Telegram.

---

## Chequeado y sin deuda

- **Vulnerabilidades de dependencias** (`pip-audit` sobre `requirements.txt`,
  2026-09-21): sin vulnerabilidades conocidas.
