-- DuckDB port of 02_views.sql, used by the Streamlit app (app.py).
-- Same logic as the Postgres views, with three differences:
--   * prices are DOUBLE: DuckDB's NUMERIC defaults to 3 decimal places,
--     which would round $/gal product prices
--   * crack spreads are computed against both WTI and Brent, one row per crude,
--     so the app can switch benchmark with a WHERE clause
--   * the app filters by date in its own queries; these views use all history,
--     so the 30-day volatility window never starts short

CREATE OR REPLACE VIEW v_daily_prices AS
SELECT
    trade_date,
    MAX(CASE WHEN symbol = 'BZ=F' THEN close_price END) AS brent,  -- $/bbl
    MAX(CASE WHEN symbol = 'CL=F' THEN close_price END) AS wti,    -- $/bbl
    MAX(CASE WHEN symbol = 'HO=F' THEN close_price END) AS ho,     -- $/gal
    MAX(CASE WHEN symbol = 'RB=F' THEN close_price END) AS rbob    -- $/gal
FROM prices
GROUP BY trade_date;


-- Crack spreads in $/bbl; products x 42 to convert $/gal -> $/bbl.
CREATE OR REPLACE VIEW v_crack_spread AS
WITH legs AS (
    SELECT
        d.trade_date,
        c.crude,
        CASE c.crude WHEN 'WTI' THEN d.wti ELSE d.brent END AS crude_price,
        d.rbob,
        d.ho
    FROM v_daily_prices d
    CROSS JOIN (VALUES ('WTI'), ('Brent')) AS c(crude)
)
SELECT
    trade_date,
    crude,
    crude_price,
    rbob,
    ho,
    ((2 * rbob + 1 * ho) * 42 - 3 * crude_price) / 3 AS crack_321,
    ho   * 42 - crude_price                          AS distillate_crack,
    rbob * 42 - crude_price                          AS gasoline_crack
FROM legs
WHERE crude_price IS NOT NULL AND rbob IS NOT NULL AND ho IS NOT NULL;


CREATE OR REPLACE VIEW v_brent_wti_spread AS
SELECT
    trade_date,
    brent,
    wti,
    brent - wti AS brent_wti_spread
FROM v_daily_prices
WHERE brent IS NOT NULL AND wti IS NOT NULL;


-- 30-day rolling volatility of daily log returns, annualised by sqrt(252).
CREATE OR REPLACE VIEW v_rolling_vol AS
WITH returns AS (
    SELECT
        trade_date,
        symbol,
        close_price,
        LN(close_price / LAG(close_price) OVER w) AS log_return
    FROM prices
    WHERE close_price > 0
    WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
),
windowed AS (
    SELECT
        trade_date,
        symbol,
        log_return,
        STDDEV_SAMP(log_return) OVER w30 AS stdev_30d,
        COUNT(log_return)       OVER w30 AS n_returns
    FROM returns
    WINDOW w30 AS (PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)
)
SELECT
    trade_date,
    symbol,
    log_return,
    stdev_30d * SQRT(252) AS vol_30d_annualised
FROM windowed
WHERE n_returns = 30;
