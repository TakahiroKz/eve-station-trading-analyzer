# Estudio: inicio de sesión EVE para todos y base de datos de usuarios

Estado: **estudio para decidir** (2026-11-19). No hay código de cuentas todavía; se implementará en la fase 2 de EF-02 solo después de aprobar este documento.

## 1. Qué se quiere
Que cada jugador entre con su cuenta EVE (SSO), que el sitio lea de ESI lo imprescindible (habilidades comerciales, standings y wallet), y que con eso se calculen **sus** comisiones, **su** capital y **sus** recomendaciones: ROI, puntaje y unidades distintos para cada perfil. Además, guardar sus simulaciones y su historial.

Esto **cambia una decisión anterior** (T16/T17: «no leer skills, que cada quien las escriba»). La nueva decisión es del propietario y este estudio mide su costo y sus riesgos.

## 2. Situación actual (medida el 2026-11-19)
| Elemento | Dato |
|---|---|
| Servidor | Oracle A1.Flex, 2 OCPU, 12 GB de RAM (0,74 GB en uso; la API usa 57 MB), disco de 45 GB con 35 GB libres |
| Base | `market.db` de 1,4 GB (SQLite), con escrituras grandes del motor cada 5 min; ya hubo «database is locked» en endpoints que escriben |
| Copias | volcado diario a Oracle Object Storage, retención de 60 días |
| Borde | Cloudflare Free + túnel; Cloudflare Access protege solo `/api/private` (solo el propietario) |
| Sesión ESI | de **un solo usuario**: un refresh token en `credentials/esi_refresh_token.txt`, callback local `localhost:8765`, scope de wallet |
| Cuentas de visitantes | ninguna; las analíticas usan un ID aleatorio en el navegador con consentimiento |

## 3. Qué datos se guardarían (mínimo útil)
| Dato | Para qué | Sensibilidad | Retención |
|---|---|---|---|
| `character_id`, nombre | identificar la cuenta y mostrarla | personal (RGPD: ID seudónimo) | mientras haya cuenta; purga a los 12 meses sin uso |
| refresh token **cifrado** + scopes | pedir skills/standings/wallet sin volver a entrar | **secreto** | hasta cerrar sesión o revocar |
| niveles de Broker Relations, Accounting, Advanced Broker Relations; standings; fecha de lectura | comisiones del jugador | bajo | se sobrescribe en cada lectura (no se guarda historial) |
| último saldo del wallet y fecha | capital por defecto | personal-financiero | solo el último valor, caché de 5 min |
| simulaciones y escenarios (entradas + resultado + versión del motor + foto del perfil) | trazabilidad y comparación | bajo-medio | tope de 100 por usuario, las más antiguas se purgan |
| consentimiento (versión del texto, fecha) | cumplir RGPD | bajo | mientras haya cuenta |

**No se guarda**: contraseñas (no existen: SSO), historial de wallet, inventario, contactos, mensajes, ni nada fuera de los scopes pedidos.

Scopes mínimos: `esi-skills.read_skills.v1`, `esi-characters.read_standings.v1`, `esi-wallet.read_character_wallet.v1`. (Las órdenes abiertas, `esi-markets.read_character_orders.v1`, para el capital comprometido de EF-02.07, solo si el usuario las concede en una fase posterior.)

## 4. Costo de infraestructura

### 4.1 Almacenamiento
Por usuario: perfil ~1 KB, token cifrado ~1 KB, hasta 100 evaluaciones de ~1 KB, escenarios de ~2 KB → **0,2–0,5 MB**.

| Usuarios | Datos | ¿Cabe en los 35 GB libres? |
|---|---|---|
| 1.000 | 0,2–0,5 GB | sí, sobrado |
| 10.000 | 2–5 GB (1–2 GB con purga de inactivos) | sí |
| 100.000 | 20–50 GB | no en esta VM: habría que migrar a Postgres y ampliar disco |

