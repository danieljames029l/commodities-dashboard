# Commodities crack-spread dashboard

Brent, WTI, heating oil (ULSD) and RBOB gasoline futures, 2021 → today, in
PostgreSQL, with Power BI on top.

| File | What it does |
|---|---|
| `load_prices.py` | Pulls daily closes from Yahoo, saves `data/prices.csv`, creates the `commodities` DB if missing, upserts into `prices`, rebuilds the views. Safe to re-run daily. |
| `sql/01_schema.sql` | The `prices` table (long format). |
| `sql/02_views.sql` | All the analysis views. |
| `findings.py` | Prints the write-up numbers from the views. |
| `crosscheck.py` | Recomputes the same numbers in pandas from the CSV. Its output should match `findings.py`. |
| `WRITEUP.md` | The finding and the explanation. |
| `app.py` | Streamlit version of the dashboard, shareable as a public link. |
| `sql/duckdb_views.sql` | The same views ported to DuckDB, which the Streamlit app runs. |
| `requirements.txt` | What Streamlit Community Cloud installs for the app. |
| `.env` | DB connection settings, including the `postgres` password. Keep out of git. |

## Views

| View | Grain | Notes |
|---|---|---|
| `v_daily_prices` | 1 row/date | Pivot with `MAX(CASE WHEN …)`. Brent, WTI in $/bbl; HO, RBOB in $/gal. |
| `v_crack_spread` | 1 row/date | `crack_321 = ((2*rbob + ho)*42 - 3*wti)/3`, plus `distillate_crack` and `gasoline_crack`. All $/bbl. |
| `v_brent_wti_spread` | 1 row/date | `brent - wti`. |
| `v_rolling_vol` | 1 row/date/symbol | 30-day stdev of log returns × √252. Built on the long table with `PARTITION BY symbol`. |
| `v_crack_seasonality` | 1 row/month | Complete calendar years only. `*_vs_year` columns subtract each year's average so 2022 doesn't dominate. |
| `v_crack_quarterly` | 1 row/year/quarter | Feeds the Q4-vs-Q2 comparison. |

## Running it

```powershell
python load_prices.py            # fetch fresh data + load
python load_prices.py --offline  # load from data/prices.csv (no internet needed)
python findings.py               # numbers for the write-up
```

If PostgreSQL isn't installed yet: install PostgreSQL 17 from postgresql.org
(or `winget install -e --id PostgreSQL.PostgreSQL.17`). When it asks for the
`postgres` password, use the `PGPASSWORD` value from `.env`. Keep port 5432.
You don't need to create the database in pgAdmin; `load_prices.py` does it.

## Power BI (one page, four visuals)

1. **Get data → More… → Database → PostgreSQL database.**
   Server `localhost:5432`, Database `commodities`, mode **Import**.
2. Credentials: pick **Database** on the left. User `postgres`, password from
   `.env`. The local server has no SSL, so if you get "unable to connect using
   an encrypted connection": File → Options and settings → Data source
   settings → `localhost:5432;commodities` → Edit Permissions → untick
   **Encrypt connections** → OK, then run Get data again. That's fine for a
   database on your own machine.
3. In the Navigator, tick `v_crack_spread`, `v_brent_wti_spread` and
   `v_crack_seasonality`, then **Load**.
4. **Date table.** Modeling → New table:
   ```dax
   Dates = CALENDAR ( DATE ( 2021, 1, 1 ), TODAY () )
   ```
   Table tools → **Mark as date table** → column `Date`.
5. **Relationships** (Model view). Drag `Dates[Date]` onto
   `v_crack_spread[trade_date]` and onto `v_brent_wti_spread[trade_date]`.
   Delete any relationship Power BI auto-created directly between the two views
   (it may try to join them on `trade_date` or `wti`).
6. **Sort months.** In Table view, select `v_crack_seasonality[month_name]` →
   Column tools → **Sort by column** → `month_num`.
7. Visuals:
   - **Line chart:** X = `Dates[Date]` (choose *Date*, not *Date Hierarchy*),
     Y = `crack_321`. Adding `distillate_crack` and `gasoline_crack` as two more
     lines is worth it, since the write-up is about them.
   - **Line chart:** X = `Dates[Date]`, Y = `brent_wti_spread`. Analytics pane →
     Constant line at 0, so the negative prints stand out.
   - **Clustered column chart:** X = `month_name`, Y = `gasoline_vs_year` and
     `distillate_vs_year`. Title: "Crack vs that year's average, 2021–2025
     ($/bbl)". This is the seasonality chart.
   - **Slicer:** `Dates[Date]`, style *Between*. It filters both line charts. The
     seasonality chart is fixed on full complete-year history on purpose.
8. Format the crack/spread columns as Decimal, 2 places. Save as
   `commodities.pbix` in this folder.

**Daily refresh:** run `python load_prices.py`, then Home → **Refresh** in Power BI.

## Streamlit app (the shareable version)

```powershell
streamlit run app.py   # opens http://localhost:8501
```

It reads `data/prices.csv` and runs `sql/duckdb_views.sql` on DuckDB, an
in-memory database, so it needs neither Postgres nor your laptop to be on.
Visitors can change the date range, switch the crude leg between WTI and Brent,
pick which spreads to show, download the data, read the SQL, or upload their
own CSV in the same format.

**Live:** https://01a0fc68-68f6-6bba-f52c-0f1d74f16aae.share.connect.posit.cloud/

It's hosted on Posit Connect Cloud (free), published from the public GitHub repo
`danieljames029l/commodities-dashboard`, branch `main`, file `app.py`.
Streamlit Community Cloud blocks connections from South Sudan IP addresses, so
it couldn't be used.

**Updating the data:** run `python load_prices.py`, then commit and push
`data/prices.csv`. Then republish in Posit Connect Cloud, unless it's set to
republish automatically on each push.
