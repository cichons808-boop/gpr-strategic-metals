"""Portfolio accounting for the earlier investment specifications."""

from paths import RAW, PROCESSED, RESULTS
from pathlib import Path
import json, numpy as np, pandas as pd, statsmodels.api as sm
from scipy.optimize import brentq
from statsmodels.stats.multitest import multipletests

R = Path(__file__).resolve().parent
O = RESULTS / "legacy"
D = RAW / "market/daily"

g = (
    pd.read_excel(RAW / "gpr/gpr.xls")
    .set_index("month")[["GPR", "GPRC_CHN"]]
    .loc["2009-01-01":"2026-10-01"]
)
prices = []
for a in ["REMX", "LIT", "COPX", "SPY"]:
    d = json.load(open(D / (a + "_daily.json")))["chart"]["result"][0]
    idx = (
        pd.to_datetime(d["timestamp"], unit="s", utc=True)
        .tz_convert("America/New_York")
        .tz_localize(None)
        .normalize()
    )
    s = pd.Series(
        d["indicators"]["adjclose"][0]["adjclose"], index=idx, name=a
    ).dropna()
    assert s.index.is_unique
    prices.append(s)
p = pd.concat(prices, axis=1).dropna().loc[:"2026-10-31"]
assert (p > 0).all().all()
p.to_csv(PROCESSED / "market/daily_adjusted_prices.csv", index_label="date")
ff = pd.read_csv(RAW / "macro/DFF.csv", index_col=0, parse_dates=True).iloc[:, 0]
ff = pd.to_numeric(ff, errors="coerce")
cal = pd.date_range(ff.index.min(), p.index.max(), freq="D")
ff = ff.reindex(cal).ffill()
cashfactor = 1 + ff.shift(1).bfill() / 100 / 360
cashwealth = cashfactor.cumprod()
cashdaily = cashwealth.reindex(p.index).pct_change().fillna(0)
monthly = p.resample("MS").last()
lagret = 100 * np.log(monthly).diff()
calibration = g.loc["2009":"2018"]
thresholds = {c: float(calibration[c].quantile(0.8)) for c in g}
thresholds_log = {c: float(np.log1p(calibration[c]).quantile(0.8)) for c in g}
rules = [
    "ChinaLow",
    "AvoidChinaHighRising",
    "ChinaHigh",
    "ChinaHighRising",
    "GlobalHighRising",
    "ChinaRising",
    "ARForecast",
    "GPRForecast",
]


def events_for(delay):
    ev = p.groupby(p.index.to_period("M")).apply(
        lambda x: x.index[min(delay - 1, len(x) - 1)]
    )
    ev.index = ev.index.to_timestamp()
    return ev


