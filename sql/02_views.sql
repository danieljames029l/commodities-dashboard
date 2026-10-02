-- Analysis views. Dropped and rebuilt on every load so edits here take effect.
-- Units: BZ=F and CL=F are quoted in $/bbl; HO=F and RB=F in $/gal.
-- 1 barrel = 42 US gallons, so product prices are multiplied by 42 before
-- they're compared with crude.

DROP VIEW IF EXISTS v_crack_quarterly;
DROP VIEW IF EXISTS v_crack_seasonality;
DROP VIEW IF EXISTS v_rolling_vol;
DROP VIEW IF EXISTS v_brent_wti_spread;
DROP VIEW IF EXISTS v_crack_spread;
DROP VIEW IF EXISTS v_daily_prices;


-- 1. Pivot: one row per date, all four prices as columns.
CREATE VIEW v_daily_prices AS
SELECT
    trade_date,
    MAX(CASE WHEN symbol = 'BZ=F' THEN close_price END) AS brent,  -- $/bbl
    MAX(CASE WHEN symbol = 'CL=F' THEN close_price END) AS wti,    -- $/bbl
    MAX(CASE WHEN symbol = 'HO=F' THEN close_price END) AS ho,     -- $/gal
    MAX(CASE WHEN symbol = 'RB=F' THEN close_price END) AS rbob    -- $/gal
FROM prices
GROUP BY trade_date;


-- 2. Crack spreads, all in $/bbl.
--    3-2-1: 3 bbl crude -> 2 bbl gasoline + 1 bbl distillate, per bbl of crude.
--    The single-product cracks are here too so the write-up can talk about
--    distillate vs gasoline separately.
CREATE VIEW v_crack_spread AS
SELECT
    trade_date,
    wti,
    rbob,
    ho,
    ((2 * rbob + 1 * ho) * 42 - 3 * wti) / 3 AS crack_321,
    ho   * 42 - wti                          AS distillate_crack,
    rbob * 42 - wti                          AS gasoline_crack
FROM v_daily_prices
WHERE wti IS NOT NULL AND rbob IS NOT NULL AND ho IS NOT NULL;


-- 3. Brent-WTI spread ($/bbl).
CREATE VIEW v_brent_wti_spread AS
SELECT
    trade_date,
    brent,
    wti,
    brent - wti AS brent_wti_spread
FROM v_daily_prices
WHERE brent IS NOT NULL AND wti IS NOT NULL;


-- 4. 30-day rolling volatility, annualised.
--    Works on the long table so PARTITION BY symbol handles all four at once.
--    Window functions can't nest, so log returns go in a CTE first.
CREATE VIEW v_rolling_vol AS
WITH returns AS (
    SELECT
        trade_date,
        symbol,
        close_price,
        LN(close_price / LAG(close_price) OVER w) AS log_return
    FROM prices
    WHERE close_price > 0          -- guard: LN() fails on zero/negative prices
    WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
),
windowed AS (
    SELECT
        trade_date,
        symbol,
        close_price,
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
    close_price,
    log_return,
    ROUND((stdev_30d * SQRT(252))::NUMERIC, 4) AS vol_30d_annualised
FROM windowed
WHERE n_returns = 30;              -- drop the warm-up period with <30 returns


-- 5. Monthly seasonality of the crack spreads.
--    Complete calendar years only: a part-year (e.g. Jan-Sep of the current
--    year) would only feed some months, so if that year runs hot or cold it
--    skews those months against the rest.
--    *_vs_year columns subtract each year's own average first, so a single
--    extreme year (2022) shifts the level but not the seasonal shape.
CREATE VIEW v_crack_seasonality AS
WITH complete_years AS (
    SELECT
        trade_date,
        crack_321,
        distillate_crack,
        gasoline_crack,
        crack_321        - AVG(crack_321)        OVER yr AS crack_321_vs_year,
        distillate_crack - AVG(distillate_crack) OVER yr AS distillate_vs_year,
        gasoline_crack   - AVG(gasoline_crack)   OVER yr AS gasoline_vs_year
    FROM v_crack_spread
    WHERE EXTRACT(YEAR FROM trade_date) < EXTRACT(YEAR FROM CURRENT_DATE)
    WINDOW yr AS (PARTITION BY EXTRACT(YEAR FROM trade_date))
)
SELECT
    EXTRACT(MONTH FROM trade_date)::INT        AS month_num,
    TO_CHAR(MIN(trade_date), 'Mon')            AS month_name,
    ROUND(AVG(crack_321), 2)                   AS avg_crack_321,
    ROUND(AVG(distillate_crack), 2)            AS avg_distillate_crack,
    ROUND(AVG(gasoline_crack), 2)              AS avg_gasoline_crack,
    ROUND(AVG(crack_321_vs_year), 2)           AS crack_321_vs_year,
    ROUND(AVG(distillate_vs_year), 2)          AS distillate_vs_year,
    ROUND(AVG(gasoline_vs_year), 2)            AS gasoline_vs_year,
    MIN(EXTRACT(YEAR FROM trade_date))::INT    AS first_year,
    MAX(EXTRACT(YEAR FROM trade_date))::INT    AS last_year,
    COUNT(*)                                   AS n_days
FROM complete_years
GROUP BY EXTRACT(MONTH FROM trade_date);


-- 6. Quarterly averages by year, for the write-up numbers.
CREATE VIEW v_crack_quarterly AS
SELECT
    EXTRACT(YEAR    FROM trade_date)::INT AS yr,
    EXTRACT(QUARTER FROM trade_date)::INT AS qtr,
    ROUND(AVG(crack_321), 2)              AS avg_crack_321,
    ROUND(AVG(distillate_crack), 2)       AS avg_distillate_crack,
    ROUND(AVG(gasoline_crack), 2)         AS avg_gasoline_crack,
    COUNT(*)                              AS n_days
FROM v_crack_spread
GROUP BY 1, 2;
