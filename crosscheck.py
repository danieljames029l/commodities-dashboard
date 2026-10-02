"""Recompute the headline numbers in pandas from data/prices.csv.

An independent check on the SQL views: if these match findings.py, the
views are doing what we think they're doing.
"""
import numpy as np
import pandas as pd

from load_prices import CSV

df = pd.read_csv(CSV, parse_dates=["trade_date"])
w = df.pivot(index="trade_date", columns="symbol", values="close_price")
w.columns = [{"BZ=F": "brent", "CL=F": "wti", "HO=F": "ho", "RB=F": "rbob"}[c] for c in w.columns]

c = w.dropna(subset=["wti", "rbob", "ho"]).copy()
c["crack_321"] = ((2 * c.rbob + c.ho) * 42 - 3 * c.wti) / 3
c["distillate_crack"] = c.ho * 42 - c.wti
c["gasoline_crack"] = c.rbob * 42 - c.wti
cracks = ["crack_321", "distillate_crack", "gasoline_crack"]

print("=== whole period")
print(c[cracks].agg(["mean", "max", "min"]).round(2).to_string())

print("\n=== by month (pooled)")
print(c.groupby(c.index.month)[cracks].mean().round(2).to_string())

print("\n=== by quarter (pooled)")
print(c.groupby(c.index.quarter)[cracks].mean().round(2).to_string())

q = c.groupby([c.index.year, c.index.quarter])[cracks].mean()
q.index.names = ["yr", "qtr"]
yoy = pd.DataFrame({
    "q2_dist": q.xs(2, level="qtr")["distillate_crack"],
    "q4_dist": q.xs(4, level="qtr")["distillate_crack"],
})
yoy["dist_q4_minus_q2"] = yoy.q4_dist - yoy.q2_dist
print("\n=== distillate Q4 - Q2 by year")
print(yoy.round(2).to_string())

bw = w.dropna(subset=["brent", "wti"])
print("\n=== Brent-WTI by year")
print((bw.brent - bw.wti).groupby(bw.index.year).agg(["mean", "min", "max"]).round(2).to_string())

print("\n=== 30d annualised vol (latest, mean)")
lr = np.log(w / w.shift(1))
# Match the SQL: returns are computed per symbol over that symbol's own rows.
vols = {}
for col in w.columns:
    s = w[col].dropna()
    r = np.log(s / s.shift(1))
    v = r.rolling(30, min_periods=30).std() * np.sqrt(252)
    vols[col] = (round(v.iloc[-1], 4), round(v.mean(), 3), round(v.max(), 4))
print(pd.DataFrame(vols, index=["latest", "mean", "peak"]).to_string())
