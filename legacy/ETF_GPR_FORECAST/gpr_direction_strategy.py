#!/usr/bin/env python3
"""Caldara-Iacoviello GPR sign -> REMX, with time-safe market execution.

LONG/CASH: hold +1 when last *published* monthly GPR rose vs previous month,
           otherwise 0. Long/short: +1 vs -1. Daily close-to-close REMX returns.

Strict historical point-in-time MODE: --source vintage --fetch-vintages
(reconstruct GPR from original month-specific release files, where available).
Preview MODE: --source final uses the user's current cached GPR series; historical
revisions mean this preview is NOT a rigorous point-in-time backtest.

A monthly vintage named YYYYMM is assumed published on calendar day N of YYYYMM.
Because filename does not identify an exact timestamp, --release-day is an
explicit timing assumption. Trades execute at the CLOSE of the first trading
session AFTER that presumed release day and affect subsequent returns only.
"""
from __future__ import annotations

import argparse
import calendar
import re
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def parse_month(x):
    if pd.isna(x):
        return None
    if isinstance(x, (pd.Timestamp,)):
        return x.to_period('M')
    text = str(x).strip()
    m = re.match(r'^(\d{4})\s*[mM./-]\s*(\d{1,2})(?:\D.*)?$', text)
    if m:
        y, mm = int(m.group(1)), int(m.group(2))
        if 1900 <= y <= 2100 and 1 <= mm <= 12:
            return pd.Period(year=y, month=mm, freq='M')
    if re.fullmatch(r'\d{5}(?:\.0)?', text):
        return (pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(float(text)))).to_period('M')
    try:
        return pd.Timestamp(text).to_period('M')
    except (ValueError, TypeError, OverflowError):
        return None


def read_gpr_frame(path: Path) -> pd.Series:
    if path.suffix.lower() == '.dta':
        df = pd.read_stata(path, convert_categoricals=False)
    elif path.suffix.lower() == '.xls':
        df = pd.read_excel(path, engine='xlrd')
    elif path.suffix.lower() == '.csv':
        df = pd.read_csv(path)
    else:
        raise ValueError(f'Unsupported GPR file: {path}')
    df.columns = [str(x).strip() for x in df.columns]
    if 'month' not in df or 'GPR' not in df:
        for k in range(min(15, len(df))):
            header = [str(x).strip() for x in df.iloc[k]]
            if 'month' in header and 'GPR' in header:
                df = df.iloc[k+1:].copy()
                df.columns = header
                break
    if 'month' not in df or 'GPR' not in df:
        raise ValueError(f'No month/GPR in {path}: {df.columns[:10].tolist()}')
    out = pd.DataFrame({'month':df['month'].map(parse_month),
                        'gpr':pd.to_numeric(df['GPR'], errors='coerce')})
    out = out.dropna(subset=['month', 'gpr'])
    out = out[out.gpr >= 0].drop_duplicates(subset='month', keep='last')
    if out.empty:
        raise ValueError(f'No usable GPR in {path}')
    return out.set_index('month')['gpr'].sort_index()


def release_timestamp(vintage: pd.Period, release_day: int) -> pd.Timestamp:
    year, month = vintage.year, vintage.month
    day = min(release_day, calendar.monthrange(year, month)[1])
    return pd.Timestamp(year=year, month=month, day=day)


def build_events_final(gpr: pd.Series, release_day: int) -> pd.DataFrame:
    # Month m index can be first known during month m+1, NOT at month m close.
    # Explicit month reindex prevents differencing across missing months.
    idx = pd.period_range(gpr.index.min(), gpr.index.max(), freq='M')
    s = gpr.reindex(idx)
    delta = s.diff()
    rows = []
    for m, change in delta.dropna().items():
        vintage = m + 1
        rows.append(dict(signal_month=str(m), vintage_month=str(vintage),
                         assumed_release_date=release_timestamp(vintage, release_day),
                         gpr_current=float(s.loc[m]), gpr_previous=float(s.loc[m-1]),
                         d_gpr=float(change),
                         signal=1 if change > 0 else (-1 if change < 0 else 0),
                         source='final_current_vintage'))
    return pd.DataFrame(rows)


