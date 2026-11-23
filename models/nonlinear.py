"""Quantile, state-dependent and daily PrNd models."""

from paths import RAW, PROCESSED, RESULTS
from pathlib import Path
import pandas as pd, numpy as np, statsmodels.api as sm, warnings

warnings.filterwarnings("ignore")
R = Path(__file__).resolve().parent
O = RESULTS / "materials"
r = pd.read_csv(PROCESSED / "materials/returns.csv", index_col=0, parse_dates=True)
g = pd.read_csv(PROCESSED / "materials/gpr.csv", index_col=0, parse_dates=True)
rows = []
for a in ["PrNd", "neodymium", "samarium", "REMX", "REE"]:
    for gi in ["GPR", "GPRC_CHN"]:
        x = np.log1p(g[gi])
        x = (x - x.loc[:"2022"].mean()) / x.loc[:"2022"].std()
        X = pd.DataFrame({"x": x, "lag": r[a].shift()})
        if a == "REMX":
            X["SPY"] = r.SPY
            X["EEM"] = r.EEM
        t = pd.concat([r[a].rename("y"), X], axis=1).dropna()
        for tau in [0.1, 0.5, 0.9]:
            for sample, sub in [
                ("discovery", t.loc[:"2022"]),
                ("test", t.loc["2023":]),
                ("full", t),
            ]:
                f = sm.QuantReg(sub.y, sm.add_constant(sub.drop(columns="y"))).fit(
                    q=tau, max_iter=5000
                )
                rows.append(
                    dict(
                        asset=a,
                        gpr=gi,
                        tau=tau,
                        sample=sample,
                        beta=f.params.x,
                        p_iid=f.pvalues.x,
                        n=len(sub),
                    )
                )
pd.DataFrame(rows).to_csv(O / "quantiles.csv", index=False)
rows = []
for a in ["PrNd", "neodymium", "samarium", "REMX", "REE"]:
    for gi in ["GPR", "GPRC_CHN"]:
        lg = np.log1p(g[gi])
        x = lg.diff()
        x = (x - x.loc[:"2022"].mean()) / x.loc[:"2022"].std()
        H = (lg.shift() > lg.loc[:"2022"].quantile(0.8)).astype(int)
        X = pd.DataFrame({"x": x, "high": H, "interaction": x * H, "lag": r[a].shift()})
        if a == "REMX":
            X["SPY"] = r.SPY
            X["EEM"] = r.EEM
        t = pd.concat([r[a].rename("y"), X], axis=1).dropna()
        for sample, sub in [
            ("discovery", t.loc[:"2022"]),
            ("test", t.loc["2023":]),
            ("full", t),
        ]:
            f = sm.OLS(sub.y, sm.add_constant(sub.drop(columns="y"))).fit(
                cov_type="HAC", cov_kwds={"maxlags": 3, "use_correction": True}
            )
            L = np.zeros(len(f.params))
            L[list(f.params.index).index("x")] = 1
            L[list(f.params.index).index("interaction")] = 1
            tt = f.t_test(L)
            rows.append(
                dict(
                    asset=a,
                    gpr=gi,
                    sample=sample,
                    beta_low=f.params.x,
                    p_low=f.pvalues.x,
                    beta_high=float(tt.effect[0]),
                    p_high=float(tt.pvalue),
                    difference=f.params.interaction,
                    p_difference=f.pvalues.interaction,
                    n=len(sub),
                    high_n=int(sub.high.sum()),
                )
            )
pd.DataFrame(rows).to_csv(O / "regimes.csv", index=False)
p = pd.read_csv(RAW / "quotes/prnd_long.csv", skiprows=[1])
p.columns = ["date", "price"]
p.date = pd.to_datetime(p.date)
p = p.sort_values("date").drop_duplicates("date").set_index("date").loc[:"2026-01-31"]
gd = pd.read_excel(RAW / "gpr/gpr_daily.xls")
gd.index = pd.to_datetime(gd.DAY.astype(str), format="%Y%m%d")
gd = gd[["GPRD", "GPRD_ACT", "GPRD_THREAT"]]
df = pd.DataFrame({"r": 100 * np.log(p.price).diff()})
for key in gd:
    df[key] = gd[key].rolling(7).mean().reindex(df.index)
df.to_csv(O / "daily_prnd.csv")
out = []
for key in gd:
    for trans in ["level", "change"]:
        x = np.log1p(df[key])
        x = x if trans == "level" else x.diff()
        x = (x - x.loc[:"2022"].mean()) / x.loc[:"2022"].std()
        for dep in ["return", "amplitude"]:
            y = df.r if dep == "return" else df.r.abs()
            X = pd.DataFrame({"x": x.shift(1), "lag": y.shift()})
            t = pd.concat([y.rename("y"), X], axis=1).dropna()
            for sample, sub in [
                ("discovery", t.loc[:"2022"]),
                ("test", t.loc["2023":]),
                ("full", t),
            ]:
                f = sm.OLS(sub.y, sm.add_constant(sub.drop(columns="y"))).fit(
                    cov_type="HAC", cov_kwds={"maxlags": 20, "use_correction": True}
                )
                out.append(
                    dict(
                        index=key,
                        transform=trans,
                        dep=dep,
                        sample=sample,
                        n=len(sub),
                        beta=f.params.x,
                        p=f.pvalues.x,
                        se=f.bse.x,
                    )
                )
pd.DataFrame(out).to_csv(O / "daily_models.csv", index=False)
print(
    pd.read_csv(O / "regimes.csv")
    .query('asset=="PrNd" and gpr=="GPRC_CHN"')
    .round(5)
    .to_string(index=False)
)
