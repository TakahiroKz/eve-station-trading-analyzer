-- Mercados (hubs) que analiza el sistema. Hoy cada uno es una REGIÓN de EVE (igual que Jita desde el
-- principio: órdenes de toda la región, histórico regional de la ESI). `kind = 'system'` y `system_id`
-- quedan para mercados de un solo sistema o estación más adelante (arbitraje entre sistemas) sin
-- cambiar el esquema: todas las tablas por mercado cuelgan de market_id.
CREATE TABLE IF NOT EXISTS market (
    market_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    region_id   INTEGER NOT NULL,
    system_id   INTEGER,
    kind        TEXT NOT NULL DEFAULT 'region' CHECK (kind IN ('region', 'system')),
    enabled     INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS item_type (
    type_id     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL
);

-- Categoría/grupo del ítem (ESI /universe/types/{id}/, /universe/groups/{id}/,
-- /universe/categories/{id}/). Es un CACHÉ: solo se pide a la ESI para type_id que
-- todavía no están acá — no hay endpoint bulk, así que se evita repetir la llamada
-- individual en cada corrida (la categoría de un ítem prácticamente nunca cambia).
CREATE TABLE IF NOT EXISTS item_category (
    type_id        INTEGER PRIMARY KEY,
    group_id       INTEGER NOT NULL,
    group_name     TEXT NOT NULL,
    category_id    INTEGER NOT NULL,
    category_name  TEXT NOT NULL,
    FOREIGN KEY (type_id) REFERENCES item_type(type_id)
);

-- Histórico diario por ítem, fuente de rotación/volatilidad (ESI /markets/{region_id}/history/)
CREATE TABLE IF NOT EXISTS market_history (
    market_id   TEXT NOT NULL DEFAULT 'jita',
    type_id     INTEGER NOT NULL,
    date        TEXT NOT NULL,
    avg_price   REAL NOT NULL,
    highest     REAL NOT NULL,
    lowest      REAL NOT NULL,
    volume      INTEGER NOT NULL,
    order_count INTEGER NOT NULL,
    PRIMARY KEY (market_id, type_id, date),
    FOREIGN KEY (market_id) REFERENCES market(market_id),
    FOREIGN KEY (type_id) REFERENCES item_type(type_id)
) WITHOUT ROWID;

-- Foto de órdenes activas, fuente del spread actual (ESI /markets/{region_id}/orders/)
CREATE TABLE IF NOT EXISTS market_snapshot (
    market_id        TEXT NOT NULL DEFAULT 'jita',
    type_id          INTEGER NOT NULL,
    captured_at      TEXT NOT NULL,
    best_buy         REAL,
    best_sell        REAL,
    buy_volume       INTEGER,
    sell_volume      INTEGER,
    buy_order_count  INTEGER NOT NULL DEFAULT 0,
    sell_order_count INTEGER NOT NULL DEFAULT 0,
    -- Profundidad del libro (analytics/market_aggregation.py), de la región completa: unidades dentro del 5 %
    -- del mejor precio, distancia al siguiente nivel en puntos básicos y parte del volumen en el mejor precio
    -- por mil. Enteros para que cada snapshot ocupe poco; NULL si ese lado no tiene órdenes o es anterior.
    buy_depth_5pct   INTEGER,
    sell_depth_5pct  INTEGER,
    buy_gap_bp       INTEGER,
    sell_gap_bp      INTEGER,
    buy_top_permille  INTEGER,
    sell_top_permille INTEGER,
    PRIMARY KEY (market_id, type_id, captured_at),
    FOREIGN KEY (market_id) REFERENCES market(market_id),
    FOREIGN KEY (type_id) REFERENCES item_type(type_id)
) WITHOUT ROWID;

-- Reflejo local de cada oportunidad de station trade evaluada por EveCalculator
CREATE TABLE IF NOT EXISTS opportunity_log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id               TEXT NOT NULL DEFAULT 'jita',
    type_id                 INTEGER NOT NULL,
    evaluated_at            TEXT NOT NULL,
    buy                     REAL NOT NULL,
    sell                    REAL NOT NULL,
    volumen_deseado         REAL NOT NULL,
    volumen_diario_real     REAL NOT NULL,
    beneficio               REAL NOT NULL,
    spread_bruto            REAL NOT NULL,
    precio_min_venta        REAL NOT NULL,
    roi                     REAL NOT NULL,
    evaluacion_spread       TEXT NOT NULL,
    posicion_vs_volumen     REAL NOT NULL,
    liquidez                TEXT NOT NULL,
    recomendacion           TEXT NOT NULL,
    FOREIGN KEY (market_id) REFERENCES market(market_id),
    FOREIGN KEY (type_id) REFERENCES item_type(type_id)
);

