"""State-dependent PrNd regressions and cumulative local projections."""

from paths import RAW, PROCESSED, RESULTS
from pathlib import Path
import json
import numpy as np, pandas as pd
from scipy.stats import norm

R = Path(__file__).resolve().parent
ROOT = R.parent
O = RESULTS / "main"
O.mkdir(exist_ok=True)
g = pd.read_excel(RAW / "gpr/gpr.xls").dropna(subset=["month"]).set_index("month")
prices = pd.read_csv(PROCESSED / "materials/prices.csv", index_col=0, parse_dates=True)
price = prices.PrNd.dropna()
r = 100 * np.log(price).diff()
lg = np.log1p(g.loc["2009":, "GPRC_CHN"])
dg = lg.diff()
cal = dg.loc["2009":"2022"]
z = (dg - cal.mean()) / cal.std()
H = (lg.shift() > lg.loc["2009":"2022"].quantile(0.8)).astype(int)
base = pd.DataFrame({"z": z, "H": H, "zH": z * H, "r_lag1": r.shift()})


def load(series):
    x = pd.read_csv(
        RAW / "macro" / f"{series}.csv", index_col=0, parse_dates=True
    ).iloc[:, 0]
    return pd.to_numeric(x, errors="coerce")


imf = pd.read_excel(RAW / "imf/imf.xlsx", header=None)
dates = pd.to_datetime(imf.iloc[4:, 0].str.replace("M", "-", regex=False) + "-01")
cp = pd.DataFrame(
    {
        "copper": pd.to_numeric(imf.iloc[4:, 29], errors="coerce").to_numpy(),
        "Brent": pd.to_numeric(imf.iloc[4:, 45], errors="coerce").to_numpy(),
    },
    index=dates,
)
macro = pd.DataFrame(
    {
        "China_CLI": (load("CHNLOLITOAASTSAM") - 100) / 10,
        "Global_activity": load("IGREA") / 100,
        "Dollar_return": 100 * np.log(load("TWEXBGSMTH")).diff(),
        "Commodity_return": 100 * np.log(cp).diff().mean(axis=1),
        "China_IP_yoy": load("CHNPRINTO01IXPYM") - 100,
    }
)
macro.to_csv(O / "macro_controls.csv", index_label="month")
maincols = ["China_CLI", "Global_activity", "Dollar_return", "Commodity_return"]


def ols_hac(y, X, L=3):
    t = pd.concat([y.rename("y"), X], axis=1).dropna()
    idx = t.index
    yy = t.y.to_numpy()
    names = ["constant"] + list(X.columns)
    xx = np.column_stack([np.ones(len(t)), t.drop(columns="y")])
    n, k = xx.shape
    assert np.linalg.matrix_rank(xx) == k
    b = np.linalg.lstsq(xx, yy, rcond=None)[0]
    e = yy - xx @ b
    bread = np.linalg.inv(xx.T @ xx)
    scores = (
        pd.DataFrame(xx * e[:, None], index=idx)
        .reindex(pd.date_range(idx.min(), idx.max(), freq="MS"), fill_value=0)
        .to_numpy()
    )
    meat = scores.T @ scores
    for lag in range(1, L + 1):
        q = scores[lag:].T @ scores[:-lag]
        meat += (1 - lag / (L + 1)) * (q + q.T)
    cov = bread @ meat @ bread * n / (n - k)
    return {
        "coef": b,
        "cov": cov,
        "names": names,
        "n": n,
        "data": t,
        "R2": 1 - sum(e * e) / sum((yy - yy.mean()) ** 2),
    }


def contrast(f, terms):
    v = np.array([terms.get(name, 0) for name in f["names"]])
    b = v @ f["coef"]
    se = np.sqrt(max(0, v @ f["cov"] @ v))
    return {
        "beta": float(b),
        "se": float(se),
        "p": float(2 * norm.sf(abs(b / se))),
        "lo": float(b - 1.96 * se),
        "hi": float(b + 1.96 * se),
    }