### 4.2 Dónde guardarlo
| Opción | Ventajas | Inconvenientes | Veredicto |
|---|---|---|---|
| **SQLite aparte (`users.db`)** | cero servicios nuevos, copia trivial, aísla los bloqueos de escritura del motor de mercado y la filtración de usuarios de la de mercado | un solo escritor; sin réplicas | **Recomendada hasta ~50.000 usuarios** |
| Mismo `market.db` | ninguna pieza nueva | choca con las escrituras en lote del motor (bloqueos), la copia diaria de 1,4 GB arrastra datos personales, mayor radio de daño | descartada |
| Postgres en la VM | concurrencia real, réplicas, roles | +150–300 MB de RAM, copias/actualizaciones/monitorización propias, otra superficie de ataque | solo si se superan ~50.000 usuarios o se pasa a varias instancias |
| Base gestionada de pago | operación delegada | costo mensual, datos personales en otro proveedor | no justificada hoy |

### 4.3 Dinero
**≈ 0 USD adicionales**: los datos caben en la VM actual y las copias de `users.db` pesan megas (no los 1,4 GB del mercado). El costo real es **trabajo de ingeniería, seguridad y cumplimiento**, no de nube.

### 4.4 Carga sobre ESI
Sin sondeo continuo: skills y standings al iniciar sesión y una vez al día; wallet con caché de 5 min y solo cuando el usuario abre la página. Con 1.000 usuarios activos al día son ~10–20 mil llamadas diarias, frente a las ~1.000 por ciclo (288 ciclos/día) que ya hace el motor de mercado. Si ESI falla, se degrada a perfil manual y capital de referencia (nunca se bloquea el sitio).

### 4.5 CPU y memoria
Las rutas de usuario son de bajo tráfico y escritura pequeña. El recálculo personalizado del Screener (ROI por perfil) reutiliza la técnica de caché por (mercado, perfil, capital) que ya hace el puntaje: ~1,3 s la primera vez por combinación y ~55 ms después; con muchos perfiles distintos el costo sube, por eso las comisiones se **redondean a una rejilla** (perfiles equivalentes comparten caché) y hay un máximo de entradas.

## 5. Seguridad
| Riesgo | Medida |
|---|---|
| Robo de refresh tokens | cifrado en reposo con AES-GCM (clave en `.env`, rotable con re-cifrado), `users.db` con permisos 600, copias cifradas, nunca en logs ni en respuestas |
| Secuestro de sesión | cookie firmada `HttpOnly; Secure; SameSite=Lax`, rotación al iniciar sesión, expiración deslizante de 30 días, cierre = borrar token |
| CSRF / login CSRF | `state` + PKCE en el flujo OAuth; comprobación de mismo origen (ya existe) en todas las rutas que escriben |
| Suplantación de personaje | el `character_id` sale **solo** del token validado por CCP (JWT del SSO v2, verificado con las claves públicas de CCP), nunca de un parámetro |
| Abuso / fuerza bruta | límite de peticiones por IP (ya existe), límites por usuario, topes de evaluaciones y escenarios |
| Filtración de la base | mínimo de datos, sin datos financieros históricos, purga de inactivos, base separada de la de mercado |
| Cambio de clave / rotación | procedimiento documentado de re-cifrado; **ojo**: hoy tomaste la decisión de no rotar claves en desarrollo; con tokens de terceros esa decisión ya no es aceptable |

## 6. Privacidad y cumplimiento
- El ID de personaje es dato personal (RGPD; hay visitantes de DE, FR e IT). Base legal: **consentimiento** explícito al iniciar sesión, con la lista de datos y para qué se usan.
- Hay que ampliar la **política de privacidad** (hoy cubre solo analíticas) en los 5 idiomas: qué se guarda, cuánto tiempo, con quién se comparte (Cloudflare y Oracle como encargados), cómo borrar.
- Derechos: **cerrar sesión** (borra el token), **«borrar mis datos»** (borra todo de ese `character_id`), exportación de sus datos, purga automática a los 12 meses sin uso.
- CCP: registrar la aplicación de producción en el portal de desarrolladores con callback `https://evemarket-analyzer.online/api/auth/callback`, aceptar el acuerdo de licencia de desarrollador, y mantener el User-Agent con contacto. Revisar sus condiciones sobre almacenamiento de datos de ESI antes de la fase 2.

## 7. Operación
- El callback y las rutas `/api/auth/*` son **públicos**; `/api/private` sigue tras Cloudflare Access (no cambia).
- `invalid_grant` (el jugador revocó el acceso) → perfil «desactualizado», se pide volver a entrar; nunca se usan datos viejos como si fueran actuales.
- Copias: `users.db` entra en el cron de copias con su propia retención; probar la restauración.
- Monitorización: contador de inicios de sesión, errores de ESI y renovaciones de token fallidas en el control de salud.

