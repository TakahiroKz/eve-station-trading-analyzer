# Flujo de trabajo de este repo

Adaptación de un framework de "sistema multi-agente" (Orchestrator/Backend/Frontend/QA
con gates formales) que el usuario trajo para este proyecto. La versión completa está
pensada para un equipo con agentes genuinamente independientes y varios ambientes —
acá hay un solo agente (Claude Code) trabajando con un solo usuario en una sesión
continua. Este documento es la adaptación honesta: lo que se aplicó tal cual, lo que
se aproximó de otra forma, y lo que se descartó explícitamente y por qué. Decidido en
conjunto con el usuario, no impuesto.

## Branching

```
feature/<ID>-<descripcion>   # funcionalidad nueva
fix/<ID>-<descripcion>       # corrección de bug
hotfix/<ID>-<descripcion>    # incidente crítico de producción
```

`<ID>` es el número de issue cuando el cambio viene de uno (ej. `feature/12-ci-cd`);
si no tiene número, una descripción corta alcanza.
Nunca se commitea directo a una rama tipo `backend`/`frontend`/`qa` — cada cambio
funcional tiene su propia rama, se mergea, se borra.

## `main` está protegida — por disciplina, no por GitHub

**Importante:** GitHub Free no permite branch protection real (clásica ni Rulesets)
en repos privados — pide GitHub Pro o el repo público. El usuario decidió mantener el
repo privado y sin pagar Pro (decisión del 2026-09-22), así que
esta regla **no está aplicada por GitHub**, es un compromiso que el agente sigue:

- Nunca push directo a `main`.
- Nunca force-push.
- Todo cambio entra por Pull Request.
- Nunca mergear con el CI en rojo.

Si en algún momento el repo pasa a público o a GitHub Pro, esto debe convertirse en
reglas reales de GitHub (branch protection / rulesets) — la disciplina manual queda
como piso mínimo, no como solución definitiva.

## CI (`.github/workflows/ci.yml`)

Corre en cada push y en cada PR contra `main`:

```
push / PR
   ├─ backend:  ruff check  →  pytest  →  pip-audit
   └─ frontend: oxlint      →  npm audit  →  tsc + vite build
```

Si cualquier paso falla, el PR no está listo para mergear — no importa lo que diga el
agente sobre si "funciona".

## QA — revisión independiente, no autoaprobación

El framework original exige que el mismo agente no pueda implementar y validar su
propio cambio. Con un solo agente en una sola sesión, "simular" un QA Agent separado
sería la misma sesión revisándose a sí misma — no aporta independencia real.

La aproximación honesta que se usa acá: antes de recomendar el merge de un cambio no
trivial, se spawnea un subagente de revisión (`code-review`/`Agent` tool) en un
contexto separado, que no vio el razonamiento de la implementación — revisa el diff
en frío y reporta hallazgos. No aprueba/rechaza el PR por sí solo; la decisión final
la toma el usuario (o el agente principal) con esa evidencia como input, no como
sustituto del criterio humano.

## Aprobación humana explícita

Se pide confirmación explícita del usuario antes de (lista adaptada de la sección 16
del documento original):

- Cambios de seguridad, autenticación o autorización.
- Cambios de infraestructura (VM, DNS, secrets, CI/CD).
- Migraciones destructivas o eliminación de datos.
- Cambios incompatibles de API.
- Cualquier acción irreversible o visible fuera de este entorno local (push, deploy,
  mensajes a terceros).

Esto ya es como el agente viene operando en este proyecto — este documento solo lo
deja explícito para el repo, no es un comportamiento nuevo.

## CD (`.github/workflows/deploy.yml`)

Solo dispara con push a `main` (nunca en PR). Un ambiente único (la VM de Oracle) —
no hay DEV/staging separados; decisión explícita para no duplicar infraestructura
para un proyecto de un solo usuario.

```
push a main
   ↓
build-and-push  (imagen a GHCR, tags :latest y :<sha>)
   ↓
deploy          (SSH a la VM: git pull, docker compose pull, up -d api)
   ↓
health check    (10 intentos, 5s c/u, contra /api/summary)
   ↓
falla el health check → DEPLOYMENT_FAILED, el workflow queda en rojo
```

**Rollback**: no automático. Cada imagen queda etiquetada con el SHA del commit — si
`:latest` resulta con un bug, entrar por SSH y correr
`docker compose up -d api` apuntando a un tag `:<sha-anterior>` a mano en
`docker-compose.yml`, o revertir el commit en `main` y dejar que el CD normal
redespliegue.

## Hotfix

Para un incidente en producción: rama `hotfix/<ID>-descripcion` desde `main`, PR
directo (sin pasar por una rama de desarrollo intermedia), mismo CI, mismo criterio de
aprobación humana para cambios de riesgo — el CD ya despliega apenas se mergea a
`main`, no hace falta un paso extra.

## Lo que se descartó del framework original, y por qué

- **Ambientes DEV/QA-Staging/Production separados**: técnicamente viable (Oracle Free
  Tier permite una segunda VM gratis), pero de bajo valor para un usuario único que
  nota en minutos si algo se rompe — se prefirió invertir ese esfuerzo en el health
  check post-deploy en vez de mantener una VM extra.
- **Máquina de estados formal** (PLANNED→ASSIGNED→...→VERIFIED con board/automatización):
  infraestructura de coordinación de equipo. los issues y los PR ya cumplen ese rol de forma liviana para un solo desarrollador.
- **Simular roles Orchestrator/Backend/Frontend/QA** en la misma sesión: se descartó
  explícitamente por no aportar independencia real (ver sección QA arriba).