models = []
designs = {
    "Original_AR1": base,
    "Lagged_economic_controls": base.join(macro[maincols].shift().add_prefix("lag_")),
    "Current_economic_controls": base.join(macro[maincols].add_prefix("current_")),
    "Lagged_IP_controls": base.join(
        macro[["China_IP_yoy", "Global_activity", "Dollar_return", "Commodity_return"]]
        .shift()
        .add_prefix("lag_")
    ),
}
for label, X in list(designs.items()):
    f = ols_hac(r, X)
    high = contrast(f, {"z": 1, "zH": 1})
    low = contrast(f, {"z": 1})
    diff = contrast(f, {"zH": 1})
    t = f["data"]
    t.to_csv(O / f"price_design_{label}.csv", index_label="month")
    models.append(
        dict(
            model=label,
            n=f["n"],
            start=str(t.index.min().date()),
            end=str(t.index.max().date()),
            high_n=int(t.H.sum()),
            high=high["beta"],
            high_se=high["se"],
            p_high=high["p"],
            low=low["beta"],
            p_low=low["p"],
            difference=diff["beta"],
            p_difference=diff["p"],
            R2=f["R2"],
        )
    )
    if label == "Lagged_IP_controls":
        matched = ols_hac(r.reindex(t.index), base.reindex(t.index))
        hh = contrast(matched, {"z": 1, "zH": 1})
        dd = contrast(matched, {"zH": 1})
        models.append(
            dict(
                model="Original_AR1_IP_matched",
                n=matched["n"],
                start=str(t.index.min().date()),
                end=str(t.index.max().date()),
                high_n=int(t.H.sum()),
                high=hh["beta"],
                high_se=hh["se"],
                p_high=hh["p"],
                difference=dd["beta"],
                p_difference=dd["p"],
            )
        )
pd.DataFrame(models).to_csv(O / "price_control_models.csv", index=False)

# Three own-return lags and three risk-change lags, plus lagged economic controls.
dynamic = base.drop(columns="r_lag1").copy()
for lag in [1, 2, 3]:
    dynamic[f"r_lag{lag}"] = r.shift(lag)
    dynamic[f"z_lag{lag}"] = z.shift(lag)
dynamic = dynamic.join(macro[maincols].shift().add_prefix("lag_"))
out = []
long_target = 100 * (np.log(price.shift(-12)) - np.log(price.shift()))
common = pd.concat([long_target.rename("target"), dynamic], axis=1).dropna().index
for sample in ["horizon_specific", "common_h0_h12"]:
    for h in range(13):
        y = 100 * (np.log(price.shift(-h)) - np.log(price.shift()))
        X = dynamic
        if sample == "common_h0_h12":
            y = y.reindex(common)
            X = X.reindex(common)
        fit = ols_hac(y, X, max(3, h + 1))
        t = fit["data"]
        for state, terms in [
            ("low", {"z": 1}),
            ("high", {"z": 1, "zH": 1}),
            ("difference", {"zH": 1}),
        ]:
            c = contrast(fit, terms)
            out.append(
                dict(
                    sample=sample,
                    h=h,
                    state=state,
                    **c,
                    n=fit["n"],
                    high_n=int(t.H.sum()),
                    start=str(t.index.min().date()),
                    end=str(t.index.max().date()),
                    hac_lags=max(3, h + 1),
                )
            )
        if sample == "common_h0_h12":
            t.to_csv(O / f"lp_design_h{h}.csv", index_label="month")
pd.DataFrame(out).to_csv(O / "local_projections.csv", index=False)
json.dump(
    {
        "price_sample": ["2010-03", "2026-01"],
        "risk_calibration": "2009–2022, exploratory and retrospective",
        "controls_primary": "China CLI, global real activity, broad USD return, equal log-return basket of copper and Brent, all lagged one month",
        "IP_sensitivity": "actual OECD industrial-production year-on-year index; no imputation; missing January observations retained as missing",
        "HAC": "Bartlett; scores reindexed to monthly calendar before covariance calculation",
        "LP": "cumulative 100[ln(P[t+h])-ln(P[t-1])], h=0..12; three return/risk lags; pointwise intervals; common-calendar-sample plot; conditional association, not structural identification",
    },
    open(O / "price_settings.json", "w"),
    indent=2,
)
print(pd.DataFrame(models).round(4).to_string(index=False))
print(
    pd.DataFrame(out)
    .query('sample=="common_h0_h12" and state=="high" and h in [0,1,3,6,12]')
    .round(4)
    .to_string(index=False)
)
