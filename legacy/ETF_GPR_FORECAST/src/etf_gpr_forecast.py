#!/usr/bin/env python3
"""Broad ETF GPR screening; expanding OOS forecasts, vintage-aware timing.

For a forecast at the close of month t of return t+1:
- uses adjusted ETF/SPY prices through t
- uses only GPR data for months <= t-1, available during t
- in vintage mode, each t uses the official release file labelled YYYYMM=t
  rather than today's revised values.

A month-end t signal could be executed on the next trading close; month t+1
close-to-close return is an idealized approximation (see README).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from gpr_direction_strategy import read_gpr_frame, discover_archives, fetch_archives

# Representative predeclared universe, NOT an AUM/liquidity ranking as of today.
GROUPS = {
    'US equities': ['SPY', 'QQQ', 'DIA', 'IWM'],
    'Global equities': ['EEM', 'EFA'],
    'Fixed income': ['TLT', 'IEF', 'LQD', 'HYG'],
    'Gold & energy': ['GLD', 'SLV', 'USO', 'XLE'],
    'Strategic metals': ['REMX', 'XME', 'GDX', 'COPX', 'URA'],
    'US sectors': ['XLK', 'XLF', 'XLI', 'XLU', 'XBI'],
    'Technology & defense': ['SMH', 'ITA'],
}
UNIVERSE = [symbol for tickers in GROUPS.values() for symbol in tickers]
NAMES = {symbol: grp for grp, symbols in GROUPS.items() for symbol in symbols}


def load_prices(cache: Path, tickers: list[str], start: str,
                refresh: bool, offline: bool, end_exclusive: str) -> pd.DataFrame:
    cache.mkdir(parents=True, exist_ok=True)
    paths = {s: cache / f'{s}_adjusted_daily.csv' for s in tickers}
    missing = [s for s in tickers if refresh or not paths[s].is_file()]
    if missing and not offline:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError('yfinance missing: pip install yfinance') from exc
        # Batched calls are considerably faster than separate one-symbol queries.
        for lo in range(0, len(missing), 7):
            chunk = missing[lo:lo+7]
            print('[PRICES] downloading:', ', '.join(chunk), flush=True)
            try:
                frame = yf.download(chunk, start=start, end=end_exclusive,
                                    auto_adjust=True, progress=False, threads=True,
                                    group_by='ticker')
            except Exception as exc:
                print('[WARN] batch download failed:', exc, file=sys.stderr)
                continue
            if frame is None or frame.empty:
                print('[WARN] empty batch:', chunk, file=sys.stderr)
                continue
            for s in chunk:
                try:
                    if isinstance(frame.columns, pd.MultiIndex):
                        if s in frame.columns.get_level_values(0):
                            series = frame[s]['Close']
                        elif s in frame.columns.get_level_values(1):
                            series = frame['Close'][s]
                        else:
                            raise KeyError(f'no symbol {s} in yfinance batch')
                    else:
                        series = frame['Close']
                    z = pd.DataFrame({'date': pd.to_datetime(series.index).strftime('%Y-%m-%d'),
                                      'adj_close': pd.to_numeric(series, errors='coerce').to_numpy()})
                    z = z.dropna(subset=['adj_close'])
                    z = z[z.adj_close > 0]
                    if len(z) < 10:
                        raise ValueError('fewer than 10 observations')
                    z.to_csv(paths[s], index=False)
                    print(f'  {s}: {len(z)} daily closes')
                except Exception as exc:
                    print(f'[WARN] {s}: {exc}', file=sys.stderr)
    elif missing:
        print('[OFFLINE] No new downloads. Missing:', ', '.join(missing))

    monthly = {}
    trade_prices = {}
    # Historical price data may have incomplete or missing calendar months.
    for s in tickers:
        if not paths[s].is_file():
            print(f'[SKIP] {s}: no saved prices', file=sys.stderr)
            continue
        raw = pd.read_csv(paths[s], usecols=['date', 'adj_close'])
        raw['date'] = pd.to_datetime(raw.date, errors='coerce')
        raw['adj_close'] = pd.to_numeric(raw.adj_close, errors='coerce')
        raw = raw.dropna().loc[lambda q: q.adj_close > 0].sort_values('date').drop_duplicates('date')
        if len(raw) < 20:
            continue
        raw['month'] = raw.date.dt.to_period('M')
        series = raw.groupby('month').adj_close.last()
        # Do not include unfinished calendar month: return would be partial.
        latest_complete = pd.Timestamp.now().to_period('M') - 1
        series = series.loc[series.index <= latest_complete]
        monthly[s] = series
        # Feasible fill: at FIRST trading-day close of each month m (after
        # signal fixed at the preceding month-end); exit first close m+1.
        first_close = raw.groupby('month').adj_close.first().sort_index()
        first_close = first_close.loc[first_close.index <= pd.Timestamp.now().to_period('M')]
        idx = pd.period_range(first_close.index.min(), first_close.index.max(),freq='M')
        trade_prices[s] = first_close.reindex(idx)
        print(f'[PRICES] {s} {series.index.min()} → {series.index.max()} ({len(series)} months)')
    if not monthly:
        raise RuntimeError('No ETF prices: check downloads/network and cache location.')
    levels = pd.concat(monthly, axis=1).sort_index().astype(float)
    contiguous = levels.reindex(pd.period_range(levels.index.min(), levels.index.max(), freq='M'))
    returns = 100 * np.log(contiguous / contiguous.shift(1))
    returns.index.name = 'month'
    # Return from first-close m to first-close m+1, realized next month.
    # Evaluated per decision formed at END of month m-1.
    tradable = {}
    for s, prices in trade_prices.items():
        r = prices.shift(-1) / prices - 1.0
        tradable[s] = r
    execution = pd.concat(tradable,axis=1).reindex(returns.index)
    execution.index.name = 'month'
    return returns, execution


def load_gpr_signals(mode: str, raw: Path, vintagedir: Path,
                     fetch: bool, vintage_start: str, last_month: pd.Period) -> pd.DataFrame:
    if mode == 'final':
        gprfiles = [raw / 'data_gpr_export.xls', raw / 'data_gpr_export.dta', raw / 'data_gpr_export.csv']
        file = next((p for p in gprfiles if p.exists()), None)
        if file is None:
            from urllib.request import urlretrieve
            file = gprfiles[0]
            file.parent.mkdir(parents=True, exist_ok=True)
            url = 'https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls'
            print(f'[GPR] fetching {url}')
            try:
                urlretrieve(url, file)
            except Exception as exc:
                raise RuntimeError(f'GPR missing; copy the existing XLS to {file}: {exc}') from exc
        gpr = read_gpr_frame(file)
        idx = pd.period_range(gpr.index.min(), gpr.index.max(), freq='M')
        gpr = gpr.reindex(idx)
        # At month t end, month t-1 released at beginning of t (not month t).
        month_index = pd.period_range(gpr.index.min()+2, last_month, freq='M')
        prior = gpr.reindex(month_index-1).to_numpy(dtype=float)
        older = gpr.reindex(month_index-2).to_numpy(dtype=float)
        return pd.DataFrame({'month': month_index,
                             'gpr_dlog': np.log1p(prior)-np.log1p(older),
                             'gpr_log_level': np.log1p(prior),
                             'gpr_month_used': (month_index-1).astype(str),
                             'source_file': file.name}).set_index('month')

    if fetch:
        fetch_archives(vintagedir, vintage_start, str(last_month))
    files = discover_archives(vintagedir)
    rows = []
    for i, (vintage, path) in enumerate(files.items(), 1):
        if vintage > last_month or vintage < pd.Period(vintage_start, freq='M'):
            continue
        try:
            s = read_gpr_frame(path)
            if vintage-1 not in s or vintage-2 not in s:
                continue
            a, b = float(s[vintage-1]), float(s[vintage-2])
            rows.append({'month':vintage,
                         'gpr_dlog':np.log1p(a)-np.log1p(b),
                         'gpr_log_level':np.log1p(a),
                         'gpr_month_used':str(vintage-1),
                         'source_file':path.name})
        except (OSError, ValueError, KeyError) as exc:
            print(f'[WARN] {path.name}: {exc}', file=sys.stderr)
    if not rows:
        raise RuntimeError('No valid GPR vintages: use --fetch-vintages, or --gpr-mode final.')
    print(f'[GPR] valid release vintages: {len(rows)}')
    return pd.DataFrame(rows).set_index('month').sort_index()


def make_design(returns: pd.DataFrame, gpr: pd.DataFrame, ticker: str) -> pd.DataFrame:
    d = pd.DataFrame(index=returns.index)
    r = returns[ticker].copy()
    d['y_next_log_pp'] = r.shift(-1)
    d['lag_return'] = r
    d['momentum_3'] = r.rolling(3, min_periods=3).sum()
    d['volatility_6'] = r.rolling(6, min_periods=6).std()
    if ticker != 'SPY' and 'SPY' in returns:
        d['spy_last'] = returns['SPY']
    d = d.join(gpr[['gpr_dlog']], how='left')
    d.index.name = 'month'
    return d.replace([np.inf,-np.inf], np.nan).dropna()


def ridge_pred(train: pd.DataFrame, test: pd.DataFrame, predictors: list[str], lam: float) -> float:
    X = train[predictors].to_numpy(float)
    y = train['y_next_log_pp'].to_numpy(float)
    one = test[predictors].to_numpy(float)
    avg, sd = X.mean(axis=0), X.std(axis=0, ddof=0)
    sd = np.where(sd < 1e-9, 1.0, sd)
    xn = (X-avg)/sd
    xt = (one-avg)/sd
    M = np.column_stack([np.ones(len(X)), xn])
    penalty = np.eye(M.shape[1]) * lam
    penalty[0,0] = 0
    coefs = np.linalg.solve(M.T @ M + penalty + 1e-8*np.eye(M.shape[1]), M.T @ y)
    return float(np.r_[1,xt.ravel()] @ coefs)


def expanding_oos(d: pd.DataFrame, ticker: str, train_months: int,
                  lam: float) -> pd.DataFrame:
    # Expanding window with chronological, unbroken monthly observations.
    # Missing GPR vintage months are NOT treated as adjacent periods.
    base = [c for c in d.columns if c not in ('y_next_log_pp','gpr_dlog')]
    full = base + ['gpr_dlog']
    rec = []
    for k in range(train_months, len(d)):
        train = d.iloc[:k]
        test = d.iloc[[k]]
        # No unseen future outcomes in training (y_s is r_{s+1}).
        # At month t close, r_t is known, so training may include s<=t-1.
        # BUT: row t-1 contains y=r_t, known by close t. This is okay.
        current = test.index[0]
        if (current - train.index[-1]).n != 1:
            continue
        if len(train) < train_months or not np.isfinite(train.to_numpy(dtype=float)).all():
            continue
        y = float(test['y_next_log_pp'].iloc[0])
        b = ridge_pred(train, test, base, lam)
        g = ridge_pred(train, test, full, lam)
        rec.append(dict(ticker=ticker, asof_month=str(current),
                        return_month=str(current+1), observed_log_pp=y,
                        forecast_baseline_log_pp=b, forecast_gpr_log_pp=g,
                        gpr_value=float(test.gpr_dlog.iloc[0]),
                        n_train=len(train)))
    return pd.DataFrame(rec)


def bh_qvalues(p: pd.Series) -> pd.Series:
    vals = pd.to_numeric(p, errors='coerce').to_numpy(float)
    ans = np.full(len(vals),np.nan)
    pos = np.where(np.isfinite(vals))[0]
    if len(pos):
        order = pos[np.argsort(vals[pos])]
        m = len(order)
        ranks = np.arange(1,m+1)
        adjusted = np.minimum.accumulate((vals[order]*m/ranks)[::-1])[::-1]
        ans[order] = np.minimum(adjusted,1)
    return pd.Series(ans,index=p.index)


def mean_hac(values: np.ndarray, maxlags: int=3) -> tuple[float,float]:
    a = np.asarray(values,float)
    if len(a) < 12 or np.std(a,ddof=1) < 1e-12:
        return (np.nan,np.nan)
    r = sm.OLS(a,np.ones((len(a),1))).fit(cov_type='HAC',cov_kwds={'maxlags':min(len(a)-1,maxlags)})
    return float(r.tvalues[0]),float(r.pvalues[0])


def pnl_from_forecast(pred: pd.DataFrame, fc_col: str, kind: str,
                      cost_bps:float, borrow_rate:float) -> pd.DataFrame:
    p = pred.sort_values('return_month').copy()
    f = p[fc_col].to_numpy(float)
    y = p.trade_return_simple.to_numpy(float)
    if kind == 'hold':
        w = np.ones(len(p))
    elif kind == 'long_cash':
        w = (f>0).astype(float)
    elif kind == 'long_short':
        w = np.where(f>0, 1.0, -1.0)
    else:
        raise ValueError(kind)
    turnover = np.abs(w-np.r_[0,w[:-1]])
    net = w*y - turnover*cost_bps/10000.0 - (w<0)*borrow_rate/12.0
    if np.any(1+net <= 0):
        raise ValueError('Month wipes out entire portfolio under short strategy')
    p['position'] = w
    p['turnover'] = turnover
    p['net_return'] = net
    p['equity'] = np.cumprod(1+net)
    return p


def performance(a: np.ndarray):
    a = np.asarray(a,float)
    eq = np.r_[1.,np.cumprod(1+a)]
    if np.any(eq<=0):
        return np.nan, np.nan, np.nan
    cagr = 100*(eq[-1]**(12/len(a))-1)
    sh = float(np.sqrt(12)*a.mean()/a.std(ddof=1)) if a.std(ddof=1)>1e-12 else np.nan
    dd = float(100*np.min(eq/np.maximum.accumulate(eq)-1))
    return cagr,sh,dd


def analyze_one(pred:pd.DataFrame, cost_bps:float, borrow_rate:float):
    ticker = pred.ticker.iloc[0]
    y = pred.observed_log_pp.to_numpy(float)
    b = pred.forecast_baseline_log_pp.to_numpy(float)
    g = pred.forecast_gpr_log_pp.to_numpy(float)
    mse_base=np.mean((y-b)**2)
    loss_diff=(y-b)**2-(y-g)**2
    mse_t,mse_p=mean_hac(loss_diff)
    result={'ticker':ticker,'group':NAMES.get(ticker,'Other'), 'n_oos':len(pred),
            'first':pred.return_month.iloc[0], 'last':pred.return_month.iloc[-1],
            'oos_r2_gpr_vs_base_pct':100*(1-np.mean((y-g)**2)/mse_base) if mse_base>0 else np.nan,
            'mse_diff_hac_t':mse_t,'mse_diff_hac_p':mse_p,
            'directional_acc_gpr_pct':100*np.mean((g>0)==(y>0)),
            'directional_acc_base_pct':100*np.mean((b>0)==(y>0))}
    ledger=[]
    for kind in ['hold','long_cash','long_short']:
        c={'hold':[('buy_hold', 'forecast_baseline_log_pp')],
           'long_cash':[('market_long_cash','forecast_baseline_log_pp'),('gpr_long_cash','forecast_gpr_log_pp')],
           'long_short':[('market_long_short','forecast_baseline_log_pp'),('gpr_long_short','forecast_gpr_log_pp')]}[kind]
        for name, col in c:
            curr=pnl_from_forecast(pred,col,kind,cost_bps,borrow_rate)
            curr['strategy']=name
            ledger.append(curr)
            cagr,sharpe,dd=performance(curr.net_return.to_numpy())
            result[name+'_cagr_pct']=cagr
            result[name+'_sharpe']=sharpe
            result[name+'_maxdd_pct']=dd
    led=pd.concat(ledger,ignore_index=True)
    pivot=led.pivot(index='return_month', columns='strategy',values='net_return')
    for kind in ['long_cash','long_short']:
        gain = pivot[f'gpr_{kind}']-pivot[f'market_{kind}']
        t,p=mean_hac(gain.to_numpy())
        result[f'{kind}_monthly_excess_pp']=100*gain.mean()
        result[f'{kind}_gain_hac_p']=p
        result[f'{kind}_gain_hac_t']=t
        result[f'{kind}_excess_cagr_pp']=result[f'gpr_{kind}_cagr_pct']-result[f'market_{kind}_cagr_pct']
    return result,led


def make_charts(report: pd.DataFrame, ledger: pd.DataFrame, out: Path, open_charts:bool):
    out.mkdir(parents=True,exist_ok=True)
    ranked=report.sort_values('oos_r2_gpr_vs_base_pct')
    if len(ranked):
        fig,ax=plt.subplots(figsize=(12,max(6,0.38*len(ranked)+1)))
        ax.barh(ranked.ticker, ranked.oos_r2_gpr_vs_base_pct)
        ax.axvline(0,lw=1)
        ax.set(xlabel='OOS R² GPR vs market model (%)',title='Does published GPR improve next-month ETF forecasts?')
        ax.grid(axis='x',alpha=.2)
        fig.tight_layout();fig.savefig(out/'01_oos_r2_all.png',dpi=170);plt.close(fig)
        ranked2=report.sort_values('long_cash_monthly_excess_pp')
        fig,ax=plt.subplots(figsize=(12,max(6,0.38*len(ranked2)+1)))
        ax.barh(ranked2.ticker, ranked2.long_cash_monthly_excess_pp)
        ax.axvline(0,lw=1)
        ax.set(xlabel='GPR model minus baseline: mean NET return (pp/month)',title='Incremental GPR trading edge | long/cash | OOS')
        ax.grid(axis='x',alpha=.2)
        fig.tight_layout();fig.savefig(out/'02_gpr_excess_long_cash.png',dpi=170);plt.close(fig)
        ranked3=report.sort_values('long_short_monthly_excess_pp')
        fig,ax=plt.subplots(figsize=(12,max(6,0.38*len(ranked3)+1)))
        ax.barh(ranked3.ticker,ranked3.long_short_monthly_excess_pp)
        ax.axvline(0,lw=1)
        ax.set(xlabel='GPR model minus baseline: mean NET return (pp/month)',title='Incremental GPR trading edge | long/short | OOS')
        ax.grid(axis='x',alpha=.2)
        fig.tight_layout();fig.savefig(out/'03_gpr_excess_long_short.png',dpi=170);plt.close(fig)
    # Include REMX regardless of rank; top ranked can be false discovery; plots remain exploratory.
    best=report.sort_values('oos_r2_gpr_vs_base_pct',ascending=False).ticker.head(4).tolist()
    for symbol in list(dict.fromkeys(['REMX','SPY']+best)):
        q=ledger[ledger.ticker.eq(symbol)].pivot(index='return_month',columns='strategy',values='equity')
        if q.empty: continue
        fig,ax=plt.subplots(figsize=(12,5))
        for k in ['buy_hold','market_long_cash','gpr_long_cash','market_long_short','gpr_long_short']:
            if k in q: ax.plot(q.index,q[k],label=k,lw=1.6)
        tick_step=max(1,len(q)//8)
        ax.set_xticks(range(0,len(q),tick_step))
        ax.set_xticklabels(q.index[::tick_step],rotation=35,ha='right')
        ax.set(ylabel='Net wealth from 1 USD', title=f'{symbol} | expanding OOS, strategy equity after estimated costs')
        ax.grid(alpha=.2);ax.legend(ncol=2,fontsize=8)
        fig.tight_layout();fig.savefig(out/f'04_equity_{symbol}.png',dpi=170);plt.close(fig)
    if open_charts:
        import subprocess
        for f in sorted(out.glob('*.png')):
            try: subprocess.Popen(['xdg-open',str(f)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except OSError: break


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=HERE/'output'/'etf_gpr_forecast')
    ap.add_argument('--project-raw',type=Path,default=HERE/'output'/'raw')
    ap.add_argument('--vintages',type=Path,default=HERE/'output'/'raw'/'gpr_vintages')
    ap.add_argument('--gpr-mode',choices=['final','vintage'],default='final')
    ap.add_argument('--fetch-vintages',action='store_true')
    ap.add_argument('--vintage-start',default='2019-01')
    ap.add_argument('--refresh-prices',action='store_true')
    ap.add_argument('--offline',action='store_true')
    ap.add_argument('--start',default='2007-01-01')
    ap.add_argument('--end',default=str(pd.Timestamp.now().date()+pd.Timedelta(days=1)))
    ap.add_argument('--tickers',nargs='+',default=UNIVERSE)
    ap.add_argument('--min-train',type=int,default=None)
    ap.add_argument('--min-oos',type=int,default=12)
    ap.add_argument('--ridge',type=float,default=10.0)
    ap.add_argument('--cost-bps',type=float,default=10.0)
    ap.add_argument('--borrow-annual',type=float,default=.03)
    ap.add_argument('--open',action='store_true')
    args=ap.parse_args(argv)
    if args.ridge < 0 or args.cost_bps < 0 or args.min_oos<12:
        ap.error('ridge, costs must be nonnegative; min-oos >= 12')
    if args.min_train is None:args.min_train=24 if args.gpr_mode=='vintage' else 72
    if args.min_train<18: ap.error('min-train must be >=18 months')
    if 'SPY' not in args.tickers: args.tickers = ['SPY'] + args.tickers
    raw=args.project_raw.resolve()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=True)
    prices, execution = load_prices(raw,args.tickers,args.start,args.refresh_prices,args.offline,args.end)
    last_month=prices.index.max()
    signals=load_gpr_signals(args.gpr_mode,raw,args.vintages.resolve(),args.fetch_vintages,args.vintage_start,last_month)
    signals=signals.loc[signals.index<=last_month].copy()
    signals.reset_index().assign(month=lambda d:d.month.astype(str)).to_csv(out/'gpr_asof_features.csv',index=False)
    all_predictions=[]; rows=[]; all_ledger=[]; skipped=[]
    for ticker in args.tickers:
        if ticker not in prices:
            skipped.append((ticker,'missing prices'))
            continue
        design=make_design(prices,signals,ticker)
        if len(design)<args.min_train+args.min_oos:
            skipped.append((ticker,f'only {len(design)} usable months (<{args.min_train+args.min_oos})'))
            continue
        pred=expanding_oos(design,ticker,args.min_train,args.ridge)
        # Fully separate forecasting target (month-end close) from realizable
        # trading return (first close to next first close). No same-close fill.
        if not pred.empty:
            realized=execution[ticker].copy()
            period_index=pd.PeriodIndex(pred.return_month,freq='M')
            pred['trade_return_simple']=realized.reindex(period_index).to_numpy(float)
            pred=pred.dropna(subset=['trade_return_simple']).reset_index(drop=True)
        if len(pred)<args.min_oos:
            skipped.append((ticker,f'only {len(pred)} OOS months'))
            continue
        report,ledger=analyze_one(pred,args.cost_bps,args.borrow_annual)
        rows.append(report);all_predictions.append(pred);all_ledger.append(ledger)
        print(f'[OOS] {ticker:5} n={len(pred):3} R2={report["oos_r2_gpr_vs_base_pct"]:+8.2f}%'
              f' excess L/C={report["long_cash_monthly_excess_pp"]:+7.3f} pp/mo',flush=True)
    if not rows:
        raise RuntimeError('No ETFs have enough contiguous OOS data. Check cached prices / GPR vintages.')
    report=pd.DataFrame(rows)
    for name in ['mse_diff_hac_p','long_cash_gain_hac_p','long_short_gain_hac_p']:
        report[name.replace('_p','_q_bh')]=bh_qvalues(report[name])
    report=report.sort_values('oos_r2_gpr_vs_base_pct',ascending=False)
    forecasts=pd.concat(all_predictions,ignore_index=True)
    ledger=pd.concat(all_ledger,ignore_index=True)
    report.to_csv(out/'leaderboard.csv',index=False,float_format='%.8f')
    forecasts.to_csv(out/'forecasts_oos.csv',index=False,float_format='%.8f')
    ledger.to_csv(out/'trades_monthly.csv',index=False,float_format='%.8f')
    make_charts(report,ledger,out/'figures',args.open)
    (out/'metadata.json').write_text(json.dumps({
        'gpr_mode':args.gpr_mode,'GPR_timing':'as of month t: last released month t-1, forecast t+1',
        'gpr_source':'Caldara-Iacoviello official monthly index',
        'vintage_note':'Actual vintage values, but source YYYYMM is assumed issued by that month end; publication timestamps unverified' if args.gpr_mode=='vintage' else 'FINAL-VINTAGE revision leakage possible. Not strict PIT.',
        'train_months':args.min_train,'ridge_fixed':args.ridge,'minimum_OOS_months':args.min_oos,
        'cost_bps_each_unit_turnover':args.cost_bps,'short_borrow_ann':args.borrow_annual,
        'cash_interest':'0 (conservative)','monthly_execution':'signal at month t end; transact at first trading-day close of t+1; exit first trading-day close of t+2; spread/slippage estimated fixed bps',
        'skipped':skipped, 'tickers_requested':args.tickers
    },indent=2,ensure_ascii=False),encoding='utf-8')
    print('\n=== OUT OF SAMPLE SCREEN ===')
    cols=['ticker','n_oos','oos_r2_gpr_vs_base_pct','mse_diff_hac_p','mse_diff_hac_q_bh',
          'directional_acc_gpr_pct','long_cash_monthly_excess_pp','long_cash_gain_hac_q_bh',
          'long_short_monthly_excess_pp','long_short_gain_hac_q_bh']
    print(report[cols].round(3).to_string(index=False))
    if skipped: print('\nSkipped:',skipped)
    print(f'\nSaved to {out} | data mode={args.gpr_mode} | historical publication timestamps are assumptions')
    print('Do not interpret selected best ETF as independent confirmation (multiple testing / data snooping).')

if __name__=='__main__': main()