## 8. Riesgos y decisión
| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| Fuga de tokens | baja | alto | cifrado, base aparte, mínimo de scopes, borrado |
| Cumplimiento (RGPD / CCP) | media | medio-alto | consentimiento, política, borrado, revisión de la licencia de CCP |
| Bloqueos de SQLite | baja con `users.db` aparte | medio | escrituras cortas, `busy_timeout`, nada de transacciones largas |
| Complejidad y mantenimiento | alta | medio | fases pequeñas con pruebas y auditorías |
| Dependencia de ESI/SSO | media | bajo | degradación a modo manual |

**Recomendación**: adoptar cuentas EVE para todos con **`users.db` SQLite aparte**, tokens cifrados, mínimo de scopes y consentimiento, **después** de (1) terminar y verificar el motor financiero (fases 0–1 de EF-02, que son independientes de las cuentas) y (2) aprobar este estudio, incluyendo la actualización de la política de privacidad y el registro de la app en CCP.

## 9. Preguntas abiertas para el propietario
1. ¿Se acepta que el uso del sitio **sin cuenta** siga igual (perfil manual o por defecto)? Recomendado: sí, la cuenta es opcional.
2. ¿Quién es el responsable del tratamiento de datos (nombre y contacto para la política de privacidad)?
3. ¿Se exige re-consentimiento cuando cambie la lista de datos?
4. ¿Qué retención de inactivos (propuesta: 12 meses)?
5. ¿Se aprueba abandonar la decisión de «no rotar claves» para el cifrado de tokens (propuesta: clave rotable y documentada)?

## 10. Fase 2 implementada (2026-11-19): lo que cambió respecto al diseño
- **Apagada por defecto**: se activa solo con `EVE_LOGIN_CLIENT_ID`, `EVE_LOGIN_CLIENT_SECRET` y `USERS_ENC_KEYS` (ver `OPERATIONS.md`). Sin eso el sitio no cambia.
- **Sin PKCE**: la app es un cliente confidencial (secreto en el servidor); la protección es `state` en cookie HttpOnly de 10 min, de un solo uso.
- Sesión: cookie `eve_session` (HttpOnly, SameSite=Lax, Secure tras HTTPS) con 32 bytes aleatorios; en la base solo su SHA-256; 30 días deslizantes (se prolonga como mucho 1 vez por hora).
- JWT de CCP verificado con las claves públicas (RS256, emisor, audiencia = nuestro `client_id`, expiración, sujeto `CHARACTER:EVE:<id>`); el `character_id` sale solo de ahí.
- Tokens: AES-256-GCM con el `character_id` como dato asociado; `USERS_ENC_KEYS` admite varias claves (rotación con `scripts/users_admin.py`).
- Cerrar sesión borra la sesión **y** el token; «Borrar mis datos» borra todo; exportación sin el token; `purge` para inactivos (12 meses).
- Pendiente de decisión del propietario antes de activar: responsable del tratamiento y su contacto en la política de privacidad, registro de la app en CCP y la clave de cifrado en un gestor de secretos.

