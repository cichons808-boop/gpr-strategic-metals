"""Monthly commodity regressions, robustness checks and forecasts."""

from paths import RAW, PROCESSED, RESULTS
from pathlib import Path
import pandas as pd, numpy as np, json, hashlib
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
D = RAW
O = RESULTS / "baseline"
x = pd.read_excel(RAW / "imf/imf.xlsx", header=None)
dates = pd.to_datetime(x.iloc[4:, 0].str.replace("M", "-", regex=False) + "-01")
cols = {
    "REE": 92,
    "Lit": 90,
    "Kobalt": 75,
    "Nikiel": 43,
    "Miedz": 29,
    "Platyna": 79,
    "Pallad": 78,
    "Krzem": 93,
    "Zloto": 76,
    "Brent": 45,
}
names = {
    "REE": "Ziemie rzadkie",
    "Lit": "Lit",
    "Kobalt": "Kobalt",
    "Nikiel": "Nikiel",
    "Miedz": "Miedź",
    "Platyna": "Platyna",
    "Pallad": "Pallad",
    "Krzem": "Krzem",
    "Zloto": "Złoto",
    "Brent": "Brent",
}
p = pd.DataFrame(
    {k: pd.to_numeric(x.iloc[4:, j], errors="coerce").values for k, j in cols.items()},
    index=dates,
)
g = pd.read_excel(RAW / "gpr/gpr.xls").set_index("month")[
    ["GPR", "GPRT", "GPRA", "GPRC_CHN"]
]
levels = p.join(g).loc["2012-06-01":"2026-08-01"].copy()
assert not levels.isna().any().any()
assert (levels > 0).all().all()
r = 100 * np.log(levels[list(cols)]).diff()
q = np.log1p(levels[["GPR", "GPRT", "GPRA", "GPRC_CHN"]]).diff()
z = (q - q.mean()) / q.std(ddof=1)
z.columns = ["z", "zt", "za", "zc"]
df = levels.join(r.add_prefix("r_")).join(z).iloc[1:]
assets = list(cols)[:8]
df.to_csv(PROCESSED / "baseline/monthly_data.csv", index_label="month")
levels.to_csv(PROCESSED / "baseline/levels.csv", index_label="month")
meta = {
    k: {
        "column_zero_based": j,
        "source_header": str(x.iloc[1, j]),
        "source_code": str(x.iloc[0, j]),
    }
    for k, j in cols.items()
}
json.dump(
    meta,
    open(PROCESSED / "baseline/source_dictionary.json", "w"),
    ensure_ascii=False,
    indent=2,
)


# OLS + Bartlett HAC, finite sample n/(n-k), asymptotic normal p-values.
def fit(y, X, L=3):
    t = pd.concat([y.rename("y"), X], axis=1).dropna()
    Y = t.pop("y").to_numpy(float)
    X = t.to_numpy(float)
    X = np.column_stack([np.ones(len(Y)), X])
    n, k = X.shape
    b = np.linalg.lstsq(X, Y, rcond=None)[0]
    e = Y - X @ b
    bread = np.linalg.inv(X.T @ X)
    v = X * e[:, None]
    S = v.T @ v
    scores = (
        pd.DataFrame(v, index=t.index)
        .reindex(pd.date_range(t.index.min(), t.index.max(), freq="MS"), fill_value=0)
        .to_numpy()
    )
    for lag in range(1, min(L, n - 1) + 1):
        A = scores[lag:].T @ scores[:-lag]
        S += (1 - lag / (L + 1)) * (A + A.T)
    cov = bread @ S @ bread * n / (n - k)
    se = np.sqrt(np.maximum(np.diag(cov), 0))
    pv = 2 * stats.norm.sf(np.abs(b / se))
    R2 = 1 - e @ e / np.sum((Y - Y.mean()) ** 2)
    return (
        dict(
            beta=b[1],
            se=se[1],
            p=pv[1],
            lo=b[1] - 1.96 * se[1],
            hi=b[1] + 1.96 * se[1],
            n=n,
            R2=R2,
        ),
        b,
    )


def design(a, zcol="z", lag=False, control=False):
    X = pd.DataFrame(
        {"z": df[zcol].shift(1) if lag else df[zcol], "r_lag": df["r_" + a].shift(1)},
        index=df.index,
    )
    if control:
        X["Brent"] = df.r_Brent
        X["Zloto"] = df.r_Zloto
    return X


rows = []
for a in assets:
    for m, lag, ctrl in [
        ("Biezacy", False, False),
        ("Warunkowy", False, True),
        ("Predykcyjny", True, False),
    ]:
        o, b = fit(df["r_" + a], design(a, lag=lag, control=ctrl))
        rows.append(dict(asset=a, model=m, **o))
res = pd.DataFrame(rows)


# Holm correction separately within each family of eight tests, arbitrary dependence.
def holm(p):
    p = np.array(p)
    order = np.argsort(p)
    out = np.empty(len(p))
    out[order] = np.minimum(
        1, np.maximum.accumulate(p[order] * (len(p) - np.arange(len(p))))
    )
    return out


for m in res.model.unique():
    ix = res.model == m
    res.loc[ix, "p_holm"] = holm(res.loc[ix, "p"])
