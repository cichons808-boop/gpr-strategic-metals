#!/usr/bin/env python3
"""SPY vs Caldara--Iacoviello GPR: point-in-time-aware daily excess-return test.

Dependencies: existing gpr_direction_strategy.py from REE_GPR_ETF.
No signals are traded before the close AFTER an assumed publication date.
Default vintage/month-end means the file is labeled as having been issued in a
calendar month, and trading begins after that month is finished. Filename is
NOT proof of precise publication timestamp; audit before claiming strict PIT.
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import statsmodels.api as sm

from gpr_direction_strategy import (
    read_gpr_frame, build_events_final, build_events_vintage, fetch_archives, map_trades
)

RULES = {
    'spy_buy_hold': 'SPY: buy & hold',
    'gpr_up_long_cash': 'GPR↑: long / ↓ cash',
    'gpr_up_long_short': 'GPR↑: long / ↓ short',
    'gpr_down_long_cash': 'GPR↓: long / ↑ cash (control)',
    'ma200': 'SPY > MA200',
    'ma200_gpr_up': 'MA200 & GPR↑: long / else cash',
    'ma200_gpr_ls': 'MA200 & GPR↑: long / GPR↓: short / below MA cash',
}


def load_spy(path: Path) -> pd.DataFrame:
    p = pd.read_csv(path)
    if not {'date', 'adj_close'}.issubset(p.columns):
        raise ValueError(f'{path} must have date, adj_close columns (cached ./run.sh data)')
    p['date'] = pd.to_datetime(p.date, errors='coerce')
    p['adj_close'] = pd.to_numeric(p.adj_close, errors='coerce')
    p = (p.dropna(subset=['date', 'adj_close']).loc[lambda d:d.adj_close > 0]
           .sort_values('date').drop_duplicates('date', keep='last').reset_index(drop=True))
    if len(p) < 240:
        raise ValueError('Need >240 trading days of SPY daily adjusted closes')
    p['ma200'] = p.adj_close.rolling(200, min_periods=200).mean()
    p['above_ma200_close'] = (p.adj_close > p.ma200)
    # Close of session T is learned after closing; execution at T+1 close;
    # first return earned is T+1 close -> T+2 close. (shift 2)
    p['ma200_tradeable_for_return'] = p.above_ma200_close.shift(2).fillna(False).astype(bool)
    return p


def event_calendar(events: pd.DataFrame, timing: str, day: int) -> pd.DataFrame:
    q = events.copy()
    if timing == 'month_end':
        # End of *vintage month*, NOT the month being measured: deliberately conservative.
        q['assumed_release_date'] = [pd.Period(s, freq='M').end_time.normalize()
                                     for s in q.vintage_month]
    elif timing != 'day':
        raise ValueError(f'Invalid timing: {timing}')
    return q.sort_values('assumed_release_date').reset_index(drop=True)


def load_tbill(path: Path, prices: pd.DataFrame, fetch: bool) -> pd.Series:
    """Past-only 3m U.S. T-bill cash proxy using DTB3 quoted discount yield, approximate."""
    if not path.is_file():
        if not fetch:
            raise FileNotFoundError(
                f'T-Bill history missing: {path}. Supply --fetch-tbill or --cash-mode zero.')
        import requests
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3'
        resp = requests.get(url, timeout=80, headers={'User-Agent':'academic-gpr-spy-backtest/1.0'})
        resp.raise_for_status()
        if len(resp.content) < 1000:
            raise RuntimeError('FRED CSV unexpectedly short')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        print('[FRED] downloaded DTB3 historical T-bill yields:', path)
    df = pd.read_csv(path)
    if 'DTB3' not in df:
        raise ValueError(f'{path}: missing DTB3 column')
    dt_col = 'DATE' if 'DATE' in df else ('observation_date' if 'observation_date' in df else None)
    if dt_col is None: raise ValueError(f'{path}: missing DATE/observation_date')
    df['date'] = pd.to_datetime(df[dt_col], errors='coerce')
    df['rate'] = pd.to_numeric(df.DTB3, errors='coerce')
    series = (df.dropna(subset=['date']).drop_duplicates('date', keep='last')
              .set_index('date').sort_index()['rate'])
    # Include nontrading days through ffill, then shift by one SPY session;
    # daily PnL on date T can only use previous-close published rate.
    date_index = pd.DatetimeIndex(prices.date)
    on_days = series.reindex(series.index.union(date_index)).sort_index().ffill().reindex(date_index)
    prior = on_days.shift(1)
    if prior.isna().any():
        raise RuntimeError('T-bill data do not cover the complete price period. Supply a fuller FRED CSV.')
    # Discount yield -> simple annual cash-rate approximation, using 252 sessions.
    return pd.Series(np.expm1(np.log1p(prior.to_numpy() / 100) / 252), index=date_index)


def build_weights(df: pd.DataFrame) -> dict[str, np.ndarray]:
    g = df.known_signal.to_numpy(int)
    trend = df.ma200_tradeable_for_return.to_numpy(bool)
    up, down = g > 0, g < 0
    return {
        'spy_buy_hold': np.ones(len(df)),
        'gpr_up_long_cash': up.astype(float),
        'gpr_up_long_short': np.where(up, 1., -1.),
        'gpr_down_long_cash': down.astype(float),
        'ma200': trend.astype(float),
        'ma200_gpr_up': (trend & up).astype(float),
        'ma200_gpr_ls': np.where(trend, np.where(up, 1., -1.), 0.),
    }


def simulate(df: pd.DataFrame, cost_bps: float, borrow_annual: float) -> pd.DataFrame:
    r = df['return'].to_numpy(float)
    cash = df['cash_return'].to_numpy(float)
    frames = []
    for name, w in build_weights(df).items():
        turnover = np.abs(w - np.r_[0., w[:-1]])
        fee = cost_bps / 10000. * turnover
        # Conservative assumption: short proceeds earn no interest; financing
        # fees separately deducted. Cash earns an approximate 3m T-bill rate.
        carry = np.where(w == 0, cash, 0.)
        borrow = np.maximum(-w, 0.) * borrow_annual / 252
        net = w * r + carry - fee - borrow
        if not np.isfinite(net).all() or (1 + net <= 0).any():
            raise ValueError(f'{name} has invalid/ruinous returns: cannot compound')
        frames.append(pd.DataFrame({
            'date': df.date.to_numpy(), 'strategy': name,
            'spy_return': r, 'cash_return': cash,
            'position': w, 'net_return': net,
            'cost': fee + borrow, 'turnover': turnover,
            'equity': np.cumprod(1 + net)
        }))
    return pd.concat(frames, ignore_index=True)


def hac_average(x: np.ndarray, lag: int = 21) -> tuple[float, float, float]:
    x = np.asarray(x, float)
    if len(x) < 30 or np.std(x) < 1e-14:
        return float(np.mean(x)), float('nan'), float('nan')
    res = sm.OLS(x, np.ones((len(x), 1))).fit(
        cov_type='HAC', cov_kwds={'maxlags': min(lag, len(x)-1)})
    return float(res.params[0]), float(res.tvalues[0]), float(res.pvalues[0])


def summarize(ledger: pd.DataFrame) -> pd.DataFrame:
    pivot = ledger.pivot(index='date', columns='strategy', values='net_return').sort_index()
    spy = pivot['spy_buy_hold'].to_numpy(float)
    rf = ledger[ledger.strategy == 'spy_buy_hold'].sort_values('date').cash_return.to_numpy(float)
    bh_equity = np.cumprod(1 + spy)
    spy_cagr = bh_equity[-1]**(252/len(spy)) - 1
    rows=[]
    for name in RULES:
        q = ledger[ledger.strategy == name].sort_values('date')
        p = q.net_return.to_numpy(float)
        eq = np.r_[1., np.cumprod(1 + p)]
        peak = np.maximum.accumulate(eq)
        ann = 252.0 / len(p)
        mean_excess, excess_t, excess_p = hac_average(p-spy)
        # CAPM alpha is a risk-adjusted diagnostic, not a guarantee of edge.
        x = sm.add_constant(spy - rf)
        reg = sm.OLS(p-rf, x).fit(cov_type='HAC', cov_kwds={'maxlags':21})
        rows.append({
            'strategy':name, 'sessions':len(p),
            'first':str(q.date.iloc[0].date()), 'last':str(q.date.iloc[-1].date()),
            'total_return_pct':100*(eq[-1]-1),
            'cagr_pct':100*(eq[-1]**ann-1),
            'excess_cagr_vs_SPY_pp':100*(eq[-1]**ann-1 - spy_cagr),
            'sharpe_cash_excess':float(np.sqrt(252)*(p-rf).mean()/p.std(ddof=1)) if p.std(ddof=1) > 0 else np.nan,
            'max_dd_pct':100*float(np.min(eq/peak - 1)),
            'long_days':int((q.position == 1).sum()), 'short_days':int((q.position == -1).sum()),
            'turnover_units':float(q.turnover.sum()),
            'mean_daily_excess_ann_pp':100*252*mean_excess,
            'excess_hac_t':excess_t, 'excess_hac_p':excess_p,
            'capm_alpha_ann_pp':100*252*float(reg.params[0]),
            'capm_alpha_hac_p':float(reg.pvalues[0]),
            'capm_beta':float(reg.params[1]),
        })
    return pd.DataFrame(rows)


def period_results(ledger: pd.DataFrame, boundaries: list[int]) -> pd.DataFrame:
    out=[]
    for start in boundaries:
        df=ledger[ledger.date >= pd.Timestamp(f'{start}-01-01')]
        if df.date.nunique() < 63: continue
        summ=summarize(df)
        summ['from_year']=start
        out.append(summ[['from_year','strategy','sessions','cagr_pct',
                         'excess_cagr_vs_SPY_pp','max_dd_pct','capm_alpha_ann_pp']])
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def charts(df: pd.DataFrame, ledger: pd.DataFrame, folder: Path, auto_open: bool) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    eq=ledger.pivot(index='date', columns='strategy', values='equity').sort_index()
    r=ledger.pivot(index='date', columns='strategy', values='net_return').sort_index()
    files=[]
    def plot_equity(keys,title,name):
        fig,ax=plt.subplots(figsize=(13,6))
        for k in keys: ax.plot(eq.index,eq[k],label=RULES[k],lw=1.6)
        ax.set(title=title, ylabel='Equity (start = 1)',xlabel='Date')
        ax.grid(alpha=.27); ax.legend(fontsize=9)
        fig.tight_layout();path=folder/name;fig.savefig(path,dpi=180);plt.close(fig);files.append(path)

    plot_equity(['spy_buy_hold','gpr_up_long_cash','ma200','ma200_gpr_up'],
                'SPY | Buy & hold vs GPR sign and MA200 | NET', '01_long_cash.png')
    plot_equity(['spy_buy_hold','gpr_up_long_short','ma200_gpr_ls'],
                'SPY | Buy & hold vs GPR long/short | NET', '02_long_short.png')
    fig,ax=plt.subplots(figsize=(13,5.5))
    for k in ['gpr_up_long_cash','gpr_up_long_short','ma200','ma200_gpr_up','ma200_gpr_ls']:
        ax.plot(eq.index,eq[k]/eq['spy_buy_hold']-1,label=RULES[k],lw=1.5)
    ax.axhline(0,color='black',lw=.8)
    ax.set(title='Relative wealth versus buying and holding SPY', ylabel='Wealth / B&H wealth - 1',xlabel='Date')
    ax.grid(alpha=.27);ax.legend(fontsize=8,ncol=2)
    fig.tight_layout();path=folder/'03_relative_wealth.png';fig.savefig(path,dpi=180);plt.close(fig);files.append(path)

    fig, ax=plt.subplots(figsize=(13,5.4))
    baseline=r['spy_buy_hold']
    for k in ['gpr_up_long_cash','gpr_up_long_short','ma200_gpr_up']:
        rel=(1+r[k]).rolling(252).apply(np.prod,raw=True)-(1+baseline).rolling(252).apply(np.prod,raw=True)
        ax.plot(r.index,100*rel,label=RULES[k],lw=1.4)
    ax.axhline(0,color='black',lw=.8)
    ax.set(title='Trailing 252-session excess total return vs SPY', ylabel='Excess percentage points', xlabel='Date')
    ax.grid(alpha=.27);ax.legend(fontsize=9)
    fig.tight_layout();path=folder/'04_rolling_excess.png';fig.savefig(path,dpi=180);plt.close(fig);files.append(path)

    fig,(ax,ax2)=plt.subplots(2,1,figsize=(13,7.4),sharex=True,gridspec_kw={'height_ratios':[3,1]})
    ax.plot(df.date,df.adj_close,label='SPY adjusted close',lw=1.4)
    ax.plot(df.date,df.ma200,label='MA200',lw=1.2)
    ax.set(ylabel='Adjusted price',title='SPY, MA200 and published GPR signal');ax.grid(alpha=.25);ax.legend()
    ax2.step(df.date,df.known_signal.where(df.known_signal != 0,0),where='post',lw=1.1)
    ax2.set(ylabel='GPR sign',yticks=[-1,0,1],ylim=(-1.4,1.4),xlabel='Date');ax2.grid(alpha=.25)
    fig.tight_layout();path=folder/'05_signals.png';fig.savefig(path,dpi=180);plt.close(fig);files.append(path)
    print('\nCHARTS (automatically opening):')
    for f in files:
        print(' ',f)
        if auto_open and shutil.which('xdg-open'):
            subprocess.Popen(['xdg-open',str(f)],stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,start_new_session=True)


def main():
    project=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',choices=['vintage','final'],default='vintage')
    p.add_argument('--fetch-vintages',action='store_true')
    p.add_argument('--vintage-start',default='2010-01')
    p.add_argument('--vintage-end',default='2026-10')
    p.add_argument('--vintage-dir',type=Path,default=project/'output/raw/gpr_vintages')
    p.add_argument('--timing',choices=['month_end','day'],default='month_end',
                   help='month_end: trade only after vintage month ends; day: assumed release day (sensitivity only)')
    p.add_argument('--release-day',type=int,default=10)
    p.add_argument('--cost-bps',type=float,default=10.)
    p.add_argument('--borrow-annual',type=float,default=.03)
    p.add_argument('--cash-mode',choices=['tbill','zero'],default='tbill')
    p.add_argument('--tbill',type=Path,default=project/'output/raw/DTB3.csv')
    p.add_argument('--fetch-tbill',action='store_true')
    p.add_argument('--prices',type=Path,default=project/'output/raw/SPY_adjusted_daily.csv')
    p.add_argument('--gpr',type=Path,default=project/'output/tables/gpr_monthly.csv')
    p.add_argument('--out',type=Path,default=project/'output/spy_gpr_excess')
    p.add_argument('--no-open',action='store_true')
    a=p.parse_args()
    if not 1 <= a.release_day <= 25 or a.cost_bps < 0 or a.borrow_annual < 0:
        p.error('release-day must be 1..25; costs and borrow must be nonnegative')
    if not a.prices.exists(): p.error(f'Cannot find SPY cache: {a.prices}; run ./run.sh first.')
    prices=load_spy(a.prices)
    if a.source=='vintage':
        if a.fetch_vintages:
            fetch_archives(a.vintage_dir,a.vintage_start,a.vintage_end)
        events=build_events_vintage(a.vintage_dir,a.release_day)
    else:
        if a.fetch_vintages: p.error('--fetch-vintages only for --source vintage')
        if not a.gpr.exists(): p.error(f'GPR final file not found: {a.gpr}')
        events=build_events_final(read_gpr_frame(a.gpr),a.release_day)
    events=event_calendar(events,a.timing,a.release_day)
    if a.source=='final':
        print('WARNING: latest GPR values are REVISED. Results are NOT true point-in-time.')
    if a.timing=='day':
        print(f'WARNING: historical publication day {a.release_day} is an ASSUMPTION; not proven PIT.')
    else:
        print('ASSUMPTION: vintage YYYYMM was available by that month end; first trade after month end.')
    daily,executed=map_trades(prices,events)
    daily=daily.dropna(subset=['return','ma200']).copy()
    if daily.empty: raise SystemExit('No matching SPY and GPR data with 200-session history')
    if a.cash_mode=='tbill':
        yields=load_tbill(a.tbill,prices,a.fetch_tbill)
        daily['cash_return']=yields.reindex(pd.DatetimeIndex(daily.date)).to_numpy()
    else:
        daily['cash_return']=0.
        print('WARNING: cash return set to zero; for historical excess, prefer --cash-mode tbill --fetch-tbill')
    if daily.cash_return.isna().any():
        raise ValueError('Missing cash returns; check Treasury CSV coverage')
    ledger=simulate(daily,a.cost_bps,a.borrow_annual)
    tab=summarize(ledger)
    subs=period_results(ledger,[2016,2020,2022,2024])
    a.out.mkdir(parents=True,exist_ok=True)
    tab.to_csv(a.out/'summary.csv',index=False,float_format='%.8f')
    ledger.to_csv(a.out/'daily_ledger.csv',index=False,float_format='%.8f')
    executed.to_csv(a.out/'executed_gpr_releases.csv',index=False)
    subs.to_csv(a.out/'subperiods.csv',index=False,float_format='%.8f')
    (a.out/'metadata.json').write_text(json.dumps({
        'gpr_source':a.source,'timing':a.timing,'release_day_if_used':a.release_day,
        'cash_mode':a.cash_mode,'cost_bps_one_way':a.cost_bps,'short_borrow_annual':a.borrow_annual,
        'price_file':str(a.prices),'vintages_directory':str(a.vintage_dir),
        'disclaimer':'A vintage month is not a verified precise publication time; execution after month end is a conservative convention. Adjusted-close fills are approximations. Models are exploratory.'
    },indent=2),encoding='utf-8')
    print(f'\nSAMPLE: {daily.date.iloc[0].date()} to {daily.date.iloc[-1].date()} | {len(daily)} SPY sessions')
    show=['strategy','cagr_pct','excess_cagr_vs_SPY_pp','sharpe_cash_excess','max_dd_pct','mean_daily_excess_ann_pp','excess_hac_p','capm_alpha_ann_pp','capm_alpha_hac_p','capm_beta']
    print('\nNET RESULTS | Excess = DIFFERENCE IN CAGR VS SPY buy-and-hold (same dates)')
    print(tab[show].round(3).to_string(index=False))
    print('\nSUBPERIODS:');print(subs.round(3).to_string(index=False) if len(subs) else '(none)')
    charts(daily,ledger,a.out/'figures',not a.no_open)
    print('\nCRITICAL: GPR month-vintage files are required for revision-safe backtest.')
    print('No intramonth trade before the first close following assumed public availability;')
    print('cash yield and execution assumptions are proxies; statistical tests are exploratory.')
    print('Results in:',a.out.resolve())

if __name__=='__main__':
    main()
