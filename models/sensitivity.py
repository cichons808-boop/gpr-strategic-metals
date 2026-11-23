"""Fixed and rolling thresholds with paired block-bootstrap intervals."""

from paths import RAW, PROCESSED, RESULTS
from pathlib import Path
import numpy as np, pandas as pd
import market as m

R = Path(__file__).resolve().parent
ROOT = R.parent
O = RESULTS / "main"
rows = []
base = (
    pd.read_stata(RAW / "gpr/vintages/data_gpr_export_202201.dta")
    .dropna(subset=["month"])
    .set_index("month")
    .sort_index()
)
archive = {}
for month, date in m.events().items():
    if month >= pd.Timestamp("2022-03-01"):
        archive[date] = (
            pd.read_stata(RAW / "gpr/vintages" / f"data_gpr_export_{month:%Y%m}.dta")
            .dropna(subset=["month"])
            .set_index("month")
            .sort_index()
        )
for sample, start in [("post2018", "2018-03-01"), ("archived2022", "2022-03-01")]:
    template = m.make_features("REMX", delay=11 if sample == "post2018" else 6)[0]
    for mode in ["fixed", "rolling120"]:
        for quantile in [0.7, 0.8, 0.9]:
            t = template.loc[template.month >= pd.Timestamp(start)].copy()
            for date, row in t.iterrows():
                risk = m.g if sample == "post2018" else archive[date]
                last = row.info_month
                previous = last - pd.offsets.MonthBegin(1)
                if mode == "fixed":
                    hist = (
                        m.g.loc["2009":"2017"]
                        if sample == "post2018"
                        else base.loc["2009":"2018"]
                    )
                else:
                    hist = risk.loc[:previous].tail(120)
                assert hist.index.max() < last
                qc = np.log1p(hist.GPRC_CHN).quantile(quantile)
                qg = np.log1p(hist.GPR).quantile(quantile)
                c = np.log1p(risk.loc[last, "GPRC_CHN"])
                dc = c - np.log1p(risk.loc[previous, "GPRC_CHN"])
                gg = np.log1p(risk.loc[last, "GPR"])
                dg = gg - np.log1p(risk.loc[previous, "GPR"])
                H = int(c > qc)
                vals = dict(
                    ChinaLow=1 - H,
                    ChinaHigh=H,
                    ChinaHighRising=int(H and dc > 0),
                    AvoidChinaHighRising=1 - int(H and dc > 0),
                    GlobalHighRising=int(gg > qg and dg > 0),
                    ChinaRising=int(dc > 0),
                )
                for col, value in vals.items():
                    t.loc[date, col] = value
            t[["month", "info_month"] + m.RULES].to_csv(
                O / f"sensitivity_{sample}_{mode}_q{int(quantile*100)}_signals.csv"
            )
            for asset in m.ASSETS:
                for rule in m.RULES:
                    _, stats = m.simulate(m.asset_weights(t, asset, rule))
                    stats.update(
                        sample=sample,
                        asset=asset,
                        rule=rule,
                        mode=mode,
                        quantile=quantile,
                    )
                    rows.append(stats)
pd.DataFrame(rows).to_csv(O / "threshold_sensitivity.csv", index=False)

rng = np.random.default_rng(182026)
boot = []
for sample in ["post2018", "archived2022"]:
    for asset, rule in [
        ("REMX", "ChinaLow"),
        ("LIT", "AvoidChinaHighRising"),
        ("COPX", "AvoidChinaHighRising"),
    ]:
        p = pd.read_csv(
            O / f"{sample}_{asset}_{rule}_daily.csv", index_col=0, parse_dates=True
        )
        a = np.log1p(p["return"]).groupby(p.index.to_period("M")).sum()
        for benchmark in ["BuyHold", "Cash", "MA200", "TSMOM12"]:
            b = pd.read_csv(
                O / f"{sample}_{asset}_{benchmark}_daily.csv",
                index_col=0,
                parse_dates=True,
            )
            lr = np.log1p(b["return"]).groupby(b.index.to_period("M")).sum()
            x = (a - lr).to_numpy()
            n = len(x)
            for L in [6, 12]:
                starts = rng.integers(n, size=(1999, int(np.ceil(n / L))))
                ix = ((starts[:, :, None] + np.arange(L)) % n).reshape(1999, -1)[:, :n]
                vals = 12 * x[ix].mean(axis=1)
                boot.append(
                    dict(
                        sample=sample,
                        asset=asset,
                        rule=rule,
                        benchmark=benchmark,
                        block=L,
                        B=1999,
                        annual_log_difference=12 * x.mean(),
                        lo=np.quantile(vals, 0.025),
                        hi=np.quantile(vals, 0.975),
                    )
                )
pd.DataFrame(boot).to_csv(O / "paired_bootstrap.csv", index=False)
print(
    pd.DataFrame(rows)
    .query('quantile==.8 and rule=="AvoidChinaHighRising" and asset in ["LIT","COPX"]')[
        ["sample", "asset", "mode", "CAGR", "maxdd"]
    ]
    .round(4)
    .to_string(index=False)
)
print(
    pd.DataFrame(boot)
    .query('sample=="post2018" and block==6 and benchmark=="MA200"')
    .round(4)
    .to_string(index=False)
)