res.to_csv(O / "regressions.csv", index=False)
desc = []
for a in assets:
    s = df["r_" + a]
    desc.append(
        dict(
            asset=a,
            n=len(s),
            mean=s.mean(),
            sd=s.std(),
            min=s.min(),
            max=s.max(),
            skew=s.skew(),
            kurt=s.kurt(),
            acf1=s.autocorr(),
            cum=100 * (levels[a].iloc[-1] / levels[a].iloc[0] - 1),
            corr=s.corr(df.z),
            spearman=stats.spearmanr(s, df.z).statistic,
        )
    )
desc = pd.DataFrame(desc)
desc.to_csv(O / "statistics.csv", index=False)
# robustness: same standardization full sample; no transformed time index.
rob = []
for a in assets:
    for variant in [
        "HAC6",
        "HAC12",
        "Winsor1",
        "Bez2022",
        "Do2019",
        "Od2020",
        "GPRT",
        "GPRA",
        "Chiny",
        "AsymPlus",
        "AsymMinus",
        "AbsReturn",
    ]:
        X = design(a)
        y = df["r_" + a].copy()
        L = 3
        if variant.startswith("HAC"):
            L = int(variant[3:])
        if variant == "Winsor1":
            y = y.clip(y.quantile(0.01), y.quantile(0.99))
            X["r_lag"] = y.shift(1)
            X["z"] = df.z.clip(df.z.quantile(0.01), df.z.quantile(0.99))
        if variant == "Bez2022":
            y = y.where(df.index.year != 2022)
        if variant == "Do2019":
            y = y.where(df.index.year <= 2019)
        if variant == "Od2020":
            y = y.where(df.index.year >= 2020)
        if variant in ["GPRT", "GPRA", "Chiny"]:
            X = design(a, {"GPRT": "zt", "GPRA": "za", "Chiny": "zc"}[variant])
        if variant in ["AsymPlus", "AsymMinus"]:
            pos = df.z.clip(lower=0)
            neg = df.z.clip(upper=0)
            X = pd.DataFrame(
                {
                    "z": pos if variant == "AsymPlus" else neg,
                    "other": neg if variant == "AsymPlus" else pos,
                    "r_lag": df["r_" + a].shift(1),
                }
            )
        if variant == "AbsReturn":
            y = y.abs()
            X["r_lag"] = y.shift(1)
        o, b = fit(y, X, L)
        rob.append(dict(asset=a, variant=variant, **o))
rob = pd.DataFrame(rob)
rob.to_csv(O / "robustness.csv", index=False)
# Local projections cumulative from t-1 through t+h, with lagged returns and GPR changes.
lp = []
for a in assets:
    X = design(a)
    X["z_lag"] = df.z.shift(1)
    for h in range(13):
        Y = 100 * (np.log(levels[a]).shift(-h) - np.log(levels[a]).shift(1)).reindex(
            df.index
        )
        o, b = fit(Y, X, max(3, h + 1))
        lp.append(dict(asset=a, h=h, **o))
lp = pd.DataFrame(lp)
lp.to_csv(O / "local_projections.csv", index=False)
# expanding forecasts: at t-1 use z[t-2], return[t-2]; one-month publication buffer.
fcasts = []
for a in assets:
    T = pd.DataFrame(
        {"y": df["r_" + a], "z": df.z.shift(2), "r": df["r_" + a].shift(2)}
    ).dropna()
    for i in range(85, len(T)):
        tr = T.iloc[: i - 1]
        te = T.iloc[i]
        nt = len(tr)
        X = np.column_stack([np.ones(nt), tr[["z", "r"]]])
        b = np.linalg.lstsq(X, tr.y, rcond=None)[0]
        br = np.linalg.lstsq(np.column_stack([np.ones(nt), tr.r]), tr.y, rcond=None)[0]
        fcasts.append(
            dict(
                asset=a,
                date=T.index[i],
                actual=te.y,
                forecast=np.array([1, te.z, te.r]) @ b,
                baseline=tr.y.mean(),
                ar=np.array([1, te.r]) @ br,
            )
        )
fcasts = pd.DataFrame(fcasts)
fcasts.to_csv(O / "forecasts.csv", index=False)
fs = []
for a, t in fcasts.groupby("asset", sort=False):
    mse = np.mean((t.actual - t.forecast) ** 2)
    fs.append(
        dict(
            asset=a,
            n=len(t),
            R2_oos=1 - mse / np.mean((t.actual - t.baseline) ** 2),
            R2_vs_ar=1 - mse / np.mean((t.actual - t.ar) ** 2),
            RMSE=np.sqrt(mse),
        )
    )
fs = pd.DataFrame(fs)
fs.to_csv(O / "forecast_metrics.csv", index=False)
# Descriptive high-GPR regime comparisons.
cut = df.GPR.quantile(0.8)
reg = []
for a in assets:
    for high in [False, True]:
        s = df.loc[(df.GPR >= cut) == high, "r_" + a]
        reg.append(
            dict(
                asset=a,
                high=high,
                n=len(s),
                mean=s.mean(),
                sd=s.std(),
                meanabs=s.abs().mean(),
            )
        )
reg = pd.DataFrame(reg)
reg.to_csv(O / "regimes.csv", index=False)
