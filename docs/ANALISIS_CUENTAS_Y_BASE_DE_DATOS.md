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
