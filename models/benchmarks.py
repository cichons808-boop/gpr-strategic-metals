"""GPR allocations, price benchmarks, forecasts and factor attribution."""

from paths import RAW, PROCESSED, RESULTS
from pathlib import Path
import json
import numpy as np, pandas as pd, statsmodels.api as sm
from scipy.stats import norm
from statsmodels.stats.multitest import multipletests
import market as m

R = Path(__file__).resolve().parent
ROOT = R.parent
O = RESULTS / "main"
paths = {}
summary = []
forecast_rows = []
all_audits = []


def keep(sample, asset, rule, t, cost=10, end=None):
    if rule == "DailyMA200":
        dates = (
            m.p.loc[t.index.min() : end].index
            if end is not None
            else m.p.loc[t.index.min() :].index
        )
        weights = pd.DataFrame(0.0, index=dates, columns=m.TRADED)
        weights[asset] = (
            (m.allprices[asset] > m.ma[asset]).shift(1).reindex(dates).astype(float)
        )
    else:
        weights = (
            m.sector_weights(t.index)
            if rule == "SectorRotation"
            else m.asset_weights(t, asset, rule)
        )
    path, stats = m.simulate(weights, cost=cost, end=end)
    stats.update(sample=sample, asset=asset, rule=rule)
    summary.append(stats)
    if cost == 10:
        paths[(sample, asset, rule)] = path
        path.to_csv(O / f"{sample}_{asset}_{rule}_daily.csv", index_label="date")
    return path, stats


def prediction_metrics(sample, asset, t):
    q = t.dropna(
        subset=[
            "forward",
            "pred_MarketForecast",
            "pred_GlobalForecast",
            "pred_ChinaForecast",
            "pred_Mean",
        ]
    )
    for model in ["GlobalForecast", "ChinaForecast"]:
        e0 = q.forward - q.pred_MarketForecast
        e1 = q.forward - q["pred_" + model]
        adjusted = e0**2 - e1**2 + (q.pred_MarketForecast - q["pred_" + model]) ** 2
        f = sm.OLS(adjusted.to_numpy(), np.ones((len(q), 1))).fit(
            cov_type="HAC", cov_kwds={"maxlags": 3, "use_correction": True}
        )
        forecast_rows.append(
            dict(
                sample=sample,
                asset=asset,
                model=model,
                n=len(q),
                start=str(q.index.min().date()),
                end=str(q.index.max().date()),
                R2_vs_market=1 - np.mean(e1**2) / np.mean(e0**2),
                R2_vs_mean=1 - np.mean(e1**2) / np.mean((q.forward - q.pred_Mean) ** 2),
                ClarkWest_mean=float(f.params[0]),
                ClarkWest_stat=float(f.tvalues[0]),
                ClarkWest_p=float(norm.sf(f.tvalues[0])),
            )
        )


# Chronological evaluation after the original working paper; revised GPR history is explicit.
for asset in m.ASSETS:
    t, threshold = m.make_features(asset, delay=11)
    t, audit = m.fit_forecasts(t)
    t.to_csv(O / f"post2018_{asset}_signals.csv")
    audit.assign(asset=asset, sample="post2018").to_csv(
        O / f"post2018_{asset}_forecast_audit.csv", index=False
    )
    test = t.loc[t.month >= pd.Timestamp("2018-03-01")].copy()
    assert test[list(m.MODELS)].notna().all().all()
    for rule in (
        m.RULES
        + ["MA200", "DailyMA200", "TSMOM12"]
        + list(m.MODELS)
        + ["BuyHold", "Cash"]
    ):
        for cost in (
            [0, 10, 25, 50]
            if rule
            in ["ChinaLow", "ChinaHigh", "AvoidChinaHighRising", "MA200", "TSMOM12"]
            else [10]
        ):
            keep("post2018", asset, rule, test, cost)
    prediction_metrics("post2018", asset, test)
    if asset == "REMX":
        keep("post2018", "Universe", "SectorRotation", test)
        keep("post2018", "SPY", "BuyHold", test)

