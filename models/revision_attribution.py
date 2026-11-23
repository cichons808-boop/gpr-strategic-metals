"""Wealth attribution for the two changed REMX classifications."""

from paths import RAW, PROCESSED, RESULTS
from pathlib import Path
import itertools, json
import numpy as np, pandas as pd
import market as m

R = Path(__file__).resolve().parent
ROOT = R.parent
O = RESULTS / "main"
t = pd.read_csv(
    O / "archived2022_REMX_signals.csv",
    index_col=0,
    parse_dates=["date", "month", "info_month"],
)
t.index = pd.to_datetime(t.index)
cal = (
    pd.read_stata(RAW / "gpr/vintages/data_gpr_export_202201.dta")
    .dropna(subset=["month"])
    .set_index("month")
)
threshold = float(np.log1p(cal.loc["2009":"2018", "GPRC_CHN"]).quantile(0.8))
latest = np.log1p(m.g.GPRC_CHN.reindex(pd.DatetimeIndex(t.info_month))).to_numpy()
revised = pd.Series((latest <= threshold).astype(int), index=t.index)
changed = t.index[t.ChinaLow != revised]
assert len(changed) == 2
values = {}
combinations = []
for flags in itertools.product([0, 1], repeat=2):
    u = t.copy()
    for j, flag in enumerate(flags):
        if flag:
            u.loc[changed[j], "ChinaLow"] = revised.loc[changed[j]]
    path, stats = m.simulate(m.asset_weights(u, "REMX", "ChinaLow"))
    values[flags] = stats["final"]
    combinations.append(dict(change_first=flags[0], change_second=flags[1], **stats))
    if flags == (1, 1):
        path.to_csv(O / "matched_revised_REMX_ChinaLow_daily.csv", index_label="date")
rows = []
for i, date in enumerate(changed):
    a = (1, 0) if i == 0 else (0, 1)
    b = (0, 1) if i == 0 else (1, 0)
    effect = 0.5 * ((values[a] - values[(0, 0)]) + (values[(1, 1)] - values[b]))
    idx = t.index.get_loc(date)
    end = t.index[idx + 1]
    rows.append(
        dict(
            execution_date=str(date.date()),
            info_month=str(t.loc[date, "info_month"].date()),
            next_execution=str(end.date()),
            archived_weight=int(t.loc[date, "ChinaLow"]),
            revised_weight=int(revised.loc[date]),
            archived_risk=float(np.expm1(t.loc[date, "china_level"])),
            revised_risk=float(np.expm1(latest[idx])),
            ETF_gross_holding_return=float(
                m.p.loc[end, "REMX"] / m.p.loc[date, "REMX"] - 1
            ),
            wealth_attribution_USD=effect,
        )
    )
assert np.isclose(
    sum(row["wealth_attribution_USD"] for row in rows), values[(1, 1)] - values[(0, 0)]
)
pd.DataFrame(rows).to_csv(O / "revision_attribution.csv", index=False)
pd.DataFrame(combinations).to_csv(O / "revision_counterfactuals.csv", index=False)
print(pd.DataFrame(rows).round(4).to_string(index=False))
print("Terminal difference", values[(1, 1)] - values[(0, 0)])
