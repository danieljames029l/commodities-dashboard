"""Streamlit version of the crack-spread dashboard.

Runs sql/duckdb_views.sql on DuckDB, an in-process database, so it needs no
server and can be hosted for free on Streamlit Community Cloud.

    streamlit run app.py
"""
import io
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

HERE = Path(__file__).parent
DEFAULT_CSV = HERE / "data" / "prices.csv"
VIEWS_SQL = (HERE / "sql" / "duckdb_views.sql").read_text()

SYMBOLS = {
    "BZ=F": "Brent",
    "CL=F": "WTI",
    "HO=F": "Heating oil (ULSD)",
    "RB=F": "RBOB gasoline",
}
CRACKS = {
    "crack_321": "3-2-1 crack",
    "distillate_crack": "Distillate crack",
    "gasoline_crack": "Gasoline crack",
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Categorical slots 1-4 of the validated reference palette, light and dark
# steps. Each series keeps its slot whatever is filtered, so colours never
# repaint when a spread is hidden.
PALETTE = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500"],
}
MUTED = "#898781"

SEASONALITY_SQL = """
WITH in_range AS (
    SELECT * FROM v_crack_spread
    WHERE crude = $crude AND trade_date BETWEEN $start AND $end
),
-- Only years the range covers from early January to late December: a
-- part-year feeds some months and not others, which skews the comparison.
complete_years AS (
    SELECT YEAR(trade_date) AS yr
    FROM in_range
    GROUP BY YEAR(trade_date)
    HAVING MIN(trade_date) <= MAKE_DATE(YEAR(MIN(trade_date)), 1, 10)
       AND MAX(trade_date) >= MAKE_DATE(YEAR(MIN(trade_date)), 12, 20)
),
-- Subtract each year's own average so one extreme year (2022) moves the
-- level, not the seasonal shape.
vs_year AS (
    SELECT
        trade_date,
        crack_321        - AVG(crack_321)        OVER yr AS crack_321,
        distillate_crack - AVG(distillate_crack) OVER yr AS distillate_crack,
        gasoline_crack   - AVG(gasoline_crack)   OVER yr AS gasoline_crack
    FROM in_range
    WHERE YEAR(trade_date) IN (SELECT yr FROM complete_years)
    WINDOW yr AS (PARTITION BY YEAR(trade_date))
)
SELECT
    MONTH(trade_date)               AS month_num,
    STRFTIME(MIN(trade_date), '%b') AS month_name,
    AVG(crack_321)                  AS crack_321,
    AVG(distillate_crack)           AS distillate_crack,
    AVG(gasoline_crack)             AS gasoline_crack,
    MIN(YEAR(trade_date))           AS first_year,
    MAX(YEAR(trade_date))           AS last_year
FROM vs_year
GROUP BY MONTH(trade_date)
ORDER BY month_num
"""

alt.data_transformers.disable_max_rows()