# Refit forecast coefficients from each actual archived risk history, using strict label timing.
base = (
    pd.read_stata(RAW / "gpr/vintages/data_gpr_export_202201.dta")
    .dropna(subset=["month"])
    .set_index("month")
    .sort_index()
)
frozen = {
    c: float(np.log1p(base.loc["2009":"2018", c]).quantile(0.8))
    for c in ["GPR", "GPRC_CHN"]
}
prebuilt = {a: m.make_features(a)[0] for a in m.ASSETS}
archrows = {a: [] for a in m.ASSETS}
archaudit = []
for month, date in m.events().items():
    if month < pd.Timestamp("2022-03-01"):
        continue
    source = RAW / "gpr/vintages" / f"data_gpr_export_{month:%Y%m}.dta"
    risk = (
        pd.read_stata(source).dropna(subset=["month"]).set_index("month").sort_index()
    )
    last = month - pd.offsets.MonthBegin(1)
    assert last in risk.index
    for asset, t0 in prebuilt.items():
        t = t0.loc[:date].copy()
        for col, tag in [("GPR", "global"), ("GPRC_CHN", "china")]:
            l = np.log1p(risk[col])
            d = l.diff()
            h = (l > frozen[col]).astype(int)
            for name, series in [
                ("level", l),
                ("change", d),
                ("high", h),
                ("interaction", d * h),
            ]:
                t[tag + "_" + name] = series.reindex(
                    pd.DatetimeIndex(t.info_month)
                ).to_numpy()
        row = t.loc[date].copy()
        H = int(row.china_high)
        delta = row.china_change
        row["ChinaLow"] = 1 - H
        row["ChinaHigh"] = H
        row["ChinaHighRising"] = int(H and delta > 0)
        row["AvoidChinaHighRising"] = 1 - int(H and delta > 0)
        row["ChinaRising"] = int(delta > 0)
        row["GlobalHighRising"] = int(row.global_high and row.global_change > 0)
        train = t.loc[t.forward_end.lt(date)].dropna(
            subset=["forward"] + list(set(sum(list(m.MODELS.values()), [])))
        )
        assert train.forward_end.max() < date
        for model, cols in m.MODELS.items():
            X = np.column_stack([np.ones(len(train)), train[cols]])
            b = np.linalg.lstsq(X, train.forward, rcond=None)[0]
            pred = np.r_[1, row[cols].to_numpy(float)] @ b
            row["pred_" + model] = pred
            row[model] = int(pred > row.cash_forecast)
        row["pred_Mean"] = train.forward.mean()
        row["date"] = date
        row["vintage"] = month.strftime("%Y%m")
        archrows[asset].append(row)
        archaudit.append(
            dict(
                asset=asset,
                date=date,
                vintage=month.strftime("%Y%m"),
                train_n=len(train),
                last_training_target_end=train.forward_end.max(),
                info_month=last,
            )
        )
pd.DataFrame(archaudit).to_csv(O / "archive_forecast_audit.csv", index=False)
for asset, rows in archrows.items():
    t = pd.DataFrame(rows).set_index("date")
    t.to_csv(O / f"archived2022_{asset}_signals.csv")
    for rule in (
        m.RULES
        + ["MA200", "DailyMA200", "TSMOM12"]
        + list(m.MODELS)
        + ["BuyHold", "Cash"]
    ):
        keep("archived2022", asset, rule, t)
    prediction_metrics("archived2022", asset, t)
    if asset == "REMX":
        keep("archived2022", "Universe", "SectorRotation", t)
        keep("archived2022", "SPY", "BuyHold", t)

# Old-method sensitivity uses the frozen 2021 workbook; it is not called real-time 2018 data.
oldfile = RAW / "gpr/GPR_OLD_2021_snapshot.xlsx"
oldg = pd.read_excel(oldfile, sheet_name="GPR")
oldg["Date"] = pd.to_datetime(oldg.Date, errors="coerce")
oldg = oldg.dropna(subset=["Date"]).set_index("Date")[["GPR"]]
oldc = pd.read_excel(oldfile, sheet_name="GPR_COUNTRIES")
oldc["Date"] = pd.to_datetime(oldc.Date, errors="coerce")
oldc = (
    oldc.dropna(subset=["Date"])
    .set_index("Date")[["GPR_CHINA"]]
    .rename(columns={"GPR_CHINA": "GPRC_CHN"})
)
oldrisk = oldg.join(oldc).dropna()
oldrisk.to_csv(O / "legacy_method_risk.csv", index_label="month")
legacy = []
for source, risk in [("old_method_2021_snapshot", oldrisk), ("revised_2026", m.g)]:
    t, threshold = m.make_features("REMX", delay=11, risk=risk)
    test = t.loc[
        (t.month >= pd.Timestamp("2018-03-01"))
        & (t.month <= pd.Timestamp("2021-09-01"))
    ]
    for rule in ["GlobalHighRising", "ChinaLow", "ChinaHigh"]:
        path, stats = m.simulate(m.asset_weights(test, "REMX", rule), end="2021-09-30")
        stats.update(source=source, rule=rule)
        legacy.append(stats)
    test.to_csv(O / f"legacy_comparison_{source}_signals.csv")
