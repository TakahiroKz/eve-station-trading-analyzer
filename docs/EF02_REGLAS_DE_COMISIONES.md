# EF-02 — Reglas de comisiones e impuestos: fuentes y estado de verificación

Versión de las reglas del motor: `2026-11-19.1` (`finance/rules.py`). Cada regla lleva su **fuente** y un **estado**:

- **CONFIRMADA**: coinciden al menos dos fuentes independientes y encaja con la especificación EF-02.
- **DISCREPANTE**: las fuentes se contradicen; el motor usa el valor indicado, lo marca y emite una advertencia (`UNVERIFIED_RULE`) cada vez que ese valor interviene en un resultado.
- **SUPUESTO**: no hay fuente que lo afirme ni lo niegue; es un supuesto de modelado documentado.

Fuentes consultadas el 2026-11-19: [EVE University — Trading](https://wiki.eveuniversity.org/Trading) (EVEU), [CCP — Broker Relations](https://www.eveonline.com/news/view/broker-relations) (CCP 2020), la especificación EF-02 (SPEC) y la búsqueda general en el archivo de foros oficiales (los foros contienen fórmulas multiplicativas antiguas, hoy obsoletas).

## Reglas

| ID | Regla | Valor por defecto | Fuentes | Estado |
|---|---|---|---|---|
| R1 | Broker fee en estación NPC = 3 % − 0,3 % × nivel de Broker Relations − 0,03 % × standing de facción − 0,02 % × standing de corporación | base 3 %, 0,3 %/nivel, 0,03 %, 0,02 % | EVEU, SPEC | CONFIRMADA |
| R2 | Los standings son los **sin modificar** (las habilidades que los suben no cuentan) y van de −10 a +10 | — | EVEU | CONFIRMADA |
| R3 | Suelo del broker fee NPC en % | 1 % (no lo alcanza nadie con standings ≤ 10: BR V + 10 + 10 da justo 1,0 %) | SPEC | SUPUESTO (inofensivo) |
| R4 | Cobro mínimo de una orden (creación o modificación) | 100 ISK | EVEU, CCP 2020, SPEC | CONFIRMADA |
| R5 | Sales tax = 7,5 % × (1 − 0,11 × nivel de Accounting) (Accounting V ≈ 3,375 %). Sube de 4 % a 7,5 % en la versión 22.02 (marzo de 2025) | base 7,5 %, 11 %/nivel | EVEU, SPEC | CONFIRMADA (EVEU cita además un «8 %» en otro apartado: texto sin actualizar) |
| R6 | Broker fee en estructura Upwell = recargo SCC fijo 0,5 % + % que fija el dueño; **Broker Relations y los standings no lo reducen** | SCC 0,5 % + % del dueño (dato obligatorio) | EVEU, SPEC | DISCREPANTE: CCP 2020 dice que el mínimo del dueño es 1 % y que la mitad va a la SCC; EVEU dice mínimo 0 % y 0,5 % + dueño |
| R7 | Cobro al modificar una orden de P1 a P2 = max(0, BR × (P2 − P1)) + (1 − RD) × BR × P2 | fórmula | CCP 2020, EVEU, SPEC | CONFIRMADA (fórmula) |
| R8 | Descuento de relist RD = 50 % + K × nivel de Advanced Broker Relations | 50 % base; **K = 6 puntos/nivel** (≈ 80 % en nivel V) | EVEU (6 %, cita un cambio de 2021), CCP 2020 (5 %: 75 % en nivel V) | DISCREPANTE |
| R9 | Una compra inmediata (a órdenes existentes) **no paga broker fee**; una venta inmediata paga sales tax y tampoco broker fee | — | SPEC, mecánica del juego | SUPUESTO (a verificar en juego) |
| R10 | Las órdenes de compra reservan el 100 % de su valor en escrow; el broker fee se paga al crear la orden, **no se devuelve** aunque no se complete, y no forma parte del escrow | — | CCP 2020 (escrow del 100 %) | CONFIRMADA (escrow) / SUPUESTO (el fee fuera del escrow) |
| R11 | Redondeo de importes a 0,01 ISK (mitad hacia arriba) | 2 decimales | — | SUPUESTO |
| R12 | Una orden de compra del jugador puede pagar su precio de **estación**; el motor no filtra por rango de órdenes de otros jugadores salvo que el libro llegue con su rango | — | — | SUPUESTO |

## Contradicciones abiertas y qué las resuelve

1. **R6** (Upwell, mínimo del dueño: 0,5 % o 1 % en total) y **R8** (5 o 6 puntos por nivel) se resuelven con una lectura real de la ventana de órdenes del juego.
2. **R5**: si el sales tax base fuera 8 % en vez de 7,5 %, el perfil por defecto del proyecto (0,901) no coincidiría con el juego: 1 − 0,08 − 0,024 = 0,896. Una lectura real lo confirma.
3. **R1**: una de las fuentes de CCP dice que el broker fee NPC va «del 3 % al 5 %»; la fórmula con base 3 % no puede dar más de 3 % (sin skills y con standing 0). Una lectura real con un personaje sin skills lo aclara.

### Lecturas reales que necesito para cerrar la versión 1.0 de las reglas

Para cada una, abre la ventana de crear una orden (o modificarla) en el juego y anota los valores que muestra:

| # | Escenario | Qué anotar |
|---|---|---|
| V1 | Estación NPC, personaje con **Broker Relations 0, Accounting 0** y standings en 0 | broker fee % de compra, broker fee % de venta, sales tax % |
| V2 | Estación NPC, **Broker Relations V y Accounting V**, standings en 0 | los mismos tres valores |
| V3 | Estación NPC, con **standings conocidos** de facción y corporación (con su Broker Relations) | broker fee % y los dos standings sin modificar |
| V4 | Una **estructura Upwell** donde sepas el % del dueño | broker fee % mostrado (para ver si es 0,5 % + dueño o max(dueño; 1 %)) |
| V5 | **Modificar** una orden existente (precio nuevo mayor y otro menor) con tu nivel de Advanced Broker Relations | el cobro de la modificación en ISK, el precio viejo y el nuevo |

Con eso se fijan los **vectores de referencia** (`tests/test_finance_reference_vectors.py`) y las reglas pasan a CONFIRMADA o se corrigen.

## Perfil por defecto = tus constantes actuales

`sales_tax_factor = 0,901` y `buy_fee_factor = 1,024` equivalen al perfil **Broker Relations II, Accounting 0, standings 0, estación NPC**:

- broker fee = 3 % − 0,3 % × 2 = **2,4 %** (compra y venta) → `buy_fee_factor = 1 + 0,024 = 1,024`;
- sales tax = 7,5 % × (1 − 0) = **7,5 %** → `sales_tax_factor = 1 − 0,075 − 0,024 = 0,901`.

El motor nuevo con ese perfil reproduce estos factores exactos (`tests/test_finance_engine.py::test_default_profile_reproduces_the_legacy_factors`), de modo que sustituir las fórmulas de `analytics/eve_calculator.py` no cambia ningún número por defecto.

## Qué hace el motor con la incertidumbre

- Cada resultado trae `rules_version` y la lista `warnings`: una advertencia `UNVERIFIED_RULE:R8` aparece si el cálculo usó una regla DISCREPANTE o SUPUESTO que influye en el resultado.
- Los parámetros que faltan (p. ej. el % del dueño de una estructura) dejan el cálculo en `INCOMPLETE` y los importes que dependen de ellos en `null`; **nunca se inventa un valor**.
- Los valores que el usuario escribe a mano se marcan `source: MANUAL`; los que vengan de ESI, `source: ESI`.

## Motor implementado (fase 1)

Paquete `finance/` (puro, `Decimal`, sin E/S; versión del motor `1.0.0`):

| Módulo | Qué hace |
|---|---|
| `rules.py` | `RuleSet` (coeficientes), `RULE_STATUS` (estado de R1–R12), versiones |
| `fees.py` | perfil validado, broker fee NPC/Upwell, sales tax, cobro mínimo, relist |
| `book.py` | recorrido de niveles: precio medio ponderado, faltante, compra/venta inmediata |
| `profit.py` | beneficio neto sin doble conteo, ROI sobre el desembolso (compra + comisión de compra + relists), margen |
| `targets.py` | precio mínimo de venta y máximo de compra en forma cerrada, con el mínimo de 100 ISK |
| `capital.py` | coste de abrir una orden, unidades máximas que caben, capital disponible (el escrow ya no está en el wallet) |
| `scenarios.py` | variaciones independientes sobre una misma entrada |
| `assessment.py` | contrato `FinancialAssessment` (`VALID`/`INCOMPLETE`, advertencias, foto de parámetros) |

Pruebas: `tests/test_finance_engine.py` (vectores a mano, regresión contra `analytics/eve_calculator.py` en 3.000 mercados aleatorios, propiedades de equilibrio/objetivo/capital con semilla fija, entradas inválidas). Mutación: `python scripts/finance_mutation_check.py` (23 fallos introducidos a propósito, todos detectados).

Aún **no** está conectado a la API ni al Screener: no cambia ningún número publicado.
