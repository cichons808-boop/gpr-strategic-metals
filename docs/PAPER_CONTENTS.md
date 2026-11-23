# Materials used in the paper

The complete saved research materials were added on 23 November 2026. The import
contains all 951 original files from the 21 retained sources. Exact original
bytes, including unsuccessful specifications and earlier versions, are preserved;
`IMPORT_MANIFEST.csv` records every source member, destination, size and SHA-256.

The current English article is
[`paper/GPR_Rare_Earths_Research_Article_EN.pdf`](../paper/GPR_Rare_Earths_Research_Article_EN.pdf).
Its original complete replication package is expanded in [`replication/`](../replication/).
The Polish article and the other saved English PDF are also in `paper/`.

## Inputs and calculations

| Paper material | Retained input | Code and output |
| --- | --- | --- |
| Monthly and daily global, China, threat and act GPR measures | `data/raw/gpr/gpr.xls`, `gpr_daily.xls` | `models/prepare_data.py`, `data/processed/materials/gpr.csv` |
| Historical GPR releases and old methodology | All 57 files in `data/raw/gpr/vintages/`, `GPR_OLD_2021_snapshot.xlsx` | `models/market.py`, `models/benchmarks.py`, `models/revision_attribution.py` |
| PrNd quotes and publisher snapshots | `data/raw/quotes/prnd_long.csv`, `sdm_official_alt.html` | `data/processed/materials/prices.csv`, `returns.csv` |
| Neodymium and samarium quotes | `data/raw/quotes/guk_prices.csv`, `guk.html` | `models/material_screen.py`, `results/materials/` |
| Eight IMF material prices, oil and gold controls | `data/raw/imf/imf.xlsx` | `models/baseline.py`, `results/baseline/` |
| REMX, LIT, COPX, SPY and EEM adjusted daily prices | `data/raw/market/daily/` | `data/processed/market/daily_adjusted_prices.csv`, `models/market.py` |
| Earlier monthly ETF and company comparisons | `data/raw/market/monthly/` | `models/legacy_market.py`, `results/legacy/` |
| China leading indicator and actual industrial production | `data/raw/macro/CHNLOLITOAASTSAM.csv`, `CHNPRINTO01IXPYM.csv` | `models/price_models.py`, `results/main/price_design_*.csv` |
| Global activity, broad dollar and cash interest | `data/raw/macro/IGREA.csv`, `TWEXBGSMTH.csv`, `DFF.csv` | `models/price_models.py`, `models/market.py` |
| US five equity factors and momentum | `data/raw/factors/FF5_daily.zip`, `MOM_daily.zip` | `models/factor_attribution.py`, `results/main/factor_daily.csv`, `factor_alphas.csv` |
| Controlled regressions and local projections | Exact estimation designs in `results/main/price_design_*.csv`, `lp_design_h*.csv` | `models/price_models.py`, `price_control_models.csv`, `local_projections.csv` |
| Sequential forecasts, 88 portfolio paths and information timing | `results/main/*_signals.csv`, `*_forecast_audit.csv`, `*_daily.csv` | `models/benchmarks.py`, `benchmark_metrics.csv`, `forecast_comparison.csv` |
| Threshold choices, block bootstrap and revision decomposition | `results/main/threshold_sensitivity.csv`, `paired_bootstrap.csv`, `revision_*.csv` | `models/sensitivity.py`, `models/revision_attribution.py` |
| Earlier model search and unsuccessful specifications | `results/baseline/`, `results/materials/`, `results/legacy/`, `results/long_history/` | Corresponding scripts in `models/`; original code in `replication/` and `legacy/` |

`data/SOURCES.csv` gives provider URLs, retrieval dates and hashes for all 84
retained raw files. `data/DICTIONARY.csv` defines the variables. Dates and data
versions are the ones actually retained for the paper, with coverage differing
by source.

## Manuscript, tables and figures

| Item | Location |
| --- | --- |
| Current English manuscript, all included sections and bibliography | `paper/latex/main.tex`, `preamble.tex`, `numbers.tex`, the five section files, `references.tex` |
| All nine vector figures | `paper/latex/figures/` |
| Generated table inputs (other tables are inline in the sections) | `paper/latex/tables/` |
| Original manuscript and additional source bibliography | `replication/paper_revision/` |
| Exhibit generation code | `replication/review_extension/make_exhibits.py`, `replication/paper_latex/make_exhibits.py` |
| Original replication instructions and file hashes | `replication/README_EN.md`, `replication/MANIFEST_EN.json` |
| Original computation and document audit reports | `checks/verification.json`, `replication/review_extension/results/document_verification.json` |
| New import integrity and independent-result validation | `checks/github_import_validation.json` |

## Reproduce

From the repository root:

```bash
python -m pip install -r requirements.txt
python run.py --check
python run.py
```

`python run.py --all` also reruns the longer earlier search. The calculation
commands use supplied local data. To regenerate the original paper's exhibits,
follow `replication/README_EN.md`; to compile the document, follow
`paper/latex/README_LATEX.md` (XeLaTeX). The original archived copies remain
available alongside the organised project.
