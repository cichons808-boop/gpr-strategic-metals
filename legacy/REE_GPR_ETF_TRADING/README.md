# Geopolitical risk and rare-earth ETFs — empirical module

## Objective
Does the Caldara–Iacoviello (2022) geopolitical-risk index co-move with rare-earth ETF returns, and does it have predictive information beyond equity / mining-sector returns?

**Primary instrument:** REMX (VanEck Rare Earth and Strategic Metals ETF, US). For shorter comparison samples: ISTM, SETM (broad critical-materials proxy), EART (2026-04 onward), REXC (2026-05 onward). **Controls:** SPY (US equities), XME (metals/mining).

REMX and these proxies hold *equity securities*, not physical rare-earth spot inventories. The sample composition changes through time and some funds have very short histories. This is an ETF study, not a pure study of NdPr/Dy/Tb spot prices.

## Linux Mint — one command
```bash
unzip REE_GPR_ETF.zip
cd REE_GPR_ETF
./run.sh --refresh
```

To re-run **without connecting** (after first successful download):
```bash
./run.sh --offline
```

### Data sources
- GPR: https://www.matteoiacoviello.com/gpr.htm — latest official monthly Excel, `https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls`; fallback official Stata file if Excel download fails. Series: `GPR`, `GPRT` (threats), `GPRA` (acts).
- Price data: Yahoo Finance via `yfinance.download(auto_adjust=True)`, USD, daily adjusted close. Last **available trading date in each calendar month** forms the monthly close. Returns are 100 × differences of logarithms (percentage points), so 3-month cumulative returns sum naturally.
- As of the 2026-10-17 project design: EART = formerly DMAT, strategy/index revised **2026-03-01**; historical returns before that point deliberately dropped. REXC inception mid-April 2026; first complete month May 2026. No sensible 24-month regression is yet possible for these newer series.
- **Data not pre-packaged**: Run locally with internet. This environment could not fetch the remote GPR/ETF bytes; there are no invented numerical findings in this package.

### Specifications
Let `z_t = Δlog(1 + GPR_t) / SD(Δlog(1+GPR))`, SD computed across the chosen GPR history. These are changes in the news-based index, *not structurally identified shocks*.

1. Contemporaneous explanatory model: `r_ETF,t = a + b*z_t + c*r_SPY,t + d*r_XME,t + e_t`.
2. Predictive model: `r_ETF,t+1 = a + b*z_t + c*r_SPY,t + d*r_XME,t + phi*r_ETF,t + e_(t+1)`.
3. Pearson lead/lag correlations: `corr(z_t, r_ETF,t+h)`, h = −3,...,+3 (negative h means ETF return PRECEDES GPR).
4. Event study: top-decile positive GPR changes, events spaced 4+ months apart; return in event month and cumulative log returns over *subsequent* 1 and 3 months. It is descriptive (not causal event identification).

HAC/Newey–West heteroscedasticity/autocorrelation robust errors with 3 lags. Report b in percentage points for a one-SD increase in monthly GPR change. At least 24 complete observations required to estimate a regression.

### Files created upon successful run
```
output/
  raw/       downloaded monthly GPR / daily ETF close files (cached)
  tables/    panel_monthly.csv, gpr_monthly.csv, etf_prices_returns_long.csv,
             regressions_hac.csv, regressions_hac.tex,
             correlations_lags.csv, event_observations.csv, event_averages.csv
  figures/   01_gpr_remx.png, 02_regression_betas.png,
             03_lag_correlations.png, 04_gpr_event_study.png
  metadata.json
```

### Research caveats
- **No causal identification**: contemporaneous GPR/ETF moves are jointly exposed to other macro/geopolitical news.
- Monthly GPR is published with a lag, and the current month may be preliminary. Contemporaneous `GPR_t` is not a real-time trading signal available on the first day of t. The predictive model assumes final month-t GPR is observable by the end of month t; publication-date / historical vintage analysis is needed for strict tradability.
- GPR often jumps during equity selloffs; SPY and XME controls are especially important. XME can also be a mediator (not just a confounder), so compare controlled and unconditional correlation.
- Test sensitivity to oil, VIX, US dollar, interest rates; distinguish GPRT vs GPRA; use rolling and subperiod samples.
- Multiple ETF/time-horizon testing creates multiple comparisons. Later work should preregister the REMX/main spec and assess out-of-sample forecasting.
- Yahoo-adjusted prices are third-party data, subject to revision and data provider restrictions. For formal publication, cross-check fund NAV/total-return series from issuers/market-data vendors.

### Citations
Caldara, D., & Iacoviello, M. (2022). Measuring Geopolitical Risk. *American Economic Review*, 112(4), 1194–1225. https://doi.org/10.1257/aer.20191823

ETF issuers: VanEck (REMX), iShares (ISTM), Sprott (SETM, REXC), Global X (EART). Record dates and prospectus changes in the paper.

## Trading backtest (new)

See [README_TRADING.md](README_TRADING.md). Run `./run_trading.sh --cost-bps 10` using the existing monthly panel.