pd.DataFrame(legacy).to_csv(O / "legacy_method_sensitivity.csv", index=False)

# Compare all GPR candidates with both standard timing benchmarks on paired months.
tests = []
gprrules = m.RULES + ["GlobalForecast", "ChinaForecast"]
for (sample, asset, rule), path in paths.items():
    if asset not in m.ASSETS or rule not in gprrules:
        continue
    y = np.log1p(path["return"]).groupby(path.index.to_period("M")).sum()
    for bench in [
        "BuyHold",
        "Cash",
        "MA200",
        "DailyMA200",
        "TSMOM12",
        "MarketForecast",
    ]:
        b = paths[(sample, asset, bench)]
        yb = np.log1p(b["return"]).groupby(b.index.to_period("M")).sum()
        diff = y - yb
        f = sm.OLS(diff.to_numpy(), np.ones((len(diff), 1))).fit(
            cov_type="HAC", cov_kwds={"maxlags": 3, "use_correction": True}
        )
        tests.append(
            dict(
                sample=sample,
                asset=asset,
                rule=rule,
                benchmark=bench,
                n=len(diff),
                annual_log_difference=float(12 * f.params[0]),
                p_two_sided=float(f.pvalues[0]),
            )
        )
tests = pd.DataFrame(tests)
for sample in tests["sample"].unique():
    for bench in tests.benchmark.unique():
        ix = (tests["sample"] == sample) & (tests.benchmark == bench)
        tests.loc[ix, "p_Holm_24"] = multipletests(
            tests.loc[ix, "p_two_sided"], method="holm"
        )[1]
tests.to_csv(O / "benchmark_tests.csv", index=False)

# Ex-post factor attribution: daily US FF5 plus momentum, through source availability.
from factor_attribution import run as factor_attribution

ff, alphas = factor_attribution(paths)
forecast = pd.DataFrame(forecast_rows)
for sample in forecast["sample"].unique():
    ix = forecast["sample"] == sample
    forecast.loc[ix, "ClarkWest_p_Holm6"] = multipletests(
        forecast.loc[ix, "ClarkWest_p"], method="holm"
    )[1]
forecast.to_csv(O / "forecast_comparison.csv", index=False)
pd.DataFrame(summary).to_csv(O / "benchmark_metrics.csv", index=False)

# Calendar returns retain the partial first and last years.
annual = []
for (sample, asset, rule), path in paths.items():
    for year, x in path.groupby(path.index.year):
        annual.append(
            dict(
                sample=sample,
                asset=asset,
                rule=rule,
                year=year,
                return_pct=100 * (np.prod(1 + x["return"]) - 1),
            )
        )
pd.DataFrame(annual).to_csv(O / "benchmark_annual_returns.csv", index=False)
json.dump(
    {
        "post2018_sample": ["2018-03-15", "2026-10-30"],
        "post2018_execution": "eleventh trading session: conservative allowance for the old monthly update around the tenth calendar day",
        "archive_execution": "sixth trading session under the revised early-month publication convention",
        "initial_training_labels_end": "2017-12-31",
        "threshold_calibration_post2018": "2009–2017, latest revised history",
        "threshold_calibration_archive": "2009–2018 in January 2022 release",
        "initial_model_training_min": 60,
        "forecast_update": "expanding; target endpoint strictly before current execution close",
        "benchmark_MA200": "previous calendar month-end adjusted close above its 200-session average",
        "benchmark_DailyMA200": "previous trading-session close above its own 200-session average; executed at the current close",
        "benchmark_TSMOM12": "previous calendar month-end twelve-month return positive",
        "sector_rotation": "highest positive twelve-minus-one-month return among REMX/LIT/COPX; otherwise cash",
        "factor_model": "daily US FF5 plus US momentum; ex-post attribution, not predictor; annualised arithmetic alpha=252*daily intercept",
        "factor_last_date": str(ff.index.max().date()),
        "selection_status": "retrospective chronological evaluation; rules and period already inspected; not independent confirmation",
        "legacy_data": "old-method 2021 workbook, not a full 2018 vintage sequence",
    },
    open(O / "benchmark_settings.json", "w"),
    indent=2,
)
print(
    pd.DataFrame(summary)
    .query('sample=="post2018" and cost_bps==10')[
        ["asset", "rule", "CAGR", "maxdd", "sharpe"]
    ]
    .round(4)
    .to_string(index=False)
)
print(forecast.round(4).to_string(index=False))
