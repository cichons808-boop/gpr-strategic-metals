# Geopolitical Risk and Returns in Rare Earth and Strategic Metal Markets

This replication package accompanies the **current English working paper**, typeset
in genuine XeLaTeX: **20 pages, nine vector figures, eight tables and 32 references**.
The active manuscript is in `paper_revision/`; the finished document is
`output/GPR_Rare_Earths_Research_Article_EN.pdf`.

## What the samples mean

| Exercise | Dates | Information convention |
| --- | --- | --- |
| Main PrNd price regression | March 2010–January 2026; 191 observations | Retrospective monthly quote associations; selected state calibration from 2009–2022 |
| Chronological investment test | 15 March 2018–30 October 2026; 104 decisions | Thresholds from 2009–2017; first forecast estimated using labels ending in 2017; revised November 2026 risk history |
| Archived-risk reconstruction | 8 March 2022–30 October 2026; 56 decisions | Each month's actual archived risk file; threshold frozen from the January 2022 release |
| Historical sensitivity diagnostic | January 2011–October 2026 | Retrospective context only; retained in `paper_latex/results/` |

The 2018 boundary follows publication of the original GPR working paper. It is
**not** a claim that today's full historical country series or methodology was
available in 2018. The old-method workbook is a frozen 2021 snapshot, not a
complete sequence of 2018 releases. The paper distinguishes sequential forecast
estimation, historical data availability, and independent model selection.

Monthly execution uses the eleventh observed US trading session in the 2018
exercise, allowing for the old update convention around the tenth calendar day.
The archive exercise uses the sixth session under the later early-month
convention. Exact server upload timestamps are not audited. The two exercises
also have different calibration histories, so their difference is not a pure
revision effect. A separate matched REMX comparison holds these features fixed.

## Principal results

The selected high-state PrNd slope is 3.004 log-return percentage points per
standard deviation, with nominal p=0.019. Lagged economic controls leave it at
3.001, p=0.023. The state difference has p=0.053 after these controls. The local
projections use 177 common dates, three return and risk lags, and pointwise HAC
intervals. Later cumulative responses are much less precisely measured.

In the revised-data 2018 exercise, the rule avoiding high and rising China risk
earns a 17.54% CAGR for LIT and 19.61% for COPX after ten-basis-point one-way
costs, compared with 7.33% and 13.99% passively. Their US five-factor-plus-momentum
alphas have nominal p-values of approximately 0.103 and 0.126. No positive GPR
alpha survives the 24-candidate Holm correction. The six risk additions have
negative mean-squared-error R-squared relative to the market-and-trend forecast
in this window. Historical profit, incremental forecast accuracy, and alpha
are evaluated as distinct outcomes.

The matched archived REMX low-risk path ends at USD 13,844 versus USD 18,550
with revised classifications. Exactly two decisions change. Their equal-order
average wealth contributions are approximately USD 1,845 and USD 2,861; the
four counterfactual portfolios are retained. This is a mechanical decomposition
of historical wealth, not expected future profit.

These are exploratory historical results. Neither sample is an untouched
strategy-discovery holdout. The full unsuccessful specification families and
threshold alternatives remain available.

## Reproduce the current results

Use Python 3.12 or another compatible recent Python version. Install the packages
in `requirements.txt`, then run from the extracted archive root:

```bash
python review_extension/price_models.py
python review_extension/benchmarks.py
python review_extension/sensitivity.py
python review_extension/revision_attribution.py
python review_extension/make_exhibits.py
python review_extension/verify.py
```

All required inputs and intermediate price panels are supplied. These steps need
no network connection. The verified computation used NumPy 2.3.5, pandas 2.2.3,
SciPy 1.17.0 and statsmodels 0.14.6. Random seeds are fixed. The sensitivity
bootstrap uses 1,999 replications for each comparison and block length.

To repeat the earlier data transformations and specification search first, run:

```bash
python analysis.py
python supplemental.py
python extension/explore.py
python extension/nonlinear.py
python extension/validate_candidates.py
python paper_en/engine.py
python paper_en/vintage_backtest.py
python paper_latex/analysis_15y.py
python paper_latex/make_exhibits.py
```

Then run the six current-result steps above. `extension/validate_candidates.py`
includes the longer original bootstrap and can take several minutes. Download
scripts are retained for source provenance; do not refresh data to reproduce
this frozen version. New downloads may contain revised histories.

## Compile the document

Select **XeLaTeX** in Overleaf and set `paper_revision/main.tex` as the main file,
or upload the contents of the source-only ZIP. With local TeX Live:

```bash
python paper_revision/compile.py
python review_extension/document_audit.py
```