## 11. Fase 3 implementada (2026-11-20): perfil y capital del jugador
- **Qué se lee de ESI** (con los 3 permisos de lectura ya pedidos en el login): niveles activos de Broker Relations (3446), Advanced Broker Relations (16597) y Accounting (16622); standings con las 4 facciones y las 5 corporaciones dueñas de las estaciones de referencia; saldo del wallet. Del listado de standings se descarta todo lo demás (agentes y el resto de corporaciones).
- **Qué se guarda** (tabla `user_profile`, esquema v2, solo lo último, sin historial): esos valores con su fecha, las correcciones manuales y el estado de la última lectura. Como cambia la lista de datos guardados, `CONSENT_VERSION` pasó a `2026-11-20` (los usuarios con sesión vuelven a consentir) y se actualizaron el diálogo y la política de privacidad en los 5 idiomas.
- **Estaciones de referencia** (`finance/hubs.py`): Jita IV-4 (Caldari Navy), Amarr VIII Emperor Family Academy, Dodixie IX Federation Navy Assembly Plant, Rens VI Brutor Tribe Treasury y Hek VIII Boundless Creation Factory. Los dueños se comprobaron contra ESI el 2026-11-20; la facción de cada corporación NPC no viene en ESI público y va fija en el código.
- **Cuándo se lee**: habilidades y standings al abrir el perfil si tienen más de 24 h (o con «Actualizar»); el saldo solo cuando se pide y con caché de 5 min; nunca menos de 5 min entre dos intentos de un mismo personaje (incluidos los fallidos). Lo anterior se conserva si ESI falla; pasadas 48 h sin lectura se avisa de que el perfil puede estar desactualizado.
- **Origen de cada valor**: `ESI` (leído), `MANUAL` (lo corrigió el jugador; gana siempre) o `DEFAULT` (sin dato: perfil por defecto del motor, igual a las constantes históricas 0,901 / 1,024). Un perfil solo es `ESI` si los seis valores lo son.
- **Fallos**: `invalid_grant` marca el token como REVOKED (hay que volver a entrar); permisos que el jugador desmarcó en el login se listan (`missing_scopes`) y esas lecturas se omiten; 5xx/timeouts/420 de ESI dan UNAVAILABLE sin tocar lo guardado.
- **Rutas** (`backend/api/me.py`, requieren sesión y consentimiento vigente, `no-store`, mismo origen en PUT/POST): `GET /api/me/profile`, `POST /api/me/profile/refresh` (429 con `Retry-After: 300`), `PUT /api/me/profile/override` (reemplaza todas las correcciones; niveles 0-5, standings -10..10, mercados conocidos), `GET /api/me/capital`.
- **Por verificar con datos reales**: si los standings que devuelve ESI ya incluyen el efecto de Connections/Diplomacy (el motor usa el valor tal cual). Hasta contrastarlo con el juego, la interfaz avisa de que el jugador lo compare y lo corrija a mano si difiere.

## 12. Fase 4 implementada (2026-11-20): simulador y escenarios
- **Libro de la estación** (`ingestion/station_book.py`): ESI público `/markets/{región}/orders/?type_id=`, filtrado por la estación de referencia del mercado, agrupado por precio (máx. 200 niveles por lado), caché de 60 s, sin reintentos largos. No modela el volumen mínimo de cada orden ni el alcance de las órdenes de compra.
- **API pública y sin estado** (`backend/api/finance.py`): `POST /api/finance/evaluate` y `POST /api/finance/compare` (2 a 6 escenarios, ranking por ROI). Perfil: `default` (constantes históricas), `manual` (el visitante escribe habilidades y standings) o `mine` (sesión: perfil de ESI con correcciones manuales; opcionalmente el saldo del wallet como capital). Entradas acotadas (unidades, precios, niveles de libro, relists) y validadas; `use_live_book` solo para estaciones NPC con `type_id`. Mismo origen en POST y `no-store`.
- **Escenarios guardados** (`users.db` esquema v3, tabla `financial_scenario`, máx. 50 por jugador): cada uno es una **foto reproducible**: la petición con el libro y el perfil realmente usados (sin consultas en vivo ni referencia al perfil actual), el resultado, `engine_version` y `rules_version`. Reevaluar la foto da el mismo resultado aunque cambien el mercado o las habilidades. Se exportan con «Descargar mis datos» y se borran al borrar la cuenta. `CONSENT_VERSION` pasó a `2026-11-20.2` porque ahora se guarda este contenido.
- **Interfaz** (`SimulatorPanel.tsx`, botón «Simulador» en la barra, 5 idiomas): búsqueda de ítem, órdenes límite o inmediatas, tipo de estación, perfil, ROI objetivo y capital; desglose de costes, precios de equilibrio y objetivo, aviso de reglas sin confirmar (R6, R8, R9) y del libro parcial; escenarios guardados y comparación.
- **Corrección de la fase 3 descubierta aquí**: el límite de 5 minutos entre intentos frenaba la lectura del saldo justo después de la del perfil (el panel pide ambas a la vez). Ahora solo frena la actualización manual repetida y los reintentos tras un fallo.