-- Clasificación VIGENTE de cada ítem, recalculada en cada corrida periódica del pipeline.
-- POTENCIAL_SIN_ORDENES: cumple spread/liquidez pero el HISTÓRICO de transacciones
-- ejecutadas (últimos 7 días, no el libro de órdenes abiertas) no muestra flujo real
-- (poco volumen/día o pocas operaciones/día — posible orden única de una ballena).
CREATE TABLE IF NOT EXISTS item_status (
    market_id                 TEXT NOT NULL DEFAULT 'jita',
    type_id                   INTEGER NOT NULL,
    status                    TEXT NOT NULL CHECK (
        status IN ('POTENCIAL', 'POTENCIAL_SIN_ORDENES', 'DESCARTADO', 'EN_OBSERVACION')
    ),
    reason                    TEXT NOT NULL,
    spread_bruto              REAL NOT NULL,
    evaluacion_spread         TEXT NOT NULL,
    liquidez                  TEXT NOT NULL,
    roi                       REAL NOT NULL,
    best_buy                  REAL NOT NULL DEFAULT 0,
    best_sell                 REAL NOT NULL DEFAULT 0,
    volumen_diario_real       REAL NOT NULL DEFAULT 0,
    buy_order_count           INTEGER NOT NULL DEFAULT 0,
    sell_order_count          INTEGER NOT NULL DEFAULT 0,
    avg_daily_volume_7d       REAL NOT NULL DEFAULT 0,
    avg_daily_order_count_7d  REAL NOT NULL DEFAULT 0,
    price_trend               REAL,
    price_trend_label         TEXT NOT NULL DEFAULT 'nodata',
    price_trend_threshold     REAL,
    last_evaluated_at         TEXT NOT NULL,
    -- Puntaje 0-100 explicable (analytics/scoring.py) y evaluación determinista (analytics/opportunity.py).
    -- Complementan al estado; NULL mientras el ítem no se haya vuelto a evaluar. score_inputs guarda solo lo que no
    -- está ya en la fila (volatilidad, antigüedad del dato, coherencia de precios): la explicación completa se
    -- recalcula a partir de la fila y de esos tres datos (analytics.opportunity.evaluate_item).
    score                     INTEGER,
    score_class               TEXT,
    eligibility               TEXT,
    recommendation            TEXT,
    score_version             TEXT,
    score_inputs              TEXT,
    PRIMARY KEY (market_id, type_id),
    FOREIGN KEY (market_id) REFERENCES market(market_id),
    FOREIGN KEY (type_id) REFERENCES item_type(type_id)
) WITHOUT ROWID;

-- Seguimiento de la tendencia de los ítems con una orden activa tuya, para avisar por Telegram
-- solo cuando la señal se confirma en dos lecturas diarias seguidas (ver analytics/trend_alerts.py).
CREATE TABLE IF NOT EXISTS trend_alert_state (
    market_id         TEXT NOT NULL,
    type_id           INTEGER NOT NULL,
    label             TEXT NOT NULL,
    since_date        TEXT NOT NULL,
    last_date         TEXT NOT NULL,
    alerted_since     TEXT,
    last_alerted_date TEXT,
    PRIMARY KEY (market_id, type_id)
) WITHOUT ROWID;

-- Historial append-only de cambios de estado, para auditar cómo evoluciona cada ítem
-- entre recategorizaciones sucesivas (ej. de EN_OBSERVACION a POTENCIAL).
CREATE TABLE IF NOT EXISTS item_status_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id       TEXT NOT NULL DEFAULT 'jita',
    type_id         INTEGER NOT NULL,
    previous_status TEXT,
    new_status      TEXT NOT NULL,
    changed_at      TEXT NOT NULL,
    reason          TEXT NOT NULL,
    FOREIGN KEY (market_id) REFERENCES market(market_id),
    FOREIGN KEY (type_id) REFERENCES item_type(type_id)
);

