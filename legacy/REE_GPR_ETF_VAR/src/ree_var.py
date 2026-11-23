#!/usr/bin/env python3
"""Monthly GPR–ETF vector autoregressions (VAR).

Reads the EXISTING output/tables/panel_monthly.csv created by src/ree_gpr.py.
No network access required. Outcomes: IRFs (generalized & recursive), percentile
residual-bootstrap CIs for generalized IRFs, Granger F tests, Cholesky FEVD,
ADF tests, diagnostics and figures. This is not structural causal identification.

Example:
    .venv/bin/python src/ree_var.py --bootstrap 399
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller

DEFAULT_ETFS = ('REMX', 'SETM', 'ISTM', 'EART', 'REXC')
CONTROLS = ('SPY', 'XME')
GPR = 'gpr_shock_sd'


def contiguous_sample(data: pd.DataFrame, variables: list[str]) -> tuple[pd.DataFrame, int]:
    """Take longest uninterrupted monthly run; never treat holes as adjacent lags."""
    keep = data[['month', *variables]].copy()
    keep['month'] = pd.PeriodIndex(keep['month'].astype(str).str[:7], freq='M')
    keep = keep.drop_duplicates(subset='month', keep='last').sort_values('month')
    keep = keep.dropna(subset=variables)
    if keep.empty:
        return pd.DataFrame(columns=variables), 0
    months = keep['month'].map(lambda v: v.ordinal).to_numpy(dtype=int)
    split_positions = np.r_[0, np.flatnonzero(np.diff(months) != 1) + 1, len(keep)]
    blocks = [(int(a), int(b)) for a, b in zip(split_positions[:-1], split_positions[1:])]
    start, end = max(blocks, key=lambda ab: ab[1] - ab[0])
    chosen = keep.iloc[start:end].set_index('month')[variables].astype(float)
    return chosen, len(keep) - len(chosen)


def fit_var(sample: pd.DataFrame, user_maxlags: int):
    n, k = sample.shape
    # VAR(1) uses k+1 coefficients per equation. Be conservative for short ETFs.
    if n < max(24, 6 * k + 5):
        raise ValueError(f'Only {n} continuous months for {k} variables; minimum {max(24, 6*k+5)}')
    cap = max(1, min(user_maxlags, (n - 15) // (k + 1)))
    if k >= 4 and n < 60:
        cap = 1  # avoid fitting a 4-variable VAR(2-3) on 40 observations
    model = VAR(sample)
    # Compare BIC lag orders with the same effective sample (statsmodels select_order).
    selection = model.select_order(maxlags=cap, trend='c')
    bic_order = int(selection.selected_orders['bic'])
    bic = selection.ics['bic']
    # Report VAR(0) preference instead of pretending BIC selected dynamics.
    if bic_order == 0:
        order = 1
        note = 'BIC chose VAR(0); VAR(1) fitted for lag-dynamics analysis'
    else:
        order = bic_order
        note = 'BIC chose VAR(p)'
    result = model.fit(maxlags=order, trend='c')
    return result, {'lag': order, 'bic_selected_lag': bic_order,
                    'max_candidate_lag': cap, 'lag_note': note,
                    'candidate_bic': {str(i): float(x) for i, x in enumerate(bic)}}


def adf_pvalue(s: pd.Series) -> float:
    try:
        if s.std() < 1e-10 or len(s) < 24:
            return float('nan')
        return float(adfuller(s, regression='c', autolag='AIC')[1])
    except (ValueError, np.linalg.LinAlgError):
        return float('nan')


def girf_gpr_to_etf(res, target: str, horizon: int) -> np.ndarray:
    """Generalized IRF to +1 residual SD of the GPR equation (order invariant)."""
    names = res.names
    shock_idx, target_idx = names.index(GPR), names.index(target)
    sigma = np.asarray(res.sigma_u, dtype=float)
    sd = float(np.sqrt(sigma[shock_idx, shock_idx]))
    ma = np.asarray(res.ma_rep(maxn=horizon), dtype=float)  # h=0..H
    return np.asarray([(a @ sigma[:, shock_idx])[target_idx] / sd for a in ma])


def recursive_irf_gpr_to_etf(res, target: str, horizon: int) -> np.ndarray:
    # GPR is always ordered first in the input sample; this is identification-sensitive.
    return np.asarray(res.irf(horizon).orth_irfs[:, res.names.index(target), 0], dtype=float)


def bootstrap_girf(res, target: str, horizon: int, draws: int, seed: int):
    """Residual-vector bootstrap (resamples joint residuals, preserving covariance)."""
    if draws <= 0:
        return None
    if not res.is_stable():
        return None  # an explosive fitted VAR invalidates this bootstrap
    rng = np.random.default_rng(seed)
    original = np.asarray(res.model.endog, dtype=float)
    residuals = np.asarray(res.resid, dtype=float)
    residuals = residuals - residuals.mean(axis=0, keepdims=True)
    n, k = original.shape
    p = int(res.k_ar)
    A = np.asarray(res.coefs, dtype=float)
    intercept = np.asarray(res.intercept, dtype=float)
    paths = []
    for _ in range(draws):
        simulated = np.empty_like(original)
        simulated[:p] = original[:p]
        sampled = residuals[rng.integers(len(residuals), size=n-p)]
        for t in range(p, n):
            prediction = intercept.copy()
            for lag in range(1, p+1):
                prediction += A[lag-1] @ simulated[t-lag]
            simulated[t] = prediction + sampled[t-p]
        try:
            fitted = VAR(pd.DataFrame(simulated, columns=res.names)).fit(maxlags=p, trend='c')
            if fitted.is_stable():
                paths.append(girf_gpr_to_etf(fitted, target, horizon))
        except (np.linalg.LinAlgError, ValueError, ZeroDivisionError):
            continue
    if len(paths) < max(30, int(draws * .5)):
        return None
    paths = np.asarray(paths)
    return {
        'low': np.percentile(paths, 2.5, axis=0),
        'high': np.percentile(paths, 97.5, axis=0),
        'cum_low': np.percentile(np.cumsum(paths, axis=1), 2.5, axis=0),
        'cum_high': np.percentile(np.cumsum(paths, axis=1), 97.5, axis=0),
        'valid': int(len(paths)),
    }


def build_outputs(res, ticker: str, model_name: str, horizon: int, bootstrap: int, seed: int,
                  lag_details: dict, discarded: int):
    estimate = girf_gpr_to_etf(res, ticker, horizon)
    orth = recursive_irf_gpr_to_etf(res, ticker, horizon)
    interval = bootstrap_girf(res, ticker, horizon, bootstrap, seed)
    # Granger: predictive content of lags, conditional on the other VAR series.
    fwd = res.test_causality(caused=ticker, causing=[GPR], kind='f')
    rev = res.test_causality(caused=GPR, causing=[ticker], kind='f')
    fevd = np.asarray(res.fevd(horizon).decomp, dtype=float)
    gpr_idx = res.names.index(GPR)
    etf_idx = res.names.index(ticker)
    try:
        whiteness_lags = max(res.k_ar + 2, min(12, max(4, int(res.nobs / 4))))
        whiteness_p = float(res.test_whiteness(nlags=whiteness_lags).pvalue)
    except (ValueError, np.linalg.LinAlgError):
        whiteness_p = float('nan')
    diagnostics = {
        'ticker': ticker, 'specification': model_name, 'n_months': int(res.nobs + res.k_ar),
        'n_estimation': int(res.nobs),
        'lags': int(res.k_ar), 'bic_preferred': lag_details['bic_selected_lag'],
        'lag_note': lag_details['lag_note'], 'stable': bool(res.is_stable()),
        'residual_whiteness_p': whiteness_p,
        'granger_gpr_to_etf_p': float(fwd.pvalue), 'granger_etf_to_gpr_p': float(rev.pvalue),
        'gpr_residual_sd': float(np.sqrt(np.asarray(res.sigma_u)[0, 0])),
        'n_discarded_outside_longest_block': int(discarded),
        'bootstrap_valid': int(interval['valid']) if interval else 0,
        'L1_GPR_to_ETF_coef': float(res.params.loc[f'L1.{GPR}', ticker]),
        'L1_GPR_to_ETF_p': float(res.pvalues.loc[f'L1.{GPR}', ticker]),
    }
    rows = []
    for h in range(horizon+1):
        rows.append({
            'ticker': ticker, 'specification': model_name, 'horizon_month': h,
            'girf_monthly_pp': float(estimate[h]),
            'girf_cumulative_log_pp': float(np.cumsum(estimate)[h]),
            'recursive_monthly_pp': float(orth[h]),
            'recursive_cumulative_log_pp': float(np.cumsum(orth)[h]),
            'girf_ci_low': float(interval['low'][h]) if interval else np.nan,
            'girf_ci_high': float(interval['high'][h]) if interval else np.nan,
            'cum_ci_low': float(interval['cum_low'][h]) if interval else np.nan,
            'cum_ci_high': float(interval['cum_high'][h]) if interval else np.nan,
            'fevd_gpr_share': float(fevd[etf_idx, h-1, gpr_idx]) if h >= 1 else np.nan,
        })
    return diagnostics, pd.DataFrame(rows)


def chart(irf: pd.DataFrame, name: str, out: Path):
    t = irf['horizon_month'].to_numpy()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    for ax, pref, ylabel in [(axes[0], '', 'Response of monthly ETF log return (pp)'),
                             (axes[1], 'cum_', 'Cumulative ETF log return response (pp)')]:
        col = 'girf_monthly_pp' if not pref else 'girf_cumulative_log_pp'
        recur = 'recursive_monthly_pp' if not pref else 'recursive_cumulative_log_pp'
        low = 'girf_ci_low' if not pref else 'cum_ci_low'
        high = 'girf_ci_high' if not pref else 'cum_ci_high'
        ax.plot(t, irf[col], marker='o', ms=3, label='Generalized IRF')
        ax.plot(t, irf[recur], ls='--', alpha=.8, label='Recursive IRF (GPR first)')
        if irf[low].notna().all():
            ax.fill_between(t, irf[low].to_numpy(), irf[high].to_numpy(), alpha=.16,
                            label='95% pointwise residual-bootstrap CI')
        ax.axhline(0, lw=.8, color='black')
        ax.set(xlabel='Months after +1 residual-SD GPR innovation', ylabel=ylabel)
        ax.grid(alpha=.2)
    axes[0].legend(fontsize=8)
    fig.suptitle(f'{name}: geopolitical risk shock → ETF returns')
    fig.tight_layout()
    fig.savefig(out, dpi=170)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).resolve().parent.parent
    p.add_argument('--panel', type=Path, default=base / 'output/tables/panel_monthly.csv')
    p.add_argument('--out', type=Path, default=base / 'output/var')
    p.add_argument('--etfs', nargs='+', default=list(DEFAULT_ETFS))
    p.add_argument('--horizon', type=int, default=12)
    p.add_argument('--maxlags', type=int, default=3)
    p.add_argument('--bootstrap', type=int, default=399, help='0 disables CIs')
    p.add_argument('--seed', type=int, default=20261017)
    p.add_argument('--start-month', default=None, help='YYYY-MM (optional; matched-sample checks)')
    p.add_argument('--end-month', default=None, help='YYYY-MM (optional; inclusive)')
    p.add_argument('--no-controls', action='store_true', help='run bivariate models only')
    args = p.parse_args()
    if args.horizon < 1 or args.maxlags < 1 or args.bootstrap < 0:
        p.error('horizon and maxlags must be >=1, bootstrap must be >=0')
    if not args.panel.exists():
        p.error(f'Missing panel: {args.panel}; first run ./run.sh (without --refresh)')
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'figures').mkdir(exist_ok=True)
    panel = pd.read_csv(args.panel)
    if 'month' not in panel or GPR not in panel:
        p.error(f'Expected columns month and {GPR}. Found: {panel.columns.to_list()}')
    for c in panel.columns:
        if c != 'month':
            panel[c] = pd.to_numeric(panel[c], errors='coerce')
    if args.start_month is not None:
        panel = panel.loc[panel['month'].astype(str).str[:7] >= args.start_month].copy()
    if args.end_month is not None:
        panel = panel.loc[panel['month'].astype(str).str[:7] <= args.end_month].copy()
    stats, irfs, tests = [], [], []
    for i, ticker in enumerate(args.etfs):
        if ticker not in panel.columns:
            print(f'[SKIP] {ticker}: absent in panel')
            continue
        models = [('bivariate', [GPR, ticker])]
        if not args.no_controls and set(CONTROLS).issubset(panel.columns):
            models.append(('full_market_VAR', [GPR, *CONTROLS, ticker]))
        for mode, cols in models:
            sample, discarded = contiguous_sample(panel, cols)
            if len(sample) < (40 if mode == 'full_market_VAR' else 24):
                print(f'[SKIP] {ticker} {mode}: only {len(sample)} contiguous months')
                continue
            try:
                result, detail = fit_var(sample, args.maxlags)
                s, curve = build_outputs(result, ticker, mode, args.horizon,
                                         args.bootstrap, args.seed + i, detail, discarded)
                s['sample_first'] = str(sample.index[0]); s['sample_last'] = str(sample.index[-1])
                s['adf_gpr_p'] = adf_pvalue(sample[GPR]); s['adf_etf_p'] = adf_pvalue(sample[ticker])
                stats.append(s)
                irfs.append(curve)
                tests.append({'ticker': ticker, 'specification': mode, 'lags': result.k_ar,
                              'granger_gpr_to_etf_p': s['granger_gpr_to_etf_p'],
                              'granger_etf_to_gpr_p': s['granger_etf_to_gpr_p'],
                              'sample_first': s['sample_first'], 'sample_last': s['sample_last']})
                chart(curve, f'{ticker} {mode}', args.out / 'figures' / f'irf_{ticker}_{mode}.png')
                # Full table of each coefficient, t-stat, p-value and equation.
                coeff_rows = []
                for eq in result.names:
                    for param in result.params.index:
                        coeff_rows.append({'equation': eq, 'regressor': param,
                                           'coefficient': float(result.params.loc[param, eq]),
                                           'p_value': float(result.pvalues.loc[param, eq]),
                                           't_value': float(result.tvalues.loc[param, eq])})
                pd.DataFrame(coeff_rows).to_csv(args.out / f'coefficients_{ticker}_{mode}.csv', index=False)
                print(f'[OK] {ticker:4s} {mode:15s} n={len(sample):3d} p={result.k_ar} '
                      f'BIC_pref={detail["bic_selected_lag"]} '
                      f'GPR->ETF Granger p={s["granger_gpr_to_etf_p"]:.4f} '
                      f'IRF(t+1)={curve.loc[1,"girf_monthly_pp"]:+.3f} pp; '
                      f'CI draws={s["bootstrap_valid"]}')
                if not result.is_stable():
                    print(f'[WARN] {ticker} {mode}: VAR unstable; bootstrap intervals disabled.')
            except (ValueError, np.linalg.LinAlgError) as exc:
                print(f'[SKIP] {ticker} {mode}: {exc}')
    if not stats:
        raise SystemExit('No estimable VAR; inspect panel and sample sizes.')
    stats_df = pd.DataFrame(stats)
    irf_df = pd.concat(irfs, ignore_index=True)
    granger_df = pd.DataFrame(tests)
    # FDR families are separated by specification (bivariate vs four-variable).
    granger_df['granger_gpr_to_etf_q_bh'] = np.nan
    for _, group in granger_df.groupby('specification'):
        q = multipletests(group['granger_gpr_to_etf_p'].to_numpy(), method='fdr_bh')[1]
        granger_df.loc[group.index, 'granger_gpr_to_etf_q_bh'] = q
    stats_df = stats_df.merge(granger_df[['ticker','specification','granger_gpr_to_etf_q_bh']],
                              on=['ticker', 'specification'], how='left')
    stats_df.to_csv(args.out / 'var_diagnostics.csv', index=False)
    irf_df.to_csv(args.out / 'irf_all.csv', index=False)
    granger_df.to_csv(args.out / 'granger_tests.csv', index=False)
    try:
        granger_df.to_latex(args.out / 'granger_tests.tex', index=False,
                            float_format='%.3f')
    except ImportError:
        print('[WARN] Jinja2 missing for LaTeX; CSV output is complete')
    (args.out / 'methodology_notes.txt').write_text(
        'VAR variables: GPR monthly log(1+GPR) change divided by full-sample SD; '
        'ETF and market benchmark monthly adjusted-price log returns in percentage points.\n'
        'Lag selected by BIC. If BIC selects VAR(0), estimates use VAR(1) and report this explicitly.\n'
        'GIRF: +1 residual standard deviation of GPR equation (not 1 unit of original GPR).\n'
        'GIRF uses Sigma_u and MA representation; Cholesky IRF & FEVD assume GPR first.\n'
        'Pointwise 95% bootstrap intervals are conditional on fixed selected lag and sample.\n'
        'FEVD h means fraction of h-step forecast error variance attributed to the GPR shock.\n'
        'Granger causality denotes predictive value of lagged regressors, not structural causality.\n'
        'Cumulative IRFs sum percentage-point log returns, approximately cumulative percent changes.\n'
        'Full market VAR includes [GPR, SPY, XME, ETF] as endogenous variables.\n'
        'Short post-launch series are excluded; missing calendar months never bridged.\n',
        encoding='utf-8')
    (args.out / 'run_parameters.json').write_text(json.dumps({
        'panel': str(args.panel), 'horizon': args.horizon, 'bootstrap_requested': args.bootstrap,
        'maxlags': args.maxlags, 'seed': args.seed, 'etfs': args.etfs,
        'start_month': args.start_month, 'end_month': args.end_month}, indent=2), encoding='utf-8')
    print('\nGRANGER TESTS (including BH-FDR q-values across funds per model):')
    print(granger_df.to_string(index=False, float_format=lambda x: f'{x:.4f}'))
    print(f'\nSaved all diagnostics, IRFs and figures to: {args.out}')
    print('WARNING: Generalized/recursive innovations and Granger prediction are not causal effects.')


if __name__ == '__main__':
    main()
