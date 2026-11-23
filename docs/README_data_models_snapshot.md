# GPR and strategic metals

Data and Python models for the analysis of geopolitical risk, material prices
and ETF returns. Data snapshot: 17 November 2026.

## Run

Python 3.12. Install the dependencies and run from this directory:

```bash
python -m pip install -r requirements.txt
python run.py
```

`python run.py --all` also reproduces the earlier model search and historical
investment specifications. This takes longer because it includes the quantile
and block-bootstrap calculations. `python run.py --check` checks the saved main
results. All commands use local data; no API keys or downloads are needed.

## Files

| Directory | Contents |
| --- | --- |
| `data/raw/gpr/` | Current GPR, daily GPR, old-method workbook and 57 archived releases |
| `data/raw/quotes/` | PrNd, neodymium and samarium quotes, with source snapshots |
| `data/raw/imf/` | IMF commodity-price workbook |
| `data/raw/market/` | Daily and monthly adjusted-price responses |
| `data/raw/macro/` | DFF, dollar index, China activity and global activity |
| `data/raw/factors/` | French daily five-factor and momentum files |
| `data/processed/` | Monthly panels, transformed returns and daily ETF prices |
| `models/` | Estimation, forecasts, portfolio accounting and sensitivity checks |
| `results/main/` | Current regressions, local projections, forecasts and backtests |
| `results/materials/` | Linear, quantile, regime and daily material models |
| `results/baseline/` | Earlier IMF-panel models |
| `results/legacy/` | Earlier 2019–2026 and archived-release investment specifications |
| `results/long_history/` | Retrospective 2011–2026 investment and calibration checks |
| `checks/` | Independent checks of prices, timing, portfolio paths and estimates |

`data/SOURCES.csv` lists the source URLs and hashes of the raw files.
`data/DICTIONARY.csv` defines the main variables. Raw data retain the terms of
their original providers.

## Models

| Script | Model |
| --- | --- |
| `price_models.py` | PrNd state-dependent OLS with macro controls; local projections |
| `benchmarks.py` | GPR rules, MA200, momentum, sector rotation and expanding forecasts |
| `factor_attribution.py` | CAPM and five-factor-plus-momentum alpha |
| `sensitivity.py` | Fixed and rolling risk thresholds; paired block bootstrap |
| `revision_attribution.py` | Matched archived/revised REMX wealth decomposition |
| `material_screen.py` | Linear return and absolute-return models across materials |
| `nonlinear.py` | Quantile, state-dependent and daily models |
| `candidate_validation.py` | PrNd robustness and quantile bootstrap |
| `baseline.py` | Earlier IMF-panel regressions, projections and forecasts |
| `legacy_backtest.py`, `legacy_vintages.py` | Earlier investment specifications |
| `long_history.py` | Retrospective 2011–2026 specifications |

Scripts can also be run separately as `python models/<script>.py`.

## Sample conventions

The main price regression covers March 2010–January 2026. The chronological
investment exercise starts on 15 March 2018, with initial training labels ending
in 2017 and revised risk history. The archived-risk reconstruction starts on
8 March 2022 and uses each month's saved release. The 2018 exercise is not a
real-time data-vintage reconstruction.

Main portfolios start at USD 10,000. Monthly execution is at the eleventh US
trading-session close in the 2018 exercise and the sixth in the archive exercise.
Costs are 10 basis points one way; the old position earns the return ending at
the decision close. Cash compounds lagged DFF on ACT/360. Factor data end in
September 2026; portfolio data end in October 2026. Earlier specifications have
their own dates and settings, saved with their results.

Monthly material returns are `100 * diff(log(price))`. Daily portfolio returns
and CAGRs are stored as decimals. PrNd is quoted in CNY per tonne. The regression
risk change is a standardised difference of `log(1 + GPR)`. In `price_models.py`,
the high state uses previous-month China risk above the selected calibration's
80th percentile. Model settings are saved as JSON beside the results.
