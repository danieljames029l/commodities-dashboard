"""Print the numbers behind the write-up, straight from the views."""
import psycopg2
import pandas as pd

from load_prices import load_env

QUERIES = {
    "Coverage": """
        SELECT MIN(trade_date) AS first_day, MAX(trade_date) AS last_day,
               COUNT(*) AS days_with_all_three_legs
        FROM v_crack_spread
    """,
    "Crack spreads, whole period ($/bbl)": """
        SELECT ROUND(AVG(crack_321), 2)        AS avg_321,
               ROUND(AVG(distillate_crack), 2) AS avg_distillate,
               ROUND(AVG(gasoline_crack), 2)   AS avg_gasoline,
               ROUND(MAX(crack_321), 2)        AS max_321,
               ROUND(MIN(crack_321), 2)        AS min_321
        FROM v_crack_spread
    """,
    "Peak 3-2-1 and distillate days": """
        SELECT what, trade_date, ROUND(crack_321, 2) AS crack_321,
               ROUND(distillate_crack, 2) AS distillate_crack,
               ROUND(gasoline_crack, 2) AS gasoline_crack
        FROM (
            (SELECT 'max 3-2-1' AS what, * FROM v_crack_spread ORDER BY crack_321 DESC LIMIT 1)
            UNION ALL
            (SELECT 'max distillate', * FROM v_crack_spread ORDER BY distillate_crack DESC LIMIT 1)
            UNION ALL
            (SELECT 'latest', * FROM v_crack_spread ORDER BY trade_date DESC LIMIT 1)
        ) t
    """,
    "Seasonality by month (complete years; *_vs_year = vs that year's average)": """
        SELECT month_num, month_name, avg_crack_321, avg_distillate_crack,
               avg_gasoline_crack, crack_321_vs_year, distillate_vs_year,
               gasoline_vs_year, first_year, last_year, n_days
        FROM v_crack_seasonality ORDER BY month_num
    """,
    "Quarterly averages, complete years only": """
        SELECT EXTRACT(QUARTER FROM trade_date)::INT AS qtr,
               ROUND(AVG(crack_321), 2)        AS avg_321,
               ROUND(AVG(distillate_crack), 2) AS avg_distillate,
               ROUND(AVG(gasoline_crack), 2)   AS avg_gasoline,
               COUNT(*) AS n_days
        FROM v_crack_spread
        WHERE EXTRACT(YEAR FROM trade_date) < EXTRACT(YEAR FROM CURRENT_DATE)
        GROUP BY 1 ORDER BY 1
    """,
    "Current year so far, by quarter": """
        SELECT yr, qtr, avg_crack_321, avg_distillate_crack, avg_gasoline_crack, n_days
        FROM v_crack_quarterly
        WHERE yr = EXTRACT(YEAR FROM CURRENT_DATE) ORDER BY qtr
    """,
    "Q4 minus Q2, year by year (does the pattern hold every year?)": """
        SELECT yr,
               MAX(CASE WHEN qtr = 2 THEN avg_distillate_crack END) AS q2_distillate,
               MAX(CASE WHEN qtr = 4 THEN avg_distillate_crack END) AS q4_distillate,
               MAX(CASE WHEN qtr = 4 THEN avg_distillate_crack END)
             - MAX(CASE WHEN qtr = 2 THEN avg_distillate_crack END) AS distillate_q4_minus_q2,
               MAX(CASE WHEN qtr = 2 THEN avg_gasoline_crack END) AS q2_gasoline,
               MAX(CASE WHEN qtr = 4 THEN avg_gasoline_crack END) AS q4_gasoline,
               MAX(CASE WHEN qtr = 4 THEN avg_gasoline_crack END)
             - MAX(CASE WHEN qtr = 2 THEN avg_gasoline_crack END) AS gasoline_q4_minus_q2
        FROM v_crack_quarterly GROUP BY yr ORDER BY yr
    """,
    "Annual averages": """
        SELECT EXTRACT(YEAR FROM trade_date)::INT AS yr,
               ROUND(AVG(crack_321), 2)        AS avg_321,
               ROUND(AVG(distillate_crack), 2) AS avg_distillate,
               ROUND(AVG(gasoline_crack), 2)   AS avg_gasoline
        FROM v_crack_spread GROUP BY 1 ORDER BY 1
    """,
    "Brent-WTI spread ($/bbl)": """
        SELECT EXTRACT(YEAR FROM trade_date)::INT AS yr,
               ROUND(AVG(brent_wti_spread), 2) AS avg_spread,
               MIN(brent_wti_spread) AS min_spread,
               MAX(brent_wti_spread) AS max_spread
        FROM v_brent_wti_spread GROUP BY 1 ORDER BY 1
    """,
    "30d annualised vol: average, peak, latest": """
        SELECT v.symbol,
               ROUND(AVG(v.vol_30d_annualised), 3) AS avg_vol,
               MAX(v.vol_30d_annualised)           AS peak_vol,
               (SELECT trade_date FROM v_rolling_vol x WHERE x.symbol = v.symbol
                ORDER BY vol_30d_annualised DESC LIMIT 1) AS peak_date,
               (SELECT vol_30d_annualised FROM v_rolling_vol x WHERE x.symbol = v.symbol
                ORDER BY trade_date DESC LIMIT 1) AS latest_vol
        FROM v_rolling_vol v GROUP BY v.symbol ORDER BY v.symbol
    """,
    "Largest single-day moves (continuous-contract roll check)": """
        SELECT symbol, trade_date, close_price, ROUND(log_return::NUMERIC, 4) AS log_return
        FROM v_rolling_vol ORDER BY ABS(log_return) DESC LIMIT 8
    """,
}


def main():
    env = load_env()
    conn = psycopg2.connect(
        host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"],
        password=env["PGPASSWORD"], dbname=env["PGDATABASE"],
    )
    pd.set_option("display.width", 200)
    with conn.cursor() as cur:
        for title, sql in QUERIES.items():
            cur.execute(sql)
            cols = [c.name for c in cur.description]
            print(f"\n=== {title}")
            print(pd.DataFrame(cur.fetchall(), columns=cols).to_string(index=False))
    conn.close()


if __name__ == "__main__":
    main()
