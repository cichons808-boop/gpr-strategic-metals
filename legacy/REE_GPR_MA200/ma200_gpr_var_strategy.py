#!/usr/bin/env python3
"""REMX MA200 gating + monthly GPR/VAR signals, simulated no-future-month leakage.

Caldara--Iacoviello GPR update for month m is assumed known in m+1 on
--release-day. Signal executes at the first US close strictly AFTER that day.
For REMX return ending day d, MA200 uses the close of d-2, executes at
the NEXT close d-1, and earns return d-1 -> d. No same-bar fill.

VAR(1) on monthly [Delta log(1+GPR), SPY, XME, REMX] with expanding/rolling
past-only window; one-step-ahead forecast for the calendar month containing
release. Forecast is for the whole month, while live trade begins after release:
this is a direction proxy, not a claim of a precisely matched return horizon.
Final-vintage GPR history may contain revisions: use --source vintage for
historical workbook values if those have been downloaded separately.
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from statsmodels.tsa.api import VAR

from gpr_direction_strategy import (
    read_gpr_frame, build_events_final, build_events_vintage,
    fetch_archives, map_trades,
)

NAMES = {
    'buy_hold': 'REMX Buy & Hold',
    'ma200_only': 'REMX > MA200',
    'gpr_unfiltered': 'GPR up: long / else cash',
    'var_unfiltered': 'VAR > 0: long / else cash',
    'ma200_gpr': 'MA200 + GPR up (long/cash)',
    'ma200_var': 'MA200 + VAR > 0 (long/cash)',
    'ma200_both': 'MA200 + GPR up + VAR > 0',
    'ma200_gpr_ls': 'MA200 + GPR up long / down short',
    'ma200_var_ls': 'MA200 + VAR > 0 long / negative short',
}


def load_prices(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if not {'date','adj_close'}.issubset(df.columns):
        raise ValueError(f'{path} needs date, adj_close')
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df['adj_close'] = pd.to_numeric(df['adj_close'], errors='coerce')
    df = (df.dropna(subset=['date','adj_close']).loc[lambda x: x.adj_close > 0]
          .drop_duplicates('date', keep='last').sort_values('date').reset_index(drop=True))
    if len(df) < 240:
        raise ValueError('At least 240 REMX trading days are needed for MA200')
    df['ma200'] = df.adj_close.rolling(200, min_periods=200).mean()
    df['above_ma200_at_close'] = df.adj_close > df.ma200
    # Close-only data: observe MA200 at t, ENTER at t+1 close,
    # earn interval t+1 -> t+2. A single shift would trade the same close
    # where the MA200 regime was measured (not realistically executable).
    df['ma200_eligible_for_return'] = (df['above_ma200_at_close'].shift(2)
                                      .astype('boolean').fillna(False).astype(bool))
    return df


def load_monthly_panel(path: Path) -> pd.DataFrame:
    panel = pd.read_csv(path)
    required = {'month', 'GPR', 'REMX', 'SPY', 'XME'}
    if not required.issubset(panel.columns):
        raise ValueError(f'Monthly panel missing: {required-set(panel.columns)}; rerun ./run.sh')
    panel['month'] = pd.PeriodIndex(panel.month.astype(str).str[:7], freq='M')
    panel = panel.drop_duplicates('month', keep='last').set_index('month').sort_index()
    panel = panel.reindex(pd.period_range(panel.index.min(), panel.index.max(), freq='M'))
    for c in ['GPR','REMX','SPY','XME']:
        panel[c] = pd.to_numeric(panel[c], errors='coerce')
    return panel[['GPR', 'SPY','XME','REMX']].copy()


def trailing_valid_block(df: pd.DataFrame, last_month: pd.Period) -> pd.DataFrame:
    """Only consecutive complete calendar months ending at last_month."""
    if last_month not in df.index:
        return df.iloc[:0].copy()
    portion = df.loc[:last_month].copy()
    valid = portion.notna().all(axis=1).to_numpy()
    if len(valid) == 0 or not valid[-1]:
        return portion.iloc[:0]
    invalid_before_end = np.where(~valid)[0]
    start = (int(invalid_before_end[-1]) + 1) if len(invalid_before_end) else 0
    return portion.iloc[start:]


def event_var_forecasts(events: pd.DataFrame, panel: pd.DataFrame,
                        gpr_final: pd.Series | None,
                        source: str, vintage_dir: Path,
                        train_months: int, rolling_months: int = 0) -> pd.DataFrame:
    """Fit a new VAR using ONLY month <= last published GPR month.

    For source=vintage, both the signal and the VAR training GPR series use that
    event's contemporary archive. No whole-sample z-score transformation.
    """
    cache: dict[str, pd.Series] = {}
    values = []
    for e in events.itertuples(index=False):
        month = pd.Period(e.signal_month, freq='M')
        if source == 'vintage':
            archive = vintage_dir / str(e.source)
            if not archive.is_file():
                values.append((np.nan,0,'missing vintage file')); continue
            if e.source not in cache:
                cache[e.source] = read_gpr_frame(archive)
            gpr = cache[e.source]
        else:
            if gpr_final is None:
                raise ValueError('Final GPR series is required')
            gpr = gpr_final

        # IMPORTANT: return panel is sliced through the last completed month;
        # no t or future returns can ever enter the training fit.
        hist = panel.loc[:month, ['SPY','XME','REMX']].copy()
        gpr_idx = gpr.reindex(hist.index)
        hist.insert(0, 'gpr_change', np.log1p(gpr_idx.where(gpr_idx>=0)).diff())
        block = trailing_valid_block(hist, month)
        if rolling_months > 0:
            block = block.tail(rolling_months)
        if len(block) < train_months:
            values.append((np.nan,len(block),'insufficient training')); continue
        try:
            fit = VAR(block).fit(1, trend='c')
            if fit.k_ar != 1 or not fit.is_stable():
                values.append((np.nan,len(block),'unstable VAR')); continue
            pred = fit.forecast(block.to_numpy()[-1:], steps=1)
            value = float(pred[0,-1])
            values.append((value,len(block),'ok' if np.isfinite(value) else 'nonfinite forecast'))
        except (ValueError, ArithmeticError, np.linalg.LinAlgError) as err:
            values.append((np.nan,len(block),type(err).__name__))
    result = events.copy()
    result['var_forecast_log_pp'] = [v[0] for v in values]
    result['var_train_n'] = [v[1] for v in values]
    result['var_status'] = [v[2] for v in values]
    return result


def assemble_daily(prices: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    # Map ALL real release events; a failed VAR forecast must not turn an OLD
    # GPR signal into a new VAR signal or silently drop a difficult month.
    daily, mapped_events = map_trades(prices, events)
    valid_events = mapped_events.loc[mapped_events['var_forecast_log_pp'].notna()]
    if valid_events.empty:
        raise ValueError('No valid VAR forecasts. Try --min-train 48 and inspect the monthly panel.')
    # All strategies share the same contiguous calendar span, beginning only
    # after first valid past-only VAR forecast could have been executed.
    first_trade_close = valid_events['execution_close_date'].iloc[0]
    daily = daily.loc[daily.date > first_trade_close].copy()
    cols = ['date', 'adj_close', 'ma200', 'ma200_eligible_for_return']
    price_data = prices.set_index('date')[cols[1:]]
    daily = daily.drop(columns=[c for c in cols[1:] if c in daily.columns],errors='ignore')
    daily = daily.join(price_data, on='date', how='left')
    forecast_lookup = mapped_events.drop_duplicates('signal_month',keep='last').set_index('signal_month')['var_forecast_log_pp']
    daily['var_forecast_log_pp'] = daily.signal_month.map(forecast_lookup)
    daily = daily[daily.ma200.notna() & daily['return'].notna()].copy()
    daily = daily.reset_index(drop=True)
    if len(daily)<15:
        raise ValueError('Insufficient overlapping dates for VAR and MA200')
    return daily, mapped_events


def positions(daily: pd.DataFrame) -> dict[str, np.ndarray]:
    gate = daily['ma200_eligible_for_return'].to_numpy(bool)
    gpr_direction = daily.known_signal.to_numpy(int)
    up = gpr_direction > 0
    forecast = daily.var_forecast_log_pp.to_numpy(float)
    valid_var = np.isfinite(forecast)
    var_up = valid_var & (forecast > 0)
    return {
        'buy_hold': np.ones(len(daily), dtype=float),
        'ma200_only': gate.astype(float),
        'gpr_unfiltered': up.astype(float),
        'var_unfiltered': var_up.astype(float),
        'ma200_gpr': (gate & up).astype(float),
        'ma200_var': (gate & var_up).astype(float),
        'ma200_both': (gate & up & var_up).astype(float),
        'ma200_gpr_ls': np.where(gate, np.sign(gpr_direction).astype(float), 0.),
        'ma200_var_ls': np.where(gate & valid_var, np.where(var_up,1.,-1.),0.),
    }


def score(daily: pd.DataFrame, cost_bps: float, borrow_annual: float) -> tuple[pd.DataFrame,pd.DataFrame]:
    ret = daily['return'].to_numpy(float)
    rows, frames = [], []
    if not np.isfinite(ret).all():
        raise ValueError('Nonfinite asset returns')
    for name, weight in positions(daily).items():
        turnover = np.abs(weight-np.r_[0,weight[:-1]])
        costs = turnover*cost_bps/10000 + (weight < 0)*borrow_annual/252
        net = weight*ret-costs
        eq = np.cumprod(1+net)
        if np.any(1+net<=0):
            raise RuntimeError(f'{name}: portfolio wealth became nonpositive; conventional long-short invalid')
        drawdown = np.r_[1.,eq]/np.maximum.accumulate(np.r_[1.,eq])-1
        n = len(net)
        ann = 252/n
        rows.append({
            'strategy':name,'days':n,'from':daily.date.iloc[0].date(),'to':daily.date.iloc[-1].date(),
            'total_pct':100*(eq[-1]-1),'cagr_pct':100*(eq[-1]**ann-1),
            'sharpe':np.sqrt(252)*np.mean(net)/np.std(net,ddof=1) if np.std(net,ddof=1)>0 else np.nan,
            'max_dd_pct':100*drawdown.min(),
            'long_days':int(np.sum(weight==1)),'short_days':int(np.sum(weight==-1)),
            'cash_days':int(np.sum(weight==0)),'turnover_units':float(turnover.sum()),
            'cost_sum_pct':100*float(costs.sum()),
        })
        frame = pd.DataFrame({'date':daily.date, 'strategy':name, 'position':weight,
                              'asset_return':ret, 'net_return':net,
                              'turnover':turnover,'cost':costs,'equity':eq})
        frames.append(frame)
    return pd.DataFrame(rows),pd.concat(frames,ignore_index=True)


def visualize(daily: pd.DataFrame, ledger: pd.DataFrame, out: Path, open_charts: bool) -> None:
    out.mkdir(parents=True,exist_ok=True)
    pivot = ledger.pivot(index='date',columns='strategy',values='equity').sort_index()
    def draw(keys,title,filename):
        fig,ax=plt.subplots(figsize=(13,6.2))
        for k in keys:
            ax.plot(pivot.index,pivot[k],lw=1.75, label=NAMES[k])
        ax.set(title=title,xlabel='Date',ylabel='Net wealth ($1 starting capital)')
        ax.grid(alpha=.25)
        ax.legend(fontsize=9,ncol=2)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5,maxticks=11))
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        fig.tight_layout()
        path=out/filename;fig.savefig(path,dpi=185);plt.close(fig)
        return path
    paths=[
        draw(['buy_hold','ma200_only','gpr_unfiltered','var_unfiltered','ma200_gpr','ma200_var','ma200_both'],
             'REMX | MA200 + monthly GPR / VAR signal | long / cash', '01_long_cash.png'),
        draw(['buy_hold','ma200_gpr','ma200_var','ma200_gpr_ls','ma200_var_ls'],
             'REMX | filtered long / short vs long / cash | net', '02_long_short.png'),
    ]
    # Price + trailing MA200 and position map
    fig,(ax1,ax2,ax3)=plt.subplots(3,1,figsize=(13,9.5),sharex=True,
        gridspec_kw={'height_ratios':[2.4,1.2,1.2]})
    ax1.plot(daily.date,daily.adj_close,lw=1.3,label='REMX adjusted close')
    ax1.plot(daily.date,daily.ma200,lw=1.45,label='MA200 (200 trading sessions)')
    ax1.legend(fontsize=9);ax1.grid(alpha=.2);ax1.set_ylabel('Price (adj.)')
    ax2.step(daily.date,np.where(daily.known_signal>0,1,0),where='post',label='GPR up (published)',lw=1.3)
    ax2.step(daily.date,np.where(daily.var_forecast_log_pp>0,1,0),where='post',
             label='VAR predicts >0 (published)',lw=1.3,alpha=.8)
    ax2.set(yticks=[0,1],ylim=(-.15,1.15),ylabel='Signal');ax2.grid(alpha=.2);ax2.legend(fontsize=9)
    pos = positions(daily)
    ax3.step(daily.date,pos['ma200_gpr'],where='post',label='MA200 + GPR long/cash',lw=1.3)
    ax3.step(daily.date,pos['ma200_var'],where='post',label='MA200 + VAR long/cash',lw=1.3,alpha=.8)
    ax3.set(yticks=[0,1],ylim=(-.15,1.15),ylabel='Held weight',xlabel='Date');ax3.grid(alpha=.2);ax3.legend(fontsize=9)
    fig.suptitle('MA200 known before execution close; GPR only after assumed release',fontsize=12)
    fig.tight_layout();p=out/'03_price_MA200_positions.png';fig.savefig(p,dpi=185);plt.close(fig);paths.append(p)
    # drawdown comparison
    fig,ax=plt.subplots(figsize=(13,5))
    for k in ['buy_hold','ma200_only','ma200_gpr','ma200_var','ma200_gpr_ls','ma200_var_ls']:
        w=np.r_[1.,pivot[k].to_numpy(float)]
        dd=100*(w/np.maximum.accumulate(w)-1)[1:]
        ax.plot(pivot.index,dd,lw=1.4,label=NAMES[k])
    ax.set(title='Drawdowns | selected strategies',ylabel='Drawdown (%)',xlabel='Date')
    ax.grid(alpha=.25);ax.legend(fontsize=8,ncol=2)
    fig.tight_layout();p=out/'04_drawdowns.png';fig.savefig(p,dpi=185);plt.close(fig);paths.append(p)
    print('\nCHARTS:')
    for p in paths:
        print(' ',p.resolve())
        if open_charts and shutil.which('xdg-open'):
            subprocess.Popen(['xdg-open',str(p.resolve())],stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,start_new_session=True)
    if open_charts and not shutil.which('xdg-open'):
        print('[INFO] xdg-open unavailable; charts saved as PNG')


def main():
    root=Path(__file__).resolve().parent
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',choices=['final','vintage'],default='final')
    ap.add_argument('--prices',type=Path,default=root/'output/raw/REMX_adjusted_daily.csv')
    ap.add_argument('--gpr',type=Path,default=root/'output/tables/gpr_monthly.csv')
    ap.add_argument('--panel',type=Path,default=root/'output/tables/panel_monthly.csv')
    ap.add_argument('--vintage-dir',type=Path,default=root/'output/raw/gpr_vintages')
    ap.add_argument('--fetch-vintages',action='store_true')
    ap.add_argument('--vintage-start',default='2018-01')
    ap.add_argument('--vintage-end',default=pd.Timestamp.today().strftime('%Y-%m'))
    ap.add_argument('--release-day',type=int,default=10)
    ap.add_argument('--min-train',type=int,default=72)
    ap.add_argument('--rolling-window',type=int,default=0,
                    help='0 = expanding history, otherwise last N months')
    ap.add_argument('--cost-bps',type=float,default=10.)
    ap.add_argument('--borrow-annual',type=float,default=.03)
    ap.add_argument('--out',type=Path,default=root/'output/ma200_gpr_var')
    ap.add_argument('--no-open',action='store_true')
    args=ap.parse_args()
    if not 1 <= args.release_day <= 25:
        ap.error('--release-day must be 1..25')
    if args.min_train<36 or (args.rolling_window and args.rolling_window<args.min_train):
        ap.error('min-train must >=36, rolling window must be zero or >= min-train')
    if args.cost_bps<0 or args.borrow_annual<0:
        ap.error('nonnegative trading and borrowing costs required')
    if args.source=='final' and args.fetch_vintages:
        ap.error('--fetch-vintages requires --source vintage')
    for f in (args.prices,args.panel):
        if not f.exists():
            ap.error(f'Missing local cache: {f}; run ./run.sh to create it')
    prices=load_prices(args.prices)
    panel=load_monthly_panel(args.panel)
    if args.source=='vintage':
        if args.fetch_vintages:
            fetch_archives(args.vintage_dir,args.vintage_start,args.vintage_end)
        events=build_events_vintage(args.vintage_dir,args.release_day)
        final=None
    else:
        if not args.gpr.exists():
            ap.error(f'Missing local GPR file: {args.gpr}')
        final=read_gpr_frame(args.gpr)
        events=build_events_final(final,args.release_day)
        print('[CAUTION] Final-vintage GPR may include historical revisions; not point-in-time.')
    # Forecasts are generated before mapping trading dates, from past-only monthly data.
    events=event_var_forecasts(events,panel,final,args.source,args.vintage_dir,
                               args.min_train,args.rolling_window)
    print('[VAR]',events.var_status.value_counts().to_dict())
    daily,exec_events=assemble_daily(prices,events)
    # Do not silently drop long gaps: days come from actual REMX observations.
    s,ledger=score(daily,args.cost_bps,args.borrow_annual)
    args.out.mkdir(parents=True,exist_ok=True)
    s.to_csv(args.out/'summary.csv',index=False,float_format='%.8f')
    ledger.to_csv(args.out/'daily_trades.csv',index=False,float_format='%.8f')
    daily.to_csv(args.out/'daily_signals.csv',index=False,float_format='%.8f')
    exec_events.to_csv(args.out/'signal_publications_and_VAR.csv',index=False,float_format='%.8f')
    (args.out/'metadata.json').write_text(json.dumps({
        'GPR_source':args.source,'assumed_release_calendar_day':args.release_day,
        'MA200':'200-day moving average observed two trading closes before return ending date; one-close execution embargo',
        'VAR':'re-fitted VAR(1) of Delta log1p GPR, monthly SPY XME REMX returns; fit through released month',
        'min_VAR_train_months':args.min_train,'VAR_rolling_window':args.rolling_window,
        'execution':'first trading close strictly after ASSUMED release, position earns return from next close',
        'cost_bps_per_1_exposure_change':args.cost_bps,'annual_short_borrow_rate':args.borrow_annual,
        'notes':['No perfect PIT without verified GPR release timestamps',
                 'Final GPR source may be revised',
                 'Historical adjusted closes and constant borrow rates approximate execution',
                 'VAR monthly forecast is used as direction proxy for post-release remaining days',
                 'Different rules evaluated on the same overlapping dates, starting with VAR availability']
    },indent=2),encoding='utf8')
    print(f'\nCOMMON SAMPLE: {daily.date.iloc[0].date()} → {daily.date.iloc[-1].date()}, {len(daily)} trading days')
    print('\nNET RESULTS (same dates, 10bps costs default, 3% annual short fee):')
    print(s[['strategy','days','total_pct','cagr_pct','sharpe','max_dd_pct','long_days','short_days','turnover_units']].round(3).to_string(index=False))
    visualize(daily,ledger,args.out/'figures',not args.no_open)
    print('\nNo same-day signal execution; GPR final-vintage revisions remain an important potential bias.')

if __name__=='__main__':
    main()
