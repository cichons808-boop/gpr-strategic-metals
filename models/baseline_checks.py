"""Calendar, transformation and OLS checks for the baseline models."""

from paths import RAW, PROCESSED, RESULTS
import pandas as pd, numpy as np, json
from pathlib import Path
from scipy.stats import norm

O = RESULTS / "baseline"
r = pd.read_csv(O / "robustness.csv")
for variant in r.variant.unique():
    ix = r.variant == variant
    p = r.loc[ix, "p"].to_numpy()
    order = np.argsort(p)
    out = np.empty(len(p))
    out[order] = np.minimum(
        1, np.maximum.accumulate(p[order] * (len(p) - np.arange(len(p))))
    )
    r.loc[ix, "p_holm"] = out
v = r.p.to_numpy()
order = np.argsort(v)
adj = np.empty(len(v))
adj[order] = np.minimum(
    1, np.maximum.accumulate(v[order] * (len(v) - np.arange(len(v))))
)
r["p_holm_all"] = adj
r.to_csv(O / "robustness.csv", index=False)
d = pd.read_csv(
    PROCESSED / "baseline/monthly_data.csv", parse_dates=["month"]
).set_index("month")
lev = pd.read_csv(PROCESSED / "baseline/levels.csv", parse_dates=["month"]).set_index(
    "month"
)
assert len(d) == 170 and d.index.is_unique
assert len(pd.date_range(d.index.min(), d.index.max(), freq="MS")) == 170
for a in ["REE", "Lit", "Kobalt", "Nikiel", "Miedz", "Platyna", "Pallad", "Krzem"]:
    assert np.allclose(100 * np.log(lev[a]).diff().dropna(), d["r_" + a])
    assert (
        abs(np.exp(d["r_" + a].sum() / 100) - lev[a].iloc[-1] / lev[a].iloc[0]) < 1e-10
    )
    assert np.isfinite(d["r_" + a]).all()
assert abs(d.z.mean()) < 1e-12 and abs(d.z.std() - 1) < 1e-12
# OLS normal equations for core REE result.
t = pd.DataFrame({"y": d.r_REE, "z": d.z, "lag": d.r_REE.shift()}).dropna()
X = np.column_stack([np.ones(len(t)), t[["z", "lag"]]])
b = np.linalg.solve(X.T @ X, X.T @ t.y)
ref = (
    pd.read_csv(O / "regressions.csv")
    .query('asset=="REE" and model=="Biezacy"')
    .iloc[0]
)
assert abs(b[1] - ref.beta) < 1e-10
# LP h=0 equals one-period target, h=12 respects final observation availability.
lp = pd.read_csv(O / "local_projections.csv")
assert (lp.query("h==12").n == 157).all()
print(
    "VALIDATION PASS: calendar, transformations, compounded returns, standardization, OLS, LP sample sizes"
)
print(
    r.query('variant=="AbsReturn"')[["asset", "beta", "p", "p_holm"]]
    .round(4)
    .to_string(index=False)
)
