# GPR direction strategy on REMX (Caldara–Iacoviello)

## Trading rule

At each presumed publication of the **monthly** GPR index, use the change of the **last complete reported month** relative to the month before that:

- `ΔGPR > 0`: buy / hold 100% long REMX.
- `ΔGPR <= 0`: liquidate and hold cash (the primary long/cash strategy).
- Alternative long/short: `ΔGPR > 0` long 100%; otherwise short 100%.
- Additional diagnostic: reverse long/cash; baseline buy-and-hold.

A new signal executes at the **close of the first REMX trading day strictly after the assumed release calendar day**, so profit and loss from that new position only begins on the following trading session. Not the calendar month-end before GPR could have been known. Uses daily adjusted closes (`output/raw/REMX_adjusted_daily.csv`), 10 bps per 100% position change, 3% annual borrow on shorts, no cash interest.

The website says monthly GPR is updated at the beginning of each month, with archived monthly dataset vintages named `data_gpr_export_YYYYMM.xls` / `.dta`. Exact intraday historical releases are not inferred from these filenames. `--release-day 10` is an assumption, not a documented daily release calendar. Run sensitivity tests with `--release-day 5` and `15`.

## Fast preliminary result (already-cached revised GPR)

Copy `gpr_direction_strategy.py` to `~/Pobrane/REE_GPR_ETF/`, then:

```bash
cd ~/Pobrane/REE_GPR_ETF
.venv/bin/python gpr_direction_strategy.py --source final --release-day 10
```

This is **time-shifted correctly** (no trade before assumed publication), but historical GPR values come from a currently revised dataset, so this is **not true point-in-time research**. This matters if the trading signal changed after revisions.

## More rigorous historically available data

Downloads month-specific release vintages from the official author's GitHub archive (may consume considerable bandwidth and disk space):

```bash
.venv/bin/python gpr_direction_strategy.py --source vintage --fetch-vintages --start 2018-01 --release-day 10
```

Only covers periods whose historical release files are actually available. `--fetch-vintages` downloads *archived contemporaneous datasets*, **not the current GPR series**. Subsequent runs can omit `--fetch-vintages`. Be aware: using vintage month YYYYMM does not by itself establish the **exact historical release day**; this script assumes publication by the chosen calendar day and buys only after that date. Exact no-lookahead timing would require actual timestamped releases (or a more conservative entry).

A stricter timing stress test:

```bash
.venv/bin/python gpr_direction_strategy.py --source vintage --release-day 20 --out output/gpr_sign_day20
```

## Outputs (also opened automatically on Linux with `xdg-open`)

`output/gpr_sign_strategy/summary.csv` returns CAGR, Sharpe, max drawdown, trading costs.

`output/gpr_sign_strategy/daily_trades.csv` records every price-change interval, position and fees.

`output/gpr_sign_strategy/published_signals.csv` records report month, vintage date, assumed release and trade close.

`output/gpr_sign_strategy/figures/gpr_strategy_equity.png` overlays long/cash, long/short, reverse rule, and buy/hold.

`output/gpr_sign_strategy/figures/gpr_strategy_equity_positions.png` shows equity and daily position histories.

`output/gpr_sign_strategy/figures/gpr_strategy_monthly_returns.png` shows monthly PnL.

Source of GPR: https://www.matteoiacoviello.com/gpr.htm ; historical vintages: https://github.com/iacoviel/iacoviel.github.io/tree/master/gpr_archive_files . Historical GPR levels might be revised; adjusted Yahoo prices are not literal executable quotes, and short borrow availability is not assured.