`paper_revision/README_LATEX.md` gives the direct XeLaTeX commands. No BibTeX step
is required. `review_extension/package.py` validates and rebuilds the three final
deliverables after the manuscript has been compiled.

## Files and outputs

- `review_extension/results/price_control_models.csv`: all controlled and matched
  PrNd models; `price_design_*.csv` retains their exact estimation observations.
- `review_extension/results/local_projections.csv`: both horizon-specific and
  common-sample responses; `lp_design_h*.csv` retains all common-sample designs.
- `review_extension/results/benchmark_metrics.csv`: both investment windows,
  all rules and retained cost alternatives.
- `review_extension/results/*_signals.csv`: dated predictors and allocations;
  `*_forecast_audit.csv` records training sizes and latest label endpoints.
- `review_extension/results/*_daily.csv`: returns, wealth, drawdowns, turnover,
  cash, held positions and new targets for all 88 main paths.
- `review_extension/results/benchmark_tests.csv`: paired benchmark comparisons
  with Holm corrections; `paired_bootstrap.csv` contains block intervals.
- `review_extension/results/factor_alphas.csv`: CAPM and six-factor attribution;
  `factor_daily.csv` contains the parsed French factors.
- `review_extension/results/forecast_comparison.csv`: nested forecast accuracy,
  Clark–West tests and six-comparison Holm corrections within each sample.
- `review_extension/results/threshold_sensitivity.csv`: all 216 threshold results.
- `review_extension/results/revision_attribution.csv` and
  `revision_counterfactuals.csv`: the two changed decisions and all four paths.
- `review_extension/results/legacy_method_sensitivity.csv`: the frozen
  old-method comparison, explicitly distinct from real-time 2018 data.
- `review_extension/results/verification.json`: independent checks of raw prices,
  every main portfolio path, information dates, coefficients, HAC errors,
  forecast timing, factor intercepts and revision attribution.
- `review_extension/results/document_verification.json`: final document checks.
- `paper_revision/figures/`, `tables/`, `numbers.tex`: computed document exhibits.
- `extension/results/`: original physical-price searches and robustness checks.
- `paper_en/raw/vintages/`: 57 original Stata files, including calibration.
- `paper_latex/results/`: earlier 2011–2026 context, including the fixed-versus-
  adaptive COPX diagnostic. It is superseded as the main investment test.
- `MANIFEST_EN.json`: SHA-256 hashes of the exact files in this archive.

## Accounting and measurement

Each portfolio starts at USD 10,000, with full ETF or cash exposure, no borrowing
or shorting. Prices are provider-adjusted for distributions and corporate
actions; their full historical adjustment process is not independently audited.
The old holding earns the return ending at an execution close; the new holding
applies afterwards. Entry and final liquidation incur costs. Switching between
two ETFs incurs both sale and purchase turnover. Fund expenses already affect
prices and are not subtracted twice.

Daily MA200 uses the previous trading close's signal, trades at the next close,
and earns subsequent returns. Monthly MA200 and momentum use the completed
previous calendar month. Sector rotation chooses the highest positive
twelve-minus-one-month return among REMX, LIT and COPX, otherwise cash.

Cash compounds the previous calendar day's effective federal funds rate on
ACT/360, including weekends. It is an opportunity-cost proxy. Factor attribution
uses the French source's own risk-free return and matches the opening cost to
the first holding interval. Factor coverage ends in September 2026, while the
portfolio sample ends in October. Alpha is 252 times the daily intercept, not a
CAGR. Prices and returns are in USD; results exclude tax, currency conversion,
large-order impact and retail account-rate differences.

PrNd is a mixed-metal monthly mean quote in CNY per tonne, not a traded total
return. China CLI is a leading indicator. Actual industrial production is a
separate shorter check ending in December 2023 after lagging; missing months
are not imputed. Calendar-aware HAC preserves gaps in that estimation sample.
The macro controls and projections describe conditional associations and do not
identify an externally instrumented causal shock.

## Source provenance

Source snapshots were retrieved on November 17, 2026. Sources include the
Caldara–Iacoviello website and release archive, IMF, SDM Magnetics, GUK Magnetics,
FRED/OECD, the Dallas Fed, Kenneth French's Data Library and Yahoo adjusted
prices. The bibliography provides attribution and links. Additional source
URLs are in `review_extension/raw/source_downloads.json`. The old-method workbook
is at `https://www.matteoiacoviello.com/gpr_files/gpr_web_latest.xlsx`; its
IMPORTANT sheet documents the November 2021 methodology change. The single
retained Wayback query is an incomplete retrieval attempt, not proof that no
other historical archive exists.

Third-party source bytes are retained to document this calculation. Their rights
remain with the original providers; this archive grants no new commercial
redistribution licence for their data.