def discover_archives(directory: Path) -> dict[pd.Period, Path]:
    seen = {}
    for p in sorted(directory.glob('data_gpr_export_*.dta')) + sorted(directory.glob('data_gpr_export_*.xls')):
        m = re.search(r'data_gpr_export_(\d{4})(\d{2})\.(?:dta|xls)$', p.name)
        if not m: continue
        month = pd.Period(f'{m.group(1)}-{m.group(2)}', freq='M')
        seen.setdefault(month, p)
    return dict(sorted(seen.items()))


def fetch_archives(directory: Path, start: str, end: str):
    """Fetch actual archived GPR release files (can be hundreds of MB)."""
    try:
        import requests
    except ImportError as e:
        raise SystemExit('Missing requests dependency: .venv/bin/python -m pip install requests') from e
    directory.mkdir(parents=True, exist_ok=True)
    api = 'https://api.github.com/repos/iacoviel/iacoviel.github.io/git/trees/master?recursive=1'
    r = requests.get(api, timeout=45, headers={'Accept':'application/vnd.github+json'})
    r.raise_for_status()
    if r.json().get('truncated'):
        raise RuntimeError('GitHub tree listing truncated; cannot reliably retrieve vintages')
    files = {}
    for entry in r.json().get('tree', []):
        path = entry.get('path', '')
        m = re.fullmatch(r'gpr_archive_files/data_gpr_export_(\d{6})\.(dta|xls)', path)
        if not m: continue
        month = pd.Period(f'{m.group(1)[:4]}-{m.group(1)[4:]}', freq='M')
        if pd.Period(start[:7], freq='M') <= month <= pd.Period(end[:7], freq='M'):
            # Prefer smaller Stata files when both are provided.
            if month not in files or m.group(2) == 'dta':
                files[month] = path
    if not files:
        raise RuntimeError('No monthly vintages found in official archive. Check GitHub access.')
    print(f'[VINTAGES] Available in chosen range: {len(files)}; downloading missing files only')
    for i, (month, path) in enumerate(sorted(files.items()), 1):
        target = directory / Path(path).name
        if target.is_file() and target.stat().st_size > 1000:
            continue
        url = 'https://raw.githubusercontent.com/iacoviel/iacoviel.github.io/master/' + path
        resp = requests.get(url, timeout=90)
        resp.raise_for_status()
        if len(resp.content) < 1000:
            raise RuntimeError('Unexpectedly small vintage: ' + url)
        temp = target.with_suffix(target.suffix+'.tmp')
        temp.write_bytes(resp.content)
        temp.replace(target)
        if i % 10 == 0:
            print(f'  downloaded through {month} ({i}/{len(files)})')
    print('[VINTAGES] Cached under:', directory)


def build_events_vintage(directory: Path, release_day: int) -> pd.DataFrame:
    files = discover_archives(directory)
    if not files:
        raise SystemExit(f'No archived GPR vintages in {directory}; use --fetch-vintages')
    rows = []
    bad = []
    for vintage, path in files.items():
        try:
            values = read_gpr_frame(path)
            m = vintage-1
            if m not in values or m-1 not in values:
                continue
            g, prev = float(values.loc[m]), float(values.loc[m-1])
            change = g-prev
            rows.append(dict(signal_month=str(m), vintage_month=str(vintage),
                             assumed_release_date=release_timestamp(vintage, release_day),
                             gpr_current=g, gpr_previous=prev, d_gpr=change,
                             signal=1 if change > 0 else (-1 if change < 0 else 0),
                             source=path.name))
        except (ValueError, KeyError, OSError) as err:
            bad.append(f'{path.name}: {err}')
    if bad:
        print('[WARN] unreadable vintages:', *bad[:5], sep='\n  ', file=sys.stderr)
    if not rows:
        raise SystemExit('No valid release vintages with GPR for prior two complete months')
    return pd.DataFrame(rows).sort_values('assumed_release_date')