-- Órdenes ACTIVAS del personaje (ESI /characters/{id}/orders/), snapshot en cada
-- corrida del motor de posiciones (scheduler/orders_run.py, cada 5 min). orders_ahead/
-- price_gap/best_price salen de comparar contra el libro de órdenes REAL de ese
-- ítem+lado (no un agregado), y se notifica solo cuando orders_ahead cambia respecto
-- a la corrida anterior (ver check_character_orders).
CREATE TABLE IF NOT EXISTS character_order (
    order_id         INTEGER PRIMARY KEY,
    type_id          INTEGER NOT NULL,
    region_id        INTEGER NOT NULL,
    is_buy_order     INTEGER NOT NULL,
    price            REAL NOT NULL,
    volume_remain    INTEGER NOT NULL,
    volume_total     INTEGER NOT NULL,
    issued           TEXT NOT NULL,
    is_undercut      INTEGER NOT NULL DEFAULT 0,
    undercut_alerted INTEGER NOT NULL DEFAULT 0,
    orders_ahead     INTEGER NOT NULL DEFAULT 0,
    price_gap        REAL NOT NULL DEFAULT 0,
    best_price       REAL,
    first_seen_at    TEXT NOT NULL,
    last_seen_at     TEXT NOT NULL,
    FOREIGN KEY (type_id) REFERENCES item_type(type_id)
);

-- Log de órdenes que desaparecieron de la lista de activas: completadas, expiradas o
-- canceladas (el estado final se resuelve contra /orders/history/ de la ESI).
CREATE TABLE IF NOT EXISTS character_order_closed (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL,
    type_id      INTEGER NOT NULL,
    is_buy_order INTEGER NOT NULL,
    price        REAL NOT NULL,
    final_state  TEXT NOT NULL,
    closed_at    TEXT NOT NULL,
    FOREIGN KEY (type_id) REFERENCES item_type(type_id)
);

-- Log de ejecuciones parciales de órdenes activas: volume_remain bajó desde la corrida
-- anterior pero la orden sigue activa (ver OrderFilled en notifications/events.py). Una
-- ejecución que deja volume_remain en 0 no pasa por acá: la orden desaparece de las
-- activas y la agarra character_order_closed en la corrida siguiente.
CREATE TABLE IF NOT EXISTS character_order_fill (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      INTEGER NOT NULL,
    type_id       INTEGER NOT NULL,
    is_buy_order  INTEGER NOT NULL,
    price         REAL NOT NULL,
    filled_units  INTEGER NOT NULL,
    volume_remain INTEGER NOT NULL,
    filled_at     TEXT NOT NULL,
    FOREIGN KEY (type_id) REFERENCES item_type(type_id)
);

-- Todos los parámetros configurables del programa (Ajustes en la PWA): reemplaza las
-- constantes hardcodeadas que antes vivían repartidas por analytics/. Fila por
-- parámetro (no una fila única) — la lista completa, categorías y defaults salen de
-- storage/settings_registry.py, no de acá. Editable vía GET/PUT/POST /api/settings.
CREATE TABLE IF NOT EXISTS app_settings (
    key            TEXT PRIMARY KEY,
    category       TEXT NOT NULL,
    label          TEXT NOT NULL,
    description    TEXT NOT NULL,
    value          REAL NOT NULL,
    default_value  REAL NOT NULL,
    updated_at     TEXT NOT NULL
);

-- Las claves primarias de market_history, market_snapshot e item_status ya cubren (market_id, type_id, ...).
CREATE INDEX IF NOT EXISTS idx_status_market_status ON item_status(market_id, status);
CREATE INDEX IF NOT EXISTS idx_opportunity_market_type ON opportunity_log(market_id, type_id);
CREATE INDEX IF NOT EXISTS idx_status_history_market_type ON item_status_history(market_id, type_id);
CREATE INDEX IF NOT EXISTS idx_category_category_id ON item_category(category_id);
CREATE INDEX IF NOT EXISTS idx_character_order_type ON character_order(type_id);
CREATE INDEX IF NOT EXISTS idx_character_order_fill_type ON character_order_fill(type_id);
