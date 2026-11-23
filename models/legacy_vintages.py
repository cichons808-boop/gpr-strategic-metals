"""Archived-release comparison for the earlier investment specifications."""

from paths import RAW, PROCESSED, RESULTS
from pathlib import Path
import pandas as pd, numpy as np, json, urllib.request
import legacy_market as engine

R = Path(__file__).resolve().parent
O = RESULTS / "legacy"
D = RAW / "gpr/vintages"
basepath = D / "data_gpr_export_202201.dta"
assert basepath.exists(), basepath
base = pd.read_stata(basepath).dropna(subset=["month"]).set_index("month").sort_index()
cal = base.loc["2009":"2018"]
q0 = float(np.log1p(cal.GPRC_CHN).quantile(0.8))
engine.start_period = "2022-03"
summary = []
all_signals = []
diffs = []
for delay in [3, 6, 11]:
    ev = engine.events_for(delay)
    rows = []
    for month, date in ev.items():
        if month < pd.Timestamp("2022-03-01"):
            continue
        path = D / ("data_gpr_export_" + month.strftime("%Y%m") + ".dta")
        assert path.exists(), path
        x = pd.read_stata(path).dropna(subset=["month"]).set_index("month").sort_index()
        last = month - pd.offsets.MonthBegin(1)
        prev = last - pd.offsets.MonthBegin(1)
        assert last in x.index
        level = float(np.log1p(x.loc[last, "GPRC_CHN"]))
        delta = level - float(np.log1p(x.loc[prev, "GPRC_CHN"]))
        H = int(level > q0)
        latest_level = float(np.log1p(engine.g.loc[last, "GPRC_CHN"]))
        latestH = int(latest_level > q0)
        rows.append(
            dict(
                month=month,
                date=date,
                info_month=last,
                vintage=month.strftime("%Y%m"),
                gpr_chn=x.loc[last, "GPRC_CHN"],
                threshold_log=q0,
                ChinaLow=1 - H,
                ChinaHigh=H,
                ChinaHighRising=int(H and delta > 0),
                AvoidChinaHighRising=1 - int(H and delta > 0),
                latest_low=1 - latestH,
            )
        )
    t = pd.DataFrame(rows).set_index("date")
    t.to_csv(O / ("vintage_signals_delay" + str(delay) + ".csv"))
    all_signals.append(t.assign(delay=delay))
    diffs.append(
        dict(
            delay=delay,
            n=len(t),
            different_low_classification=int((t.ChinaLow != t.latest_low).sum()),
        )
    )
    for asset in ["REMX", "LIT", "COPX"]:
        for rule in [
            "ChinaLow",
            "ChinaHigh",
            "ChinaHighRising",
            "AvoidChinaHighRising",
            "BuyHold",
            "Cash",
        ]:
            for cost in [0, 10, 25, 50] if delay == 6 else [10]:
                path, stats = engine.simulate(asset, t, rule, cost)
                stats["delay"] = delay
                summary.append(stats)
                if delay == 6 and cost == 10:
                    path.to_csv(
                        O / ("vintage_" + asset + "_" + rule + "_daily.csv"),
                        index_label="date",
                    )
    if delay == 6:
        for cost in [0, 10, 25, 50]:
            path, stats = engine.simulate("SPY", t, "BuyHold", cost)
            stats["delay"] = delay
            summary.append(stats)
            if cost == 10:
                path.to_csv(O / "vintage_SPY_BuyHold_daily.csv", index_label="date")
        matched = t.copy()
        matched.ChinaLow = matched.latest_low
        path, stats = engine.simulate("REMX", matched, "ChinaLow", 10)
        path.to_csv(O / "matched_latest_REMX_ChinaLow_daily.csv", index_label="date")
        stats["delay"] = 6
        stats["rule"] = "LatestMatchedLow"
        summary.append(stats)