def map_trades(prices: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    events = events.copy().sort_values('assumed_release_date')
    dts = prices['date'].to_numpy(dtype='datetime64[ns]')
    # The price must exist on trading day after the presumed release date.
    ix = np.searchsorted(dts, events['assumed_release_date'].to_numpy(dtype='datetime64[ns]'), side='right')
    events['exec_index'] = ix
    events = events[events.exec_index < len(prices)].copy()
    events['execution_close_date'] = prices['date'].to_numpy()[events.exec_index.to_numpy(int)]
    events = events.drop_duplicates('execution_close_date', keep='last')
    if events.empty:
        raise SystemExit('No GPR releases occurred while REMX traded')
    # For daily return ending on date i, position must be known at the preceding close (i-1).
    daily = prices.copy()
    daily['return'] = daily['adj_close'].pct_change(fill_method=None)
    dates = daily['date'].to_numpy(dtype='datetime64[ns]')
    event_ix = np.searchsorted(events['execution_close_date'].to_numpy(dtype='datetime64[ns]'), dates, side='left')-1
    # event_ix for return dated d points to last execution close STRICTLY BEFORE d.
    sig = events['signal'].to_numpy(int)
    daily['known_signal'] = np.where(event_ix >= 0, sig[np.maximum(event_ix, 0)], np.nan)
    daily['signal_month'] = np.where(event_ix >= 0,
        events['signal_month'].to_numpy()[np.maximum(event_ix, 0)], '')
    daily = daily.loc[daily['known_signal'].notna()].copy()
    daily['known_signal'] = daily['known_signal'].astype(int)
    if len(daily) < 3:
        raise SystemExit('Not enough subsequent REMX sessions to test the rule')
    return daily, events


def evaluate_strategy(daily: pd.DataFrame, name: str, cost_bps: float, borrow: float):
    r = daily['return'].to_numpy(float)
    direction = daily['known_signal'].to_numpy(int)
    if name == 'buy_hold':
        weight = np.ones(len(r))
    elif name == 'long_cash':
        weight = (direction > 0).astype(float)
    elif name == 'long_short':
        weight = np.where(direction > 0, 1., -1.)
    elif name == 'reverse_long_cash':
        weight = (direction < 0).astype(float)
    else:
        raise ValueError(name)
    # Initial position assumed zero, transaction cost proportional to |delta exposure|.
    turnover = np.abs(weight - np.r_[0., weight[:-1]])
    trade_fees = turnover*cost_bps/10000.
    borrow_fees = np.where(weight < 0, borrow/252., 0.)
    net = weight*r-trade_fees-borrow_fees
    eq = np.cumprod(1+net)
    if (1+net <= 0).any():
        eq[(np.cumprod(1+net) <= 0)] = np.nan
    return pd.DataFrame(dict(date=daily.date.to_numpy(), strategy=name,
        position=weight, asset_return=r, turnover=turnover,
        fees=trade_fees+borrow_fees, net_return=net, equity=eq))


def summarize(sub: pd.DataFrame):
    r = sub.net_return.to_numpy(float)
    eq = sub.equity.to_numpy(float)
    n = len(sub)
    wealth = np.r_[1., eq]
    dd = wealth/np.maximum.accumulate(wealth)-1
    ann_factor = 252/n
    total = float(eq[-1]-1) if np.isfinite(eq[-1]) else float('nan')
    return dict(strategy=sub.strategy.iloc[0], sessions=n,
        total_pct=round(total*100,2),
        cagr_pct=round((eq[-1]**ann_factor-1)*100,2) if np.isfinite(eq[-1]) and eq[-1]>0 else float('nan'),
        sharpe=round(float(np.sqrt(252)*np.mean(r)/np.std(r,ddof=1)),3) if np.std(r,ddof=1)>0 else float('nan'),
        max_dd_pct=round(float(100*dd.min()),2),
        turnover=round(float(sub.turnover.sum()),2),
        gross_trading_days_long=int((sub.position > 0).sum()),
        gross_trading_days_short=int((sub.position < 0).sum()),
        fees_pct_initial_capital_units=round(float(100*sub.fees.sum()),2))


def charts(ledger: pd.DataFrame, daily: pd.DataFrame, events: pd.DataFrame, directory: Path,
           source: str, opening: bool):
    directory.mkdir(parents=True, exist_ok=True)
    series = ledger.pivot(index='date', columns='strategy', values='equity').sort_index()
    paths = []
    labels = dict(buy_hold='REMX buy & hold', long_cash='GPR ↑ long / ↓ cash',
                  long_short='GPR ↑ long / ↓ short', reverse_long_cash='GPR ↓ long / ↑ cash')
    fig,ax = plt.subplots(figsize=(14, 6.8))
    for k in ['buy_hold','long_cash','long_short','reverse_long_cash']:
        if k in series:
            ax.plot(series.index, series[k], lw=1.75, label=labels[k])
    ax.set(title=f'REMX | GPR sign strategy | {source}', ylabel='Capital (start = 1 USD)', xlabel='Date')
    ax.legend(); ax.grid(alpha=.25)
    fig.tight_layout()
    p1=directory/'gpr_strategy_equity.png'; fig.savefig(p1,dpi=180);plt.close(fig);paths.append(p1)

    fig,(ax,ax2)=plt.subplots(2,1,figsize=(14,8),sharex=True,gridspec_kw={'height_ratios':[2.5,1]})
    for k in ['buy_hold','long_cash','long_short']:
        ax.plot(series.index,series[k],lw=1.7,label=labels[k])
    ax.set_ylabel('Equity (USD)');ax.grid(alpha=.25);ax.legend()
    ax2.step(daily.date, np.where(daily.known_signal>0,1,0),where='post',label='Long/Cash position (+1/0)',lw=1.5)
    ax2.step(daily.date,np.where(daily.known_signal>0,1,-1),where='post',label='Long/Short position (+1/-1)',lw=1.1,alpha=.8)
    ax2.set(ylim=(-1.4,1.4),yticks=[-1,0,1], ylabel='Position',xlabel='Trade interval date')
    ax2.grid(alpha=.23);ax2.legend(loc='best')
    fig.suptitle('Caldara-Iacoviello GPR signal | orders after presumed publication')
    fig.tight_layout();p2=directory/'gpr_strategy_equity_positions.png';fig.savefig(p2,dpi=180);plt.close(fig);paths.append(p2)

    fig,ax=plt.subplots(figsize=(14,5))
    selected=ledger.loc[ledger.strategy.isin(['long_cash','long_short'])]
    monthly=(selected.assign(month=selected.date.dt.to_period('M'))
             .groupby(['month','strategy'])['net_return']
             .apply(lambda x: 100*(np.prod(1+x.to_numpy())-1)).unstack('strategy'))
    monthly.index=monthly.index.to_timestamp('M')
    for k in ['long_cash','long_short']:
        if k in monthly:
            ax.plot(monthly.index,monthly[k],lw=1.4,label=labels[k])
    ax.axhline(0,color='black',lw=.8);ax.grid(alpha=.25)
    ax.set(title='Monthly NET strategy returns',ylabel='Return (%)',xlabel='Month');ax.legend()
    fig.tight_layout();p3=directory/'gpr_strategy_monthly_returns.png';fig.savefig(p3,dpi=180);plt.close(fig);paths.append(p3)
    print('CHARTS:')
    for p in paths:
        print(' ',p)
        if opening and shutil.which('xdg-open'):
            subprocess.Popen(['xdg-open',str(p)],stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,start_new_session=True)


def main():
    project=Path(__file__).resolve().parent
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--source',choices=['final','vintage'],default='final',
                   help='final=quick preview with revised values; vintage=real historical values')
    a.add_argument('--release-day',type=int,default=10,
                   help='assumed calendar day in publication month, default 10 (sensitivity: 5, 15)')
    a.add_argument('--cost-bps',type=float,default=10.,help='fee per one unit absolute position change')
    a.add_argument('--borrow-annual',type=float,default=.03)
    a.add_argument('--prices',type=Path,default=project/'output/raw/REMX_adjusted_daily.csv')
    a.add_argument('--gpr',type=Path,default=project/'output/tables/gpr_monthly.csv')
    a.add_argument('--vintage-dir',type=Path,default=project/'output/raw/gpr_vintages')
    a.add_argument('--fetch-vintages',action='store_true')
    a.add_argument('--start',default='2010-10',help='earliest vintage month to fetch')
    a.add_argument('--end',default=pd.Timestamp.today().strftime('%Y-%m'),help='latest vintage to fetch')
    a.add_argument('--out',type=Path,default=project/'output/gpr_sign_strategy')
    a.add_argument('--no-open',action='store_true')
    args=a.parse_args()
    if not 1 <= args.release_day <= 25:
        a.error('--release-day must be between 1 and 25')
    if args.cost_bps < 0 or args.borrow_annual < 0:
        a.error('Costs and borrow fees must not be negative')
    if not args.prices.is_file():
        a.error(f'No cached daily prices: {args.prices}. First run ./run.sh --offline')
    prices=pd.read_csv(args.prices)
    if not {'date','adj_close'}.issubset(prices.columns):
        a.error('Price cache must contain date and adj_close')
    prices['date']=pd.to_datetime(prices.date)
    prices['adj_close']=pd.to_numeric(prices.adj_close,errors='coerce')
    prices=(prices.dropna(subset=['date','adj_close'])
            .loc[lambda x:x.adj_close>0]
            .drop_duplicates('date',keep='last').sort_values('date').reset_index(drop=True))
    if len(prices)<10: a.error('Not enough valid daily prices')
    if args.source=='vintage':
        if args.fetch_vintages:
            fetch_archives(args.vintage_dir,args.start,args.end)
        events=build_events_vintage(args.vintage_dir,args.release_day)
        print('[SOURCE] ORIGINAL HISTORICAL VINTAGES. Timing still assumes release by calendar day',args.release_day)
    else:
        if args.fetch_vintages: a.error('--fetch-vintages requires --source vintage')
        if not args.gpr.is_file(): a.error(f'No monthly GPR cache: {args.gpr}')
        events=build_events_final(read_gpr_frame(args.gpr),args.release_day)
        print('[WARNING] Final-vintage GPR values: historical revisions may create bias. NOT strictly point-in-time.')
    daily, events=map_trades(prices,events)
    print(f'[SAMPLE] {daily.date.iloc[0].date()} to {daily.date.iloc[-1].date()}; {len(daily)} daily PnL intervals; {len(events)} GPR updates')
    ledgers=[evaluate_strategy(daily,n,args.cost_bps,args.borrow_annual)
             for n in ['buy_hold','long_cash','long_short','reverse_long_cash']]
    ledger=pd.concat(ledgers,ignore_index=True)
    summary=pd.DataFrame([summarize(df) for _,df in ledger.groupby('strategy',sort=False)])
    args.out.mkdir(parents=True,exist_ok=True)
    ledger.to_csv(args.out/'daily_trades.csv',index=False)
    summary.to_csv(args.out/'summary.csv',index=False)
    events.to_csv(args.out/'published_signals.csv',index=False)
    print('\nNET PERFORMANCE (adjusted close proxies; borrow/fees estimated):')
    print(summary.to_string(index=False))
    charts(ledger,daily,events,args.out/'figures',args.source,not args.no_open)
    print('\nAssumption: execution at next available US market close strictly AFTER assumed GPR release day;')
    print('position first earns return on next trading session; never on signal/release day.')
    print('Publication dates here are approximations, not verified historical timestamps.')
    print('Chart output:',args.out.resolve())

if __name__=='__main__':
    main()
