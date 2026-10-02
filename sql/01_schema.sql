-- One row per date per symbol (long format).
CREATE TABLE IF NOT EXISTS prices (
    trade_date  DATE,
    symbol      TEXT,
    close_price NUMERIC,
    PRIMARY KEY (trade_date, symbol)
);
