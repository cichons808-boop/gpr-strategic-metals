#!/usr/bin/env python3
"""REMX / rare-earth ETF returns versus Caldara--Iacoviello GPR (monthly).

Run: python src/ree_gpr.py --refresh
Data: official GPR .xls; Yahoo Finance adjusted market prices via yfinance.
The analysis is descriptive, NOT causal identification.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import polars as pl
import requests
import statsmodels.api as sm
import yfinance as yf
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

GPR_XLS = 'https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls'
GPR_DTA = 'https://www.matteoiacoviello.com/gpr_files/data_gpr_export.dta'
ETFS = ['REMX', 'ISTM', 'SETM', 'EART', 'REXC']
BENCHMARKS = ['SPY', 'XME']
# Fund renaming: DMAT -> EART + material index change as of 2026-03-01.
# Limit EART return observations to post-change rather than splicing incompatible mandates.
STARTS = {'EART': '2026-04', 'REXC': '2026-05'}  # First FULL month after inception of REXC
MIN_N = 24


def get_session():
    s = requests.Session()
    retry = Retry(total=3, connect=3, read=3, backoff_factor=0.7,
                  status_forcelist=[429, 500, 502, 503, 504])
    s.mount('https://', HTTPAdapter(max_retries=retry))
    s.headers.update({'User-Agent': 'Mozilla/5.0 REE-GPR-Research/1.0'})
    return s


def fetch_gpr(base: Path, refresh: bool) -> Path:
    raw = base / 'raw'
    raw.mkdir(exist_ok=True, parents=True)
    cache_xls = raw / 'data_gpr_export.xls'
    cache_dta = raw / 'data_gpr_export.dta'
    if not refresh:
        for p in [cache_xls, cache_dta]:
            if p.exists() and p.stat().st_size > 500:
                print(f'[GPR] cache: {p}')
                return p
    failures = []
    for url, target in [(GPR_XLS, cache_xls), (GPR_DTA, cache_dta)]:
        try:
            response = get_session().get(url, timeout=45)
            response.raise_for_status()
            if len(response.content) < 500 or b'<html' in response.content[:200].lower():
                raise ValueError('invalid GPR payload')
            target.write_bytes(response.content)
            print(f'[GPR] downloaded: {url} ({len(response.content):,} bytes)')
            return target
        except Exception as exc:
            failures.append(f'{url}: {exc}')
    if not refresh:
        for p in [cache_xls, cache_dta]:
            if p.exists() and p.stat().st_size > 500:
                print(f'[GPR] using old cache after download failures: {p}')
                return p
    raise RuntimeError('Cannot download official GPR (check connection, try again).\n' + '\n'.join(failures))


def month_str(v) -> str | None:
    if pd.isna(v):
        return None
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        return v.strftime('%Y-%m')
    text = str(v).strip()
    match = re.match(r'^(\d{4})\s*[mM/\-.]\s*(\d{1,2})(?:\D.*)?$', text)
    if match:
        y, m = int(match.group(1)), int(match.group(2))
        if 1900 <= y <= 2100 and 1 <= m <= 12:
            return f'{y:04d}-{m:02d}'
    if re.fullmatch(r'\d{5}(?:\.0)?', text):  # Excel date serial
        return (pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(float(text)))).strftime('%Y-%m')
    try:
        return pd.to_datetime(text, errors='raise').strftime('%Y-%m')
    except (ValueError, TypeError, OverflowError):
        return None


def normalize_gpr(raw: pd.DataFrame) -> pl.DataFrame:
    # The live official file usually has `month`, `GPR`, `GPRT`, `GPRA`.
    raw = raw.copy()
    raw.columns = [str(c).strip() for c in raw.columns]
    if not {'month', 'GPR'}.issubset(set(raw.columns)):
        # Tolerate a preamble/header row in a subsequent release.
        for row_i in range(min(12, len(raw))):
            names = [str(v).strip() for v in raw.iloc[row_i].tolist()]
            if 'month' in names and 'GPR' in names:
                raw = raw.iloc[row_i+1:].copy()
                raw.columns = names
                break
    if not {'month', 'GPR'}.issubset(set(raw.columns)):
        raise ValueError(f'GPR schema changed; available fields={list(raw.columns)[:35]}')
    for c in ['GPR', 'GPRT', 'GPRA']:
        if c not in raw.columns:
            raw[c] = np.nan
    raw = raw[['month', 'GPR', 'GPRT', 'GPRA']].copy()
    raw['month'] = raw['month'].map(month_str)
    for c in ['GPR', 'GPRT', 'GPRA']:
        raw[c] = pd.to_numeric(raw[c], errors='coerce')
    raw = raw.dropna(subset=['month', 'GPR'])
    raw = raw.loc[raw['GPR'] >= 0]
    raw = raw.drop_duplicates(subset=['month'], keep='last').sort_values('month')
    return pl.DataFrame({
        'month': raw['month'].tolist(),
        'GPR': raw['GPR'].astype(float).tolist(),
        'GPRT': raw['GPRT'].astype(float).tolist(),
        'GPRA': raw['GPRA'].astype(float).tolist(),
    })


def load_gpr(path: Path, start: str) -> pl.DataFrame:
    if path.suffix == '.dta':
        pdf = pd.read_stata(path, convert_categoricals=False)
    else:
        pdf = pd.read_excel(path, engine='xlrd')
    df = normalize_gpr(pdf).filter(pl.col('month') >= start[:7]).sort('month')
    # Δ log(1 + GPR) is an observed GPR change, not an identified structural shock.
    df = df.with_columns(pl.col('GPR').log1p().diff().alias('dgpr_log'))
    shocks = df.get_column('dgpr_log').drop_nulls().to_numpy()
    if len(shocks) < 12 or np.std(shocks, ddof=1) < 1e-12:
        raise ValueError('Insufficient variation in GPR')
    sd = float(np.std(shocks, ddof=1))
    df = df.with_columns((pl.col('dgpr_log') / sd).alias('gpr_shock_sd'))
    return df


def yf_download(ticker: str, path: Path, start: str, end: str, refresh: bool) -> pd.DataFrame:
    if path.exists() and not refresh:
        print(f'[PRICE] {ticker}: cache')
        return pd.read_csv(path)
    try:
        df = yf.download(ticker, start=start, end=end, auto_adjust=True,
                         actions=False, progress=False, threads=False)
        if df is None or df.empty:
            raise RuntimeError('empty history from Yahoo')
        if isinstance(df.columns, pd.MultiIndex):
            close_matches = [c for c in df.columns if 'Close' in c]
            if len(close_matches) != 1:
                raise RuntimeError(f'cannot find adjusted Close: {list(df.columns)}')
            closes = df[close_matches[0]]
        else:
            closes = df['Close']
        px = pd.DataFrame({'date': pd.to_datetime(df.index).date.astype(str),
                           'adj_close': pd.to_numeric(closes, errors='coerce').to_numpy()})
        px = px.dropna(subset=['adj_close'])
        if px.empty:
            raise RuntimeError('no valid closing prices')
        px.to_csv(path, index=False)
        print(f'[PRICE] {ticker}: downloaded {len(px)} daily observations')
        return px
    except Exception as exc:
        if path.exists():
            print(f'[WARN] {ticker} download failed: {exc}; using cache', file=sys.stderr)
            return pd.read_csv(path)
        raise RuntimeError(f'{ticker}: {exc}') from exc


def prices_monthly(raw: pd.DataFrame, ticker: str) -> pl.DataFrame:
    if not {'date', 'adj_close'}.issubset(raw.columns):
        raise ValueError(f'{ticker} price cache needs date, adj_close')
    d = pl.DataFrame({
        'date': pd.to_datetime(raw['date']).dt.strftime('%Y-%m-%d').to_list(),
        'adj_close': pd.to_numeric(raw['adj_close'], errors='coerce').to_list(),
    }).with_columns(pl.col('date').str.slice(0, 7).alias('month'))
    d = (d.drop_nulls(subset=['adj_close']).filter(pl.col('adj_close') > 0)
         .sort('date').group_by('month').agg(pl.col('adj_close').last().alias('price'))
         .sort('month'))
    # Avoid mistaking a 2-month gap for a monthly return.
    d = d.with_columns([
        (pl.col('price').log().diff() * 100).alias('ret_pct'),
        pl.concat_str([pl.col('month'), pl.lit('-01')]).str.to_date('%Y-%m-%d').dt.offset_by('-1mo').dt.strftime('%Y-%m').alias('prev_month'),
        pl.col('month').shift(1).alias('actual_prev_month'),
    ])
    d = (d.with_columns(pl.when(pl.col('prev_month') == pl.col('actual_prev_month'))
                        .then(pl.col('ret_pct')).otherwise(None).alias('ret_pct'))
         .drop(['prev_month', 'actual_prev_month']))
    if ticker in STARTS:
        d = d.filter(pl.col('month') >= STARTS[ticker])
    return d.with_columns(pl.lit(ticker).alias('ticker')).select('month', 'ticker', 'price', 'ret_pct')


def build_panel(gpr: pl.DataFrame, price_long: pl.DataFrame):
    r = price_long.pivot(index='month', on='ticker', values='ret_pct').sort('month')
    p = price_long.pivot(index='month', on='ticker', values='price').sort('month')
    panel = (gpr.join(r, on='month', how='inner').sort('month'))
    return panel, p


def fit_ols(y, X, maxlags=3):
    d = pd.concat([pd.Series(y, name='outcome'), pd.DataFrame(X)], axis=1).dropna()
    if len(d) < MIN_N:
        return None
    Xmat = sm.add_constant(d.drop(columns='outcome'), has_constant='add')
    res = sm.OLS(d['outcome'], Xmat).fit(cov_type='HAC', cov_kwds={'maxlags': maxlags})
    v = 'gpr_shock_sd'
    return {'n': int(res.nobs), 'beta_pp': float(res.params[v]),
            'se_hac_pp': float(res.bse[v]), 'p_value': float(res.pvalues[v]),
            'ci_low': float(res.conf_int().loc[v, 0]),
            'ci_high': float(res.conf_int().loc[v, 1]),
            'r2': float(res.rsquared)}


def run_regressions(panel: pl.DataFrame, targets: list[str]) -> pd.DataFrame:
    p = pd.DataFrame(panel.to_dict(as_series=False)).set_index('month').sort_index()
    if not {'SPY', 'XME'}.issubset(p.columns):
        raise ValueError('SPY and XME missing; necessary controls')
    rows = []
    for target in targets:
        if target not in p.columns:
            continue
        # Contemporaneous association, explanatory NOT trading signal.
        same = fit_ols(p[target], p[['gpr_shock_sd', 'SPY', 'XME']])
        if same:
            rows.append({'ticker': target, 'model': 'same_month_controls', **same})
        # Predict t+1 return using information from month t only.
        forward = fit_ols(p[target].shift(-1), p[['gpr_shock_sd', 'SPY', 'XME', target]]
                          .rename(columns={target: 'ETF_return_t'}))
        if forward:
            rows.append({'ticker': target, 'model': 'next_month_predictive', **forward})
    return pd.DataFrame(rows)


def correlation_lags(panel: pl.DataFrame, targets: list[str]) -> pd.DataFrame:
    p = pd.DataFrame(panel.to_dict(as_series=False)).set_index('month').sort_index()
    rows = []
    for target in targets:
        if target not in p.columns:
            continue
        for h in range(-3, 4):
            sample = pd.concat([p['gpr_shock_sd'], p[target].shift(-h)], axis=1).dropna()
            if len(sample) < 12:
                continue
            rows.append({'ticker': target, 'months_after_GPR': h,
                         'n': len(sample), 'correlation': sample.iloc[:,0].corr(sample.iloc[:,1])})
    return pd.DataFrame(rows)


def event_study(panel: pl.DataFrame, targets: list[str]) -> pd.DataFrame:
    p = pd.DataFrame(panel.to_dict(as_series=False)).set_index('month').sort_index()
    p.index = pd.PeriodIndex(p.index, freq='M')
    z = p['gpr_shock_sd'].dropna()
    threshold = z.quantile(.90)
    candidates = [m for m in z.index if z.loc[m] >= threshold]
    # Retain shocks at least four months apart so following 3-month windows do not overlap.
    selected = []
    for m in candidates:
        if not selected or (m.ordinal - selected[-1].ordinal) > 3:
            selected.append(m)
    rows = []
    for ticker in targets:
        if ticker not in p.columns:
            continue
        for m in selected:
            if m not in p.index or pd.isna(p.at[m, ticker]):
                continue
            for h in (0, 1, 3):
                months = [m] if h == 0 else [m + k for k in range(1, h + 1)]
                vals = p[ticker].reindex(months)
                if vals.isna().any():
                    continue
                rows.append({'ticker': ticker, 'event_month': str(m),
                             'horizon_months': h, 'cumulative_log_return_pp': float(vals.sum()),
                             'GPR_z': float(z.loc[m]), 'threshold_z': float(threshold)})
    return pd.DataFrame(rows)


def figures(panel: pl.DataFrame, prices: pl.DataFrame, regressions: pd.DataFrame,
            correlations: pd.DataFrame, events: pd.DataFrame, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    g = pd.DataFrame(panel.to_dict(as_series=False))
    levels = pd.DataFrame(prices.to_dict(as_series=False))
    joined = g[['month', 'GPR']].merge(levels[['month', 'REMX']], on='month', how='inner') if 'REMX' in levels else pd.DataFrame()
    if len(joined) > 6:
        x = pd.to_datetime(joined['month'] + '-01')
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(x, joined['GPR'], label='GPR index (level)', lw=1.4)
        ax.set_ylabel('Caldara–Iacoviello GPR')
        ax2 = ax.twinx()
        ax2.plot(x, 100 * joined['REMX'] / joined['REMX'].iloc[0],
                 label='REMX adjusted price (start=100)', alpha=.8, lw=1.4, linestyle='--')
        ax2.set_ylabel('REMX adjusted price, first matched month = 100')
        ax.set_title('Geopolitical risk versus REMX (levels: descriptive only)')
        fig.tight_layout()
        fig.savefig(out / '01_gpr_remx.png', dpi=180)
        plt.close(fig)
    if not regressions.empty:
        r = regressions.sort_values(['ticker', 'model']).reset_index(drop=True)
        fig, ax = plt.subplots(figsize=(10, max(3.7, len(r) * .5 + 1)))
        y = np.arange(len(r))
        ax.errorbar(r['beta_pp'], y, xerr=[r['beta_pp'] - r['ci_low'],
                    r['ci_high'] - r['beta_pp']], fmt='o', capsize=4)
        ax.axvline(0, lw=.9, c='black')
        ax.set_yticks(y, [f'{a} | {b}' for a,b in zip(r['ticker'], r['model'])])
        ax.set_xlabel('Monthly log return response (percentage points) per 1 SD GPR increase')
        ax.set_title('GPR loading with 95% HAC confidence intervals')
        ax.grid(axis='x', alpha=.25)
        fig.tight_layout()
        fig.savefig(out / '02_regression_betas.png', dpi=180)
        plt.close(fig)
    if not correlations.empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        for ticker in ETFS:
            subset = correlations[correlations['ticker'].eq(ticker)]
            if not subset.empty:
                ax.plot(subset['months_after_GPR'], subset['correlation'], marker='o', label=ticker)
        ax.axhline(0, lw=.7, color='black')
        ax.axvline(0, lw=.7, color='black', linestyle='--')
        ax.set(xlabel='h: correlation between GPR change at t and ETF return at t+h',
               ylabel='Pearson correlation', title='Lead/lag correlations (not causal)')
        ax.legend(); ax.grid(alpha=.25)
        fig.tight_layout(); fig.savefig(out / '03_lag_correlations.png', dpi=180)
        plt.close(fig)
    if not events.empty:
        e = events.groupby(['ticker', 'horizon_months'])['cumulative_log_return_pp'].agg(['mean', 'count']).reset_index()
        e.to_csv(out.parent / 'tables' / 'event_averages.csv', index=False)
        fig, ax = plt.subplots(figsize=(10,5))
        for ticker in ETFS:
            subset = e[e['ticker'].eq(ticker)].sort_values('horizon_months')
            if not subset.empty:
                ax.plot(subset['horizon_months'], subset['mean'], marker='o',
                        label=f"{ticker} (events max {subset['count'].max()})")
        ax.axhline(0, lw=.7, c='black')
        ax.set(xticks=[0,1,3], xlabel='0: same month, 1/3: subsequent months',
               ylabel='Mean cumulative log return (percentage points)',
               title='Returns around high GPR-change months (descriptive)')
        ax.grid(alpha=.25); ax.legend()
        fig.tight_layout(); fig.savefig(out / '04_gpr_event_study.png', dpi=180)
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2010-10-01')
    parser.add_argument('--end', default=dt.date.today().isoformat(),
                        help='exclusive end for daily quotes (YYYY-MM-DD)')
    parser.add_argument('--refresh', action='store_true', help='re-download cache')
    parser.add_argument('--offline', action='store_true', help='use existing raw/ cache only')
    parser.add_argument('--out', default=str(Path(__file__).resolve().parent.parent / 'output'))
    args = parser.parse_args()
    base = Path(args.out).expanduser().resolve()
    for name in ['raw', 'tables', 'figures']:
        (base / name).mkdir(parents=True, exist_ok=True)
    if args.offline:
        files = [base/'raw'/'data_gpr_export.xls', base/'raw'/'data_gpr_export.dta']
        existing = [p for p in files if p.exists()]
        if not existing:
            raise SystemExit('Offline mode: missing official GPR file in output/raw/')
        gp = existing[0]
    else:
        gp = fetch_gpr(base, args.refresh)
    gpr = load_gpr(gp, args.start)
    gpr.write_csv(base / 'tables' / 'gpr_monthly.csv')
    price_parts = []
    for ticker in ETFS + BENCHMARKS:
        cache = base / 'raw' / f'{ticker}_adjusted_daily.csv'
        try:
            if args.offline:
                px = pd.read_csv(cache)
            else:
                px = yf_download(ticker, cache, args.start, args.end, args.refresh)
            part = prices_monthly(px, ticker)
            if part.height:
                price_parts.append(part)
        except Exception as exc:
            print(f'[WARN] {ticker}: {exc}', file=sys.stderr)
    if not price_parts:
        raise SystemExit('No market prices. Check Yahoo network connection or cached data.')
    rawprices = pl.concat(price_parts)
    rawprices.write_csv(base / 'tables' / 'etf_prices_returns_long.csv')
    panel, levels = build_panel(gpr, rawprices)
    if panel.is_empty():
        raise SystemExit('No overlapping monthly observations for GPR/ETFs')
    panel.write_csv(base / 'tables' / 'panel_monthly.csv')
    targets = [t for t in ETFS if t in panel.columns]
    regressions = run_regressions(panel, targets)
    correlations = correlation_lags(panel, targets)
    events = event_study(panel, targets)
    regressions.to_csv(base / 'tables' / 'regressions_hac.csv', index=False)
    correlations.to_csv(base / 'tables' / 'correlations_lags.csv', index=False)
    events.to_csv(base / 'tables' / 'event_observations.csv', index=False)
    figures(panel, levels, regressions, correlations, events, base / 'figures')
    if not regressions.empty:
        (base / 'tables' / 'regressions_hac.tex').write_text(
            regressions.to_latex(index=False, float_format=lambda x: f'{x:.3f}'), encoding='utf-8')
    (base / 'metadata.json').write_text(json.dumps({
        'gpr_source': GPR_XLS, 'prices_source': 'Yahoo Finance via yfinance',
        'price_field': 'auto-adjusted Close',
        'estimated_on': dt.datetime.now(dt.timezone.utc).isoformat(),
        'start': args.start, 'end_exclusive': args.end,
        'gpr_first': gpr['month'][0], 'gpr_last': gpr['month'][-1],
        'panel_first': panel['month'][0], 'panel_last': panel['month'][-1],
        'target_funds': targets,
        'note': 'GPR not an identified exogenous shock. EART returns from April 2026, excluding the March transition month.'
    }, indent=2), encoding='utf-8')
    print('\nRESULTS (percentage-point sensitivity per one SD increase in monthly log GPR):')
    if regressions.empty:
        print('No regressions: too few complete monthly observations (minimum 24).')
    else:
        print(regressions[['ticker','model','n','beta_pp','p_value','ci_low','ci_high']].to_string(index=False))
    print(f'\nOutput: {base}')
    print('IMPORTANT: statistical association/predictability, not established causation.')


if __name__ == '__main__':
    main()