def positions(asset, delay):
    ev = events_for(delay)
    rows = []
    for month, date in ev.items():
        last = month - pd.offsets.MonthBegin(1)
        prev = last - pd.offsets.MonthBegin(1)
        if (
            last not in g.index
            or prev not in g.index
            or last not in lagret.index
            or not np.isfinite(lagret.loc[last, asset])
        ):
            continue
        level = float(np.log1p(g.loc[last, "GPRC_CHN"]))
        delta = level - float(np.log1p(g.loc[prev, "GPRC_CHN"]))
        H = int(level > thresholds_log["GPRC_CHN"])
        dg = float(np.log1p(g.loc[last, "GPR"]) - np.log1p(g.loc[prev, "GPR"]))
        # All prices used as predictors are from the completed calendar month.
        row = dict(
            month=month,
            date=date,
            info_month=last,
            level=level,
            delta=delta,
            H=H,
            interaction=delta * H,
            lagret=float(lagret.loc[last, asset]),
            cash_forecast=float(ff.shift(1).loc[date] / 100 * 30 / 360),
        )
        row.update(
            ChinaLow=1 - H,
            AvoidChinaHighRising=1 - int(H and delta > 0),
            ChinaHigh=H,
            ChinaHighRising=int(H and delta > 0),
            GlobalHighRising=int(
                np.log1p(g.loc[last, "GPR"]) > thresholds_log["GPR"] and dg > 0
            ),
            ChinaRising=int(delta > 0),
        )
        rows.append(row)
    t = pd.DataFrame(rows).set_index("date")
    t["forward"] = p[asset].reindex(t.index).shift(-1) / p[asset].reindex(t.index) - 1
    t["ARForecast"] = np.nan
    t["GPRForecast"] = np.nan
    t["pred_ar"] = np.nan
    t["pred_gpr"] = np.nan
    t["pred_mean"] = np.nan
    t["train_n"] = 0
    for i in range(len(t)):
        # Exclude label i-1: its endpoint is today's close and cannot be used before execution.
        train = t.iloc[: max(0, i - 1)].dropna(
            subset=["forward", "lagret", "level", "delta", "H", "interaction"]
        )
        test = t.iloc[i]
        if len(train) < 84:
            continue
        for mode, cols, outcol in [
            ("AR", ["lagret"], "ARForecast"),
            ("GPR", ["lagret", "level", "delta", "H", "interaction"], "GPRForecast"),
        ]:
            X = np.column_stack([np.ones(len(train)), train[cols]])
            b = np.linalg.lstsq(X, train.forward, rcond=None)[0]
            forecast = np.r_[1, test[cols].to_numpy(float)] @ b
            t.loc[t.index[i], "pred_" + mode.lower()] = forecast
            t.loc[t.index[i], outcol] = int(forecast > test.cash_forecast)
        t.loc[t.index[i], "pred_mean"] = train.forward.mean()
        t.loc[t.index[i], "train_n"] = len(train)
    return t


start_period = "2019-01"
end = p.index[-1]
allsummary = []
paths = {}
audits = []


def simulate(asset, t, rule, cost=10, start=None):
    t = t.loc[t.month >= pd.Timestamp(start_period)]
    t = t.dropna(subset=[rule]) if rule in rules else t
    if start is None:
        start = t.index[0]
    dates = p.loc[start:end].index
    ev = t[rule].to_dict() if rule in rules else {}
    w = 0.0
    wealth = 10000.0
    ret = []
    turn = []
    held = []
    for i, date in enumerate(dates):
        if i == 0:
            base = 0.0
            q = 0.0
        else:
            q = w
            base = (
                q * (p.loc[date, asset] / p.loc[dates[i - 1], asset] - 1)
                + (1 - q) * cashdaily.loc[date]
            )
        new = float(ev[date]) if date in ev else w
        if rule == "BuyHold":
            new = 1.0
        if rule == "Cash":
            new = 0.0
        if date == dates[-1]:
            new = 0.0
        turnover = abs(new - w)
        net = (1 + base) * (1 - cost / 10000 * turnover) - 1
        wealth *= 1 + net
        ret.append(net)
        turn.append(turnover)
        held.append(q)
        w = new
    result = pd.DataFrame(
        {
            "return": ret,
            "wealth": 10000 * np.cumprod(1 + np.array(ret)),
            "turnover": turn,
            "held": held,
            "cash_return": cashdaily.reindex(dates).to_numpy(),
        },
        index=dates,
    )
    years = (dates[-1] - dates[0]).days / 365.25
    excess = result["return"] - result.cash_return
    excess.iloc[0] = result["return"].iloc[0]
    dd = result.wealth / np.maximum.accumulate(np.r_[10000, result.wealth])[1:] - 1
    stats = dict(
        asset=asset,
        rule=rule,
        cost_bps=cost,
        n_days=len(dates),
        start=str(dates[0].date()),
        end=str(dates[-1].date()),
        final=result.wealth.iloc[-1],
        profit=result.wealth.iloc[-1] - 10000,
        CAGR=(result.wealth.iloc[-1] / 10000) ** (1 / years) - 1,
        vol=result["return"].std(ddof=1) * np.sqrt(252),
        sharpe=(
            excess.mean() / excess.std(ddof=1) * np.sqrt(252)
            if excess.std(ddof=1) > 1e-12
            else np.nan
        ),
        maxdd=float(dd.min()),
        exposure=np.mean(held),
        one_way_turnover=sum(turn),
        years=years,
    )
    return result, stats
