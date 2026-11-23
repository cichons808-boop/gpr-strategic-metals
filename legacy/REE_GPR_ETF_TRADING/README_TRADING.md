# REE / GPR — trading test (walk-forward VAR)

## Quick run on your computer

From `~/Pobrane/REE_GPR_ETF` (which already contains `output/tables/panel_monthly.csv`):

```bash
./run_trading.sh --cost-bps 10
./run_trading.sh --cost-bps 25 --out output/trading_25bps
```

**No re-download or paid data sources.** The script reads the existing monthly panel created by `src/ree_gpr.py`.

For publication, use REMX as the primary history. SETM has a much shorter out-of-sample window; ISTM may be skipped when the OOS threshold is not reached.

## Hypothesis

Does GPR improve the EX ANTE ETF strategy, once the underlying mining/equity market has already been modelled?

- VAR(1) WITH GPR: `[Δlog(1+GPR), SPY return, XME return, ETF return]`.
- VAR(1) WITHOUT GPR: `[SPY return, XME return, ETF return]`.
- Expanding-window reestimation and two-step-ahead predictions each month.
- **STRICT DATA EMBARGO:** For the traded month *t*, the latest observations the backtest uses are from *t−2* (GPR for t−2 is expected to be released during t−1). Position is taken for return t (end of t−1 to end of t).
- All forecasts fit only information dated through t−2. No random train-test shuffles, future standardization or hyperparameter optimization on the test period.
- Monthly returns were supplied as **log return × 100**; position PnL is computed on correctly converted simple returns.

This intentionally sacrifices some information from t−1 to avoid trading on that month's just-completed close and to impose a consistent reporting embargo.

## Strategy definitions

- `buy_hold`: 100% ETF.
- `gpr_positive_long_cash`: 100% ETF when observed `Δlog(1+GPR)` is positive; otherwise cash.
- `gpr_negative_long_cash`: 100% ETF when that GPR change is negative; otherwise cash (exploratory reverse hypothesis).
- `var_gpr_long_cash`: ETF when with-GPR VAR forecasts positive return; otherwise cash.
- `var_market_long_cash`: the exact same rule using without-GPR VAR.
- `var_gpr_long_short` and `var_market_long_short`: +100% ETF if forecast >0, otherwise -100%. Only a research proxy; short restrictions and borrowing costs may be higher.

All positions are held for one calendar-month return. No leverage above 1× gross exposure. Cash has **0% assumed interest**; monthly holdings are adjusted close proxies (already include ETF expenses). Default transaction cost: 10 basis points **per 100% of position turnover**; switching +1 to −1 costs 20 basis points. Default short borrow fee: 3% annualized, charged monthly. This is a simplification, not an order-book simulation.

## Output

- `output/trading/strategy_summary.csv`: CAGR, Sharpe (zero assumed rf), maximum drawdown, return, turnover and exposure.
- `output/trading/forecast_accuracy.csv`: genuine OOS MSE and directional accuracy; R² improvement over VAR without GPR.
- `output/trading/incremental_gpr_tests.csv`: paired HAC t-tests of incremental net returns from GPR and squared error difference. Multiple-comparison caution applies.
- `output/trading/walkforward_forecasts.csv`: forecasts and the true source month available for each trade.
- `output/trading/monthly_trades.csv`: all monthly positions, costs, net PnL, equity.
- `output/trading/subperiod_performance.csv`: split around 2021 where at least 12 OOS observations are available.
- `output/trading/figures/equity_REMX.png` etc.: OOS equity curves.

Recommended first check: does **VAR+GPR beat VAR without GPR after costs?** A profitable strategy alone is not sufficient; the difference could be general mining beta. Check consistency under 10 and 25 bps and pre/post-2021. SETM is short and should be labelled exploratory.

## IMPORTANT BIASES / LIMITATIONS

1. **Final-vintage GPR is not historical real-time GPR.** The file originally downloaded from `matteoiacoviello.com` reflects historical revisions and changed methodology (2021). Timing lag prevents future-month leakage but does **not** remove revision/lookback bias. For publishable point-in-time claims, replay archived vintage workbooks `data_gpr_export_YYYYMM.xls` rather than final-vintage GPR.
2. **Monthly adjusted-close executions are idealized.** To make fills realistic, reconstruct positions at the next open or next available close using daily prices with published release timestamps. Signal information as of prior month-end is guaranteed only under the lag assumption; the exact release calendars still require verification.
3. **Multiple testing.** GPR-only positive and negative signs, REMX/SETM, model comparisons are exploratory. No selection on OOS profits.
4. **Small sample.** VAR(1) fit on ~26 observations for SETM is fragile. Its OOS performance is a pilot, not independent confirmation.
5. **Cash earns zero here.** Add historical T-bill returns for a more realistic alternative. Short borrowing 3% p.a. is an assumption. No taxes, financing margin, partial fills, order restrictions or dynamic spread model.
6. **VAR tests of Granger predictability are in-sample.** Positive p-values or IRFs from an in-sample VAR do not establish a successful trading strategy.

## Sanity tests

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_trading.py' -v
```

Test data are **synthetic and are NOT genuine performance results**. The real result comes from *your existing panel* after running `./run_trading.sh` on your machine.