## 13. Fase 5 implementada (2026-11-20): Screener personalizado
- **Qué cambia**: con sesión y el interruptor «Usar mis comisiones» (se guarda en el navegador), `GET /api/items` y `GET /api/items/{id}` reciben `profile=mine` y devuelven el ROI, la evaluación del spread, el **estado** (POTENCIAL, EN_OBSERVACION, …), el puntaje, la elegibilidad, la recomendación y las unidades con las comisiones del jugador **en el mercado pedido** (broker fee con sus habilidades y standings en la estación de referencia de ese mercado; sales tax con su Accounting). Sin `profile=mine` todo es idéntico a antes (prueba de regresión). La respuesta lleva `profile` (fuente, broker fee y sales tax aplicados, si hay diferencia con la referencia).
- **Bandas en ROI neto**: las bandas de spread de Ajustes están en spread bruto para las comisiones de referencia (0,901 / 1,024). Se trasladan a las del jugador con `(1 + banda') = (1 + banda) · (fv₀·fc)/(fc₀·fv)`, de modo que «Pérdida», «Pequeño beneficio»… marcan el **mismo ROI neto** para cualquiera (propiedad comprobada con 400 casos aleatorios). Ejemplo con BR V, Accounting IV y standing 3: un ítem con spread 10 % sale «Descartado» con las comisiones de referencia pero con ROI neto +2,4 % para el jugador.
- **Factores del jugador** (`finance/user_profile.screener_factors`): `fv = 1 − sales_tax − broker`, `fc = 1 + broker` (órdenes límite en estación NPC, como el Screener), redondeados a 4 decimales. Con el perfil por defecto salen exactamente 0,901 y 1,024.
- **Qué no cambia**: la liquidez guardada, los mínimos de volumen y operaciones, y la detección de precios incoherentes (un ítem con precio incoherente sigue descartado). El spread bruto no depende de las comisiones. `latest_opportunities` del detalle sigue siendo el registro histórico con comisiones de referencia.
- **Filtros**: `min_roi`/`max_roi` son una condición exacta en SQL sobre los precios; `status`, `min_score`, `score_class`, `eligibility`, `recommendation` y `sort=score` recorren el mercado entero una vez por (mercado, comisiones, ciclo) con la misma caché del capital propio (ahora de 24 entradas). Un jugador con comisiones distintas de las de referencia paga ese recálculo (~1,4 s en Jita) la primera vez en cada ciclo de precios; los factores se redondean a 4 decimales para acotar las variantes.
- **Privacidad y caché**: las respuestas personales llevan `Cache-Control: private, no-store` y `Vary: Cookie` (Cloudflare no las guarda ni las sirve a otros). `profile=mine` sin sesión responde 401 (nunca cae en silencio al perfil por defecto) y 503 si las cuentas están apagadas. Se usa el perfil ya guardado; este endpoint no llama a ESI.
- **Límites**: el Screener asume órdenes límite de compra y venta y no aplica el mínimo de 100 ISK por orden ni los relists (eso es del Simulador); el ROI personal usa las comisiones de la estación NPC de referencia del mercado, no de una estructura Upwell.

## 14. Capital comprometido en órdenes (permiso `esi-markets.read_character_orders.v1`)

- **Qué se lee:** `GET /characters/{id}/orders/` (órdenes abiertas), junto con el saldo y con la misma caché de 5 minutos.
  Solo se usa el tipo de cada orden y su `escrow`; **no se guarda ninguna orden**, solo el total y los contadores
  (`committed_isk`, `buy_orders`, `sell_orders`, `orders_at` en `user_profile`, esquema v4 con `ALTER TABLE` para bases anteriores).
- **Definición:** comprometido = suma del `escrow` de las órdenes de **compra** abiertas. Las de venta no retienen ISK (son inventario).
- **Sin doble conteo:** el saldo del wallet ya descuenta el escrow, así que el **capital libre es el saldo** (lo que usa el
  Screener) y `total_isk = saldo + comprometido` se informa aparte en `/api/me/capital` y en «Mi perfil».
- **Consentimiento:** versión `2026-11-20.3` (se pide aceptar de nuevo y volver a entrar para conceder el permiso nuevo); política de
  privacidad actualizada en los 5 idiomas. Sin el permiso, el estado de sincronización es `PARTIAL` y el panel lista el permiso que falta.