pd.DataFrame(summary).to_csv(O / "vintage_strategy_metrics.csv", index=False)
pd.DataFrame(diffs).to_csv(O / "vintage_signal_differences.csv", index=False)
# Partial calendar years are reported as realized, nonannualized returns.
years = []
for asset in ["REMX", "LIT", "COPX", "SPY"]:
    for rule in (
        ["ChinaLow", "ChinaHighRising", "BuyHold", "Cash"]
        if asset != "SPY"
        else ["BuyHold"]
    ):
        x = pd.read_csv(
            O / ("vintage_" + asset + "_" + rule + "_daily.csv"),
            index_col=0,
            parse_dates=True,
        )
        for year, t in x.groupby(x.index.year):
            years.append(
                dict(
                    asset=asset,
                    rule=rule,
                    year=year,
                    return_pct=100 * ((1 + t["return"]).prod() - 1),
                )
            )
pd.DataFrame(years).to_csv(O / "vintage_annual_returns.csv", index=False)
# Bootstrap applies to paired calendar-month returns; endpoints can be partial.
rng = np.random.default_rng(20221117)
a = pd.read_csv(O / "vintage_REMX_ChinaLow_daily.csv", index_col=0, parse_dates=True)
bench = {
    k: pd.read_csv(
        O / ("vintage_REMX_" + k + "_daily.csv"), index_col=0, parse_dates=True
    )
    for k in ["BuyHold", "Cash"]
}
monthly = lambda p: np.log1p(p["return"]).groupby(p.index.to_period("M")).sum()
aa = monthly(a)
boots = []
for L in [6, 12]:
    for name, p in bench.items():
        x = (aa - monthly(p)).values
        vals = []
        for i in range(1999):
            ix = np.concatenate(
                [
                    (rng.integers(len(x)) + np.arange(L)) % len(x)
                    for _ in range(int(np.ceil(len(x) / L)))
                ]
            )[: len(x)]
            vals.append(12 * np.mean(x[ix]))
        boots.append(
            dict(
                benchmark=name,
                block=L,
                B=1999,
                annual_log_point=12 * np.mean(x),
                lo=np.quantile(vals, 0.025),
                hi=np.quantile(vals, 0.975),
            )
        )
pd.DataFrame(boots).to_csv(O / "vintage_bootstrap.csv", index=False)
# Alternative thresholds use 70th, 80th and 90th percentiles of the frozen 2009-2018 history.
threshold_rows = []
t = pd.read_csv(
    O / "vintage_signals_delay6.csv", index_col=0, parse_dates=["date", "month"]
)
t.index = pd.to_datetime(t.index)
for quantile in [0.7, 0.8, 0.9]:
    u = t.copy()
    threshold = float(np.log1p(cal.GPRC_CHN).quantile(quantile))
    u.ChinaLow = (np.log1p(u.gpr_chn) <= threshold).astype(int)
    path, stats = engine.simulate("REMX", u, "ChinaLow", 10)
    stats["quantile"] = quantile
    threshold_rows.append(stats)
pd.DataFrame(threshold_rows).to_csv(
    O / "vintage_threshold_sensitivity.csv", index=False
)
json.dump(
    {
        "start": "2022-03",
        "calibration_vintage": "202201",
        "calibration_period": "2009-2018",
        "threshold_log": q0,
        "threshold_level": float(np.expm1(q0)),
        "vintage_months": len(t),
        "availability_assumption": "named release month, traded sixth NYSE session; upload timestamps not audited",
        "selection_status": "secondary rule selected after seeing latest-vintage performance",
    },
    open(O / "vintage_settings.json", "w"),
    indent=2,
)
print(
    pd.DataFrame(summary)
    .query("delay==6 and cost_bps==10")[
        [
            "asset",
            "rule",
            "CAGR",
            "final",
            "sharpe",
            "maxdd",
            "exposure",
            "one_way_turnover",
        ]
    ]
    .round(4)
    .to_string(index=False)
)
print(pd.DataFrame(diffs))
print(pd.DataFrame(boots).round(4).to_string(index=False))
print(
    pd.DataFrame(threshold_rows)[["quantile", "CAGR", "final", "maxdd"]]
    .round(4)
    .to_string(index=False)
)