@st.cache_data
def read_prices(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = [c.strip().lower() for c in df.columns]
    missing = {"trade_date", "symbol", "close_price"} - set(df.columns)
    if missing:
        raise ValueError(f"missing column(s): {', '.join(sorted(missing))}")
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df = df.dropna(subset=["trade_date", "close_price"])
    absent = set(SYMBOLS) - set(df["symbol"])
    if absent:
        raise ValueError(f"no rows for {', '.join(sorted(absent))}")
    return (df.drop_duplicates(["trade_date", "symbol"], keep="last")
              [["trade_date", "symbol", "close_price"]])


def build_db(prices: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    # A fresh in-memory database per run: ~6k rows load in milliseconds, and
    # nothing is shared between viewers.
    con = duckdb.connect()
    con.register("prices_df", prices)
    con.execute("""
        CREATE TABLE prices AS
        SELECT CAST(trade_date AS DATE)    AS trade_date,
               symbol,
               CAST(close_price AS DOUBLE) AS close_price
        FROM prices_df
    """)
    con.execute(VIEWS_SQL)
    return con


def colors() -> list[str]:
    try:
        mode = st.context.theme.type or "light"
    except AttributeError:
        mode = "light"
    return PALETTE.get(mode, PALETTE["light"])


def zero_rule():
    return (alt.Chart(pd.DataFrame({"zero": [0]}))
            .mark_rule(color=MUTED, strokeDash=[4, 4])
            .encode(y="zero:Q"))


def time_chart(df, order, palette, y_title, fmt, axis_fmt=None, zero=False):
    """Lines plus a hover crosshair whose tooltip lists every series that day."""
    color = alt.Color("series:N", title=None,
                      scale=alt.Scale(domain=order, range=palette[:len(order)]),
                      legend=alt.Legend(orient="top") if df["series"].nunique() > 1 else None)
    hover = alt.selection_point(fields=["trade_date"], nearest=True,
                                on="pointerover", clear="pointerout", empty=False)
    base = alt.Chart(df).encode(x=alt.X("trade_date:T", title=None))
    lines = base.mark_line(strokeWidth=2).encode(
        y=alt.Y("value:Q", title=y_title, axis=alt.Axis(format=axis_fmt or fmt)),
        color=color,
    )
    dots = base.mark_point(filled=True, size=60).encode(
        y="value:Q", color=color,
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
    )
    present = [s for s in order if s in set(df["series"])]
    crosshair = (
        base.transform_pivot("series", value="value", groupby=["trade_date"])
        .mark_rule(color=MUTED)
        .encode(
            opacity=alt.condition(hover, alt.value(0.7), alt.value(0)),
            tooltip=[alt.Tooltip("trade_date:T", title="Date", format="%d %b %Y")]
                    + [alt.Tooltip(field=s, type="quantitative", format=fmt) for s in present],
        )
        .add_params(hover)
    )
    layers = [lines, dots, crosshair]
    if zero:
        layers.insert(0, zero_rule())
    return alt.layer(*layers).properties(height=320)


def to_long(df, columns, id_var="trade_date"):
    return (df.rename(columns=columns)
              .melt(id_vars=id_var, value_vars=list(columns.values()),
                    var_name="series", value_name="value"))


st.set_page_config(page_title="Refining Margins Dashboard", layout="wide")
palette = colors()
# Grey spread tags: Streamlit's red would look like a fourth series colour.
# (A [theme] primaryColor in config.toml would do this too, but in Streamlit
# 1.47 it also locks the app to light mode.)
st.markdown("<style>span[data-baseweb='tag'] {background-color: #898781 !important;}</style>",
            unsafe_allow_html=True)

with st.sidebar:
    st.header("Use your own data")
    upload = st.file_uploader("Price CSV", type="csv")
    st.caption(
        "Long format: `trade_date, symbol, close_price`, one row per date per "
        "symbol. Needs BZ=F and CL=F in \\$/bbl, HO=F and RB=F in \\$/gal."
    )

prices = None
if upload is not None:
    try:
        prices = read_prices(upload.getvalue())
    except ValueError as e:
        st.sidebar.error(f"Couldn't use that file ({e}). Showing the built-in data.")
if prices is None:
    prices = read_prices(DEFAULT_CSV.read_bytes())
con = build_db(prices)

lo, hi = prices["trade_date"].min().date(), prices["trade_date"].max().date()

st.title("Refining margins dashboard")
st.markdown(
    "How much a US refinery earns turning crude oil into gasoline and diesel, "
    "from daily futures prices. The **3-2-1 crack** assumes 3 barrels of crude "
    "make 2 of gasoline and 1 of diesel. Fuels are priced per gallon and crude "
    "per barrel, so fuel prices are multiplied by 42 (gallons in a barrel) first."
)

f1, f2, f3 = st.columns([3, 1.3, 2.7])
start, end = f1.slider("Date range", min_value=lo, max_value=hi,
                       value=(lo, hi), format="MMM YYYY")
crude = f2.radio("Crude price used", ["WTI", "Brent"], horizontal=True,
                 help="Which crude the refinery buys. The standard US crack uses WTI.")
shown = f3.multiselect("Spreads", list(CRACKS.values()), default=list(CRACKS.values()))

rng = {"crude": crude, "start": start, "end": end}
cracks = con.execute("""
    SELECT trade_date, crack_321, distillate_crack, gasoline_crack
    FROM v_crack_spread
    WHERE crude = $crude AND trade_date BETWEEN $start AND $end
    ORDER BY trade_date
""", rng).df()
bw = con.execute("""
    SELECT trade_date, brent, wti, brent_wti_spread
    FROM v_brent_wti_spread
    WHERE trade_date BETWEEN $start AND $end
    ORDER BY trade_date
""", {"start": start, "end": end}).df()
vol = con.execute("""
    SELECT trade_date, symbol, vol_30d_annualised
    FROM v_rolling_vol
    WHERE trade_date BETWEEN $start AND $end
    ORDER BY trade_date
""", {"start": start, "end": end}).df()
season = con.execute(SEASONALITY_SQL, rng).df()

if cracks.empty:
    st.warning("No prices in that date range.")
    st.stop()

# Headline numbers: last day in range, compared with the range average.
last_day = cracks["trade_date"].iloc[-1]
kpis = st.columns(4)
for col, (field, label) in zip(kpis, CRACKS.items()):
    now, avg = cracks[field].iloc[-1], cracks[field].mean()
    col.metric(f"{label}, {last_day:%d %b %Y}", f"${now:,.2f}",
               f"{now - avg:+,.2f} vs range average", delta_color="off")
if not bw.empty:
    now, avg = bw["brent_wti_spread"].iloc[-1], bw["brent_wti_spread"].mean()
    kpis[3].metric(f"Brent–WTI, {bw['trade_date'].iloc[-1]:%d %b %Y}", f"${now:,.2f}",
                   f"{now - avg:+,.2f} vs range average", delta_color="off")

crack_order = list(CRACKS.values())
crack_palette = palette[:3]
picked = [s for s in crack_order if s in shown]

left, right = st.columns(2)
with left:
    st.subheader("Crack spreads ($/bbl)")
    st.caption(f"Refinery margin per barrel of {crude} crude.")
    if picked:
        long = to_long(cracks, CRACKS)
        st.altair_chart(time_chart(long[long["series"].isin(picked)], crack_order,
                                   crack_palette, "$/bbl", "$,.2f", "$,.0f"),
                        use_container_width=True)
    else:
        st.info("Pick at least one spread above.")

with right:
    st.subheader("Seasonality")
    if season.empty:
        st.info("Pick a range that covers at least one full calendar year.")
    else:
        y0, y1 = int(season["first_year"].min()), int(season["last_year"].max())
        years = f"{y0}" if y0 == y1 else f"{y0}–{y1}"
        st.caption(f"Each month's average minus that year's average, complete years "
                   f"{years}. Above zero = stronger than usual for that year.")
        s_long = to_long(season, CRACKS, id_var="month_name")
        s_long = s_long[s_long["series"].isin(picked)]
        bars = alt.Chart(s_long).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("month_name:N", sort=MONTHS, title=None, axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("series:N", sort=crack_order),
            y=alt.Y("value:Q", title="$/bbl vs year average", axis=alt.Axis(format="$,.0f")),
            color=alt.Color("series:N", title=None, legend=alt.Legend(orient="top"),
                            scale=alt.Scale(domain=crack_order, range=crack_palette)),
            tooltip=[alt.Tooltip("month_name:N", title="Month"),
                     alt.Tooltip("series:N", title="Spread"),
                     alt.Tooltip("value:Q", title="vs year average", format="+$,.2f")],
        )
        if picked:
            st.altair_chart(alt.layer(zero_rule(), bars).properties(height=320),
                            use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("Brent–WTI spread ($/bbl)")
    st.caption("World crude (Brent) minus US crude (WTI). Negative days are mostly a "
               "data quirk: the two front-month contracts can be for different months.")
    bw_long = bw[["trade_date", "brent_wti_spread"]].rename(
        columns={"brent_wti_spread": "value"}).assign(series="Brent–WTI")
    st.altair_chart(time_chart(bw_long, ["Brent–WTI"], palette, "$/bbl", "$,.2f", "$,.0f",
                               zero=True),
                    use_container_width=True)

with right:
    st.subheader("Volatility")
    st.caption("How jumpy each price is: standard deviation of daily returns over the "
               "last 30 trading days, annualised.")
    vol_order = list(SYMBOLS.values())
    vol_long = vol.assign(series=vol["symbol"].map(SYMBOLS)).rename(
        columns={"vol_30d_annualised": "value"})[["trade_date", "series", "value"]]
    st.altair_chart(time_chart(vol_long, vol_order, palette, "Annualised volatility", ".0%"),
                    use_container_width=True)

with st.expander("Data table and download"):
    table = cracks.rename(columns=CRACKS).merge(
        bw[["trade_date", "brent_wti_spread"]].rename(columns={"brent_wti_spread": "Brent–WTI"}),
        on="trade_date", how="left")
    st.dataframe(table, hide_index=True, use_container_width=True,
                 column_config={"trade_date": st.column_config.DateColumn("Date")})
    st.download_button("Download as CSV", table.to_csv(index=False).encode(),
                       file_name=f"crack_spreads_{start}_{end}.csv", mime="text/csv")

with st.expander("The SQL behind this"):
    st.caption("Views (sql/duckdb_views.sql), then the seasonality query.")
    st.code(VIEWS_SQL, language="sql")
    st.code(SEASONALITY_SQL, language="sql")

st.caption(
    f"Data: Yahoo Finance continuous front-month futures (BZ=F, CL=F, HO=F, RB=F), "
    f"daily closes {lo:%d %b %Y} – {hi:%d %b %Y}. Roll dates add small jumps; "
    f"real refinery margins also depend on location, crude slate and costs."
)
