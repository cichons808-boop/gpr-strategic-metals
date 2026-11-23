#!/usr/bin/env python3
"""Point-in-time conservative GPR->ETF monthly walk-forward trading test.

Uses an existing output/tables/panel_monthly.csv, with NO new downloads.
The return for month t is traded using ONLY observations dated <= t-2:
GPR for t-2 is normally released during t-1, so the signal is known by
month-end t-1. We deliberately don't use even the observed ETF return at
month-end t-1 to avoid assuming a filled trade at the same close.

WARNING: the downloaded GPR workbook is the CURRENT vintage, not necessarily
its original historical release. Results are not genuine point-in-time until
vintage GPR values are substituted. All prices assume adjusted-close fills.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.api import VAR

DEFAULT_TICKERS = ('REMX', 'SETM', 'ISTM')


def load_panel(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    expected = {'month', 'GPR', 'SPY', 'XME'}
    missing = expected.difference(raw.columns)
    if missing:
        raise ValueError(f'panel missing {sorted(missing)}; regenerate using ./run.sh')
    raw['month'] = pd.PeriodIndex(raw['month'].astype(str).str[:7], freq='M')
    if raw['month'].duplicated().any():
        raise ValueError('Duplicate months in data')
    raw = raw.set_index('month').sort_index()
    # Explicit reindex prevents treating multi-month gaps as one lag.
    raw = raw.reindex(pd.period_range(raw.index.min(), raw.index.max(), freq='M'))
    for c in raw.columns:
        raw[c] = pd.to_numeric(raw[c], errors='coerce')
    # RECOMPUTE raw first difference from LEVELS. Never use gpr_shock_sd:
    # that column was standardized using the FULL sample in the original project.
    gpr_log = np.log1p(raw['GPR'].where(raw['GPR'] >= 0))
    raw['GPR_CHANGE'] = gpr_log.diff()
    return raw


def longest_unbroken(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Longest genuinely contiguous sample with complete values."""
    df = df.loc[:, columns].dropna()
    if df.empty:
        return df
    ords = df.index.asi8
    splits = np.r_[0, np.flatnonzero(np.diff(ords) != 1) + 1, len(df)]
    blocks = [df.iloc[a:b] for a, b in zip(splits[:-1], splits[1:])]
    return max(blocks, key=len).copy()


def monthly_rets(log_return_pp: np.ndarray) -> np.ndarray:
    return np.expm1(np.asarray(log_return_pp, dtype=float) / 100.0)


def forecast_two_steps(train: pd.DataFrame, ticker: str, with_gpr: bool) -> float:
    """Fit VAR(1) only on past, forecast TWO steps ahead; return ETF log pp."""
    cols = (['GPR_CHANGE', 'SPY', 'XME', ticker] if with_gpr
            else ['SPY', 'XME', ticker])
    arr = train[cols]
    fit = VAR(arr).fit(maxlags=1, trend='c')
    pred = fit.forecast(arr.to_numpy()[-fit.k_ar:], steps=2)
    value = float(pred[1, -1])
    if not np.isfinite(value):
        raise ArithmeticError('Nonfinite VAR forecast')
    return value


def rolling_predictions(df: pd.DataFrame, ticker: str, min_train: int) -> pd.DataFrame:
    cols = ['GPR_CHANGE', 'SPY', 'XME', ticker]
    data = longest_unbroken(df, cols)
    if len(data) - (min_train + 2) < 12:
        raise ValueError(f'{ticker}: contiguous months={len(data)}, min_train={min_train}; '
                         f'need >=12 truly out-of-sample months, got {max(0,len(data)-min_train-2)}')
    results = []
    # At position i, only fit using indices <=i-2. GPR[i-2] was released
    # during i-1 and available for a trade spanning i-1 close to i close.
    for i in range(min_train + 2, len(data)):
        hist = data.iloc[:i-1]
        assert hist.index[-1] == data.index[i-2]
        try:
            gpr_forecast = forecast_two_steps(hist, ticker, True)
            market_forecast = forecast_two_steps(hist, ticker, False)
        except (np.linalg.LinAlgError, ValueError, ArithmeticError) as exc:
            # In rare degenerate samples fail loudly rather than cherry-picking
            # successful forecast months.
            raise RuntimeError(f'{ticker} model failed at {data.index[i]}: {exc}') from exc
        results.append({
            'month': str(data.index[i]),
            'ticker': ticker,
            'asof_month': str(data.index[i-2]),
            'gpr_signal': float(data['GPR_CHANGE'].iloc[i-2]),
            'forecast_with_GPR_pp': gpr_forecast,
            'forecast_without_GPR_pp': market_forecast,
            'actual_log_return_pp': float(data[ticker].iloc[i]),
            'actual_simple_return': float(monthly_rets(data[ticker].iloc[i])),
            'sample_train_n': int(len(hist)),
        })
    return pd.DataFrame(results)


def positions_from_forecast(oc: pd.DataFrame) -> dict[str, np.ndarray]:
    shock = oc['gpr_signal'].to_numpy(float)
    full = oc['forecast_with_GPR_pp'].to_numpy(float)
    base = oc['forecast_without_GPR_pp'].to_numpy(float)
    return {
        'buy_hold': np.ones(len(oc)),
        'gpr_positive_long_cash': (shock > 0).astype(float),
        'gpr_negative_long_cash': (shock < 0).astype(float),
        'var_gpr_long_cash': (full > 0).astype(float),
        'var_market_long_cash': (base > 0).astype(float),
        'var_gpr_long_short': np.where(full > 0, 1.0, -1.0),
        'var_market_long_short': np.where(base > 0, 1.0, -1.0),
    }


def net_monthly_returns(positions: np.ndarray, asset_returns: np.ndarray,
                        cost_bps: float, borrow_annual: float,
                        liquidate_end: bool = False):
    """Simple returns on portfolio equity, 100% gross maximum, zero cash yield."""
    w = np.asarray(positions, dtype=float)
    r = np.asarray(asset_returns, dtype=float)
    if w.ndim != 1 or w.shape != r.shape or not np.isin(w, [-1, 0, 1]).all():
        raise ValueError('positions must be -1/0/+1, same length as monthly returns')
    if cost_bps < 0 or borrow_annual < 0:
        raise ValueError('Trading costs and annual borrow rates must be nonnegative')
    turnover = np.abs(np.diff(np.r_[0.0, w]))
    if liquidate_end and len(w):
        turnover[-1] += abs(w[-1])
    fees = turnover * (cost_bps / 10000.0)
    # Not the ETF's management fee (already included in adjusted returns).
    # Short-sale borrow expense and funding are simplistic assumptions.
    borrow = np.maximum(-w, 0) * (borrow_annual / 12.0)
    profits = w * r - fees - borrow
    return profits, turnover, fees + borrow


def metrics(strategy: str, ticker: str, months: list[str], net: np.ndarray,
            turnover: np.ndarray, positions: np.ndarray, bench: np.ndarray) -> dict:
    n = len(net)
    capital = np.cumprod(1 + net)
    if np.any((1 + net) <= 0):
        return dict(ticker=ticker, strategy=strategy, months=n, first=months[0],
                    last=months[-1], total_pct=-100.0, cagr_pct=-100.0,
                    sharpe=np.nan, max_dd_pct=-100.0, vol_ann_pct=np.nan,
                    time_in_market_pct=float(100*np.mean(positions!=0)),
                    turnover_units=float(turnover.sum()),
                    benchmark_total_pct=float(100*(np.prod(1+bench)-1)),
                    mean_excess_monthly_pp=float(100*np.mean(net-bench)))
    total = 100.0 * (capital[-1] - 1)
    cagr = 100 * (capital[-1]**(12/n)-1)
    vol = float(net.std(ddof=1)) if n > 1 else 0.0
    sharpe = np.sqrt(12) * net.mean()/vol if vol > 0 else np.nan
    eq = np.r_[1, capital]
    dd = eq/np.maximum.accumulate(eq)-1
    return {
        'ticker': ticker, 'strategy': strategy, 'months': n,
        'first': months[0], 'last': months[-1],
        'total_pct': float(total), 'cagr_pct': float(cagr),
        'sharpe': float(sharpe),
        'max_dd_pct': float(dd.min()*100),
        'vol_ann_pct': float(vol*np.sqrt(12)*100),
        'time_in_market_pct': float(100*np.mean(positions != 0)),
        'turnover_units': float(turnover.sum()),
        'benchmark_total_pct': float(100*(np.prod(1+bench)-1)),
        'mean_excess_monthly_pp': float(100*np.mean(net-bench))
    }


def hac_t_pvalue(diff: np.ndarray, lags: int = 3) -> tuple[float, float]:
    diff = np.asarray(diff, dtype=float)
    if len(diff) < 12 or not np.isfinite(diff).all():
        return float('nan'), float('nan')
    res = sm.OLS(diff, np.ones((len(diff), 1))).fit(
        cov_type='HAC', cov_kwds={'maxlags': min(lags, len(diff)-1)})
    return float(res.tvalues[0]), float(res.pvalues[0])


def evaluate_one(oc: pd.DataFrame, cost_bps: float, borrow_annual: float):
    ticker = str(oc['ticker'].iloc[0])
    dates = oc['month'].tolist()
    ret = oc['actual_simple_return'].to_numpy()
    pos = positions_from_forecast(oc)
    result = []
    detailed = []
    baseline, _, _ = net_monthly_returns(pos['buy_hold'], ret, cost_bps, borrow_annual)
    for name, p in pos.items():
        net, turnover, fees = net_monthly_returns(p, ret, cost_bps, borrow_annual)
        result.append(metrics(name, ticker, dates, net, turnover, p, baseline))
        # Compare NET trading excess over benchmark; not a causal test of GPR.
        test_t, test_p = hac_t_pvalue(net - baseline)
        result[-1]['hac_excess_t'] = test_t
        result[-1]['hac_excess_p'] = test_p
        tmp = oc[['month','ticker','asof_month','gpr_signal','forecast_with_GPR_pp',
                  'forecast_without_GPR_pp','actual_simple_return']].copy()
        tmp['strategy'] = name
        tmp['position'] = p
        tmp['turnover'] = turnover
        tmp['fees_and_borrow'] = fees
        tmp['net_simple_return'] = net
        tmp['equity'] = np.cumprod(1 + net)
        detailed.append(tmp)
    return pd.DataFrame(result), pd.concat(detailed, ignore_index=True)


def incremental_tests(ledger: pd.DataFrame, forecasts: pd.DataFrame) -> pd.DataFrame:
    """Paired OOS tests: does adding GPR improve forecasts and strategy returns?"""
    rows = []
    for ticker, sub in ledger.groupby('ticker'):
        q = sub.pivot(index='month', columns='strategy', values='net_simple_return')
        for kind in ['long_cash', 'long_short']:
            a = q[f'var_gpr_{kind}'].to_numpy(float)
            b = q[f'var_market_{kind}'].to_numpy(float)
            t, p = hac_t_pvalue(a-b)
            rows.append({'ticker': ticker, 'comparison':f'var_gpr_vs_market_{kind}',
                         'oos_months':len(a), 'mean_monthly_gain_pp':100*np.mean(a-b),
                         'hac_t':t, 'hac_p':p})
        preds = forecasts.loc[forecasts['ticker'] == ticker]
        y = preds['actual_log_return_pp'].to_numpy(float)
        full = preds['forecast_with_GPR_pp'].to_numpy(float)
        base = preds['forecast_without_GPR_pp'].to_numpy(float)
        # Positive loss difference means the GPR model has lower MSE.
        diff = (y-base)**2 - (y-full)**2
        t, p = hac_t_pvalue(diff)
        rows.append({'ticker':ticker, 'comparison':'market_MSE_minus_GPR_MSE',
                     'oos_months':len(diff), 'mean_monthly_gain_pp':float(np.mean(diff)),
                     'hac_t':t, 'hac_p':p})
    return pd.DataFrame(rows)


def subperiod_stats(ledger: pd.DataFrame, cost_bps: float, borrow_annual: float) -> pd.DataFrame:
    # Pre-specified break motivated by substantive post-2021 regime changes.
    rows = []
    for ticker, sub in ledger.groupby('ticker'):
        for label, dates in [('pre_2021', sub['month'] < '2021-01'),
                             ('post_2021', sub['month'] >= '2021-01')]:
            d = sub.loc[dates]
            n = d['month'].nunique()
            if n < 12:
                continue
            for strategy, g in d.groupby('strategy'):
                g = g.sort_values('month')
                r = g['net_simple_return'].to_numpy(float)
                if (1+r<=0).any():
                    continue
                eq = np.cumprod(1+r)
                path = np.r_[1.,eq]
                rows.append({'ticker':ticker, 'subperiod':label, 'strategy':strategy,
                    'months':n, 'total_pct':float(100*(eq[-1]-1)),
                    'sharpe':float(np.sqrt(12)*r.mean()/r.std(ddof=1)) if r.std(ddof=1)>0 else np.nan,
                    'max_dd_pct':float(100*np.min(path/np.maximum.accumulate(path)-1))})
    return pd.DataFrame(rows)


def forecast_accuracy(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker, subset in predictions.groupby('ticker'):
        y = subset['actual_log_return_pp'].to_numpy()
        full = subset['forecast_with_GPR_pp'].to_numpy()
        base = subset['forecast_without_GPR_pp'].to_numpy()
        mse_base = np.mean((y-base)**2)
        rows.append({'ticker': ticker, 'n_oos':len(subset),
                    'mse_with_GPR':float(np.mean((y-full)**2)),
                    'mse_without_GPR':float(mse_base),
                    'oos_r2_vs_market_VAR':float(1 - np.mean((y-full)**2)/mse_base) if mse_base>0 else np.nan,
                    'sign_accuracy_with_GPR':float(np.mean((full>0)==(y>0))),
                    'sign_accuracy_without_GPR':float(np.mean((base>0)==(y>0)))})
    return pd.DataFrame(rows)


def charts(monthly: pd.DataFrame, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    selected = ['buy_hold','gpr_positive_long_cash','gpr_negative_long_cash',
                'var_gpr_long_cash','var_market_long_cash']
    for ticker, group in monthly.groupby('ticker'):
        curves = group.loc[group['strategy'].isin(selected)].pivot(index='month', columns='strategy', values='equity')
        fig, ax = plt.subplots(figsize=(11, 5.3))
        for name in selected:
            if name in curves.columns:
                ax.plot(curves.index, curves[name], lw=1.6, label=name)
        ax.set(title=f'{ticker} | OUT-OF-SAMPLE | after estimated costs',
               ylabel='Equity from 1 USD', xlabel='Month (trade held one month)')
        ax.grid(alpha=.24); ax.legend(fontsize=8, ncol=2, loc='best')
        if len(curves) > 12:
            step = max(1,len(curves)//8)
            ax.set_xticks(list(curves.index[::step]))
        fig.autofmt_xdate(rotation=30)
        fig.tight_layout()
        fig.savefig(out/f'equity_{ticker}.png', dpi=170)
        plt.close(fig)


def main():
    project = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--panel', type=Path, default=project/'output/tables/panel_monthly.csv')
    p.add_argument('--out', type=Path, default=project/'output/trading')
    p.add_argument('--etfs', nargs='+', default=list(DEFAULT_TICKERS))
    p.add_argument('--min-train-remx', type=int, default=72)
    p.add_argument('--min-train-other', type=int, default=26)
    p.add_argument('--cost-bps', type=float, default=10.0,
                   help='Each 1.0 unit change of position costs N bps, default 10')
    p.add_argument('--borrow-annual', type=float, default=0.03,
                   help='Estimated borrow fee on short positions (default 3%% annual)')
    a = p.parse_args()
    if not a.panel.exists():
        p.error(f'Panel not found: {a.panel}. Run ./run.sh first.')
    df = load_panel(a.panel)
    a.out.mkdir(parents=True, exist_ok=True)
    if a.cost_bps < 0 or a.borrow_annual < 0:
        p.error('Costs cannot be negative')
    frames = []
    for ticker in a.etfs:
        if ticker not in df:
            print(f'[SKIP] {ticker}: no prices in panel'); continue
        threshold = a.min_train_remx if ticker == 'REMX' else a.min_train_other
        print(f'[FIT] {ticker}: expanding VAR(1) OOS, 2-month information embargo, train >= {threshold}...')
        try:
            frame = rolling_predictions(df, ticker, threshold)
            print(f'  [OK] {len(frame)} strictly OOS months ({frame.month.iloc[0]} to {frame.month.iloc[-1]})')
            frames.append(frame)
        except ValueError as e:
            print(f'[SKIP] {e}')
    if not frames:
        raise SystemExit('No ETF has >=12 out-of-sample months; try --min-train-other 22 for a preliminary sensitivity check.')
    forecasts = pd.concat(frames, ignore_index=True)
    report_parts, ledger_parts = [], []
    for ticker, frame in forecasts.groupby('ticker'):
        stats, ledger = evaluate_one(frame, a.cost_bps, a.borrow_annual)
        report_parts.append(stats); ledger_parts.append(ledger)
    summary = pd.concat(report_parts, ignore_index=True)
    ledger = pd.concat(ledger_parts, ignore_index=True)
    acc = forecast_accuracy(forecasts)
    incremental = incremental_tests(ledger, forecasts)
    subs = subperiod_stats(ledger, a.cost_bps, a.borrow_annual)
    summary.to_csv(a.out/'strategy_summary.csv', index=False, float_format='%.8f')
    forecasts.to_csv(a.out/'walkforward_forecasts.csv', index=False, float_format='%.8f')
    ledger.to_csv(a.out/'monthly_trades.csv', index=False, float_format='%.8f')
    acc.to_csv(a.out/'forecast_accuracy.csv', index=False, float_format='%.8f')
    incremental.to_csv(a.out/'incremental_gpr_tests.csv', index=False, float_format='%.8f')
    subs.to_csv(a.out/'subperiod_performance.csv', index=False, float_format='%.8f')
    charts(ledger, a.out/'figures')
    (a.out/'metadata.json').write_text(json.dumps({
        'estimated_cost_bps_per_100pct_turnover':a.cost_bps,
        'borrow_annual': a.borrow_annual,
        'cash_yield':'zero',
        'information_embargo_months':2,
        'trading_rule':'For return in month t, model uses actual info only through t-2; trade at t-1 close',
        'market_returns':'Adjusted monthly close-to-close log returns transformed to simple before PnL',
        'forecast_horizon':'VAR(1) two steps ahead; expanding window; comparison excluding GPR',
        'historical_vintage_warning':'GPR dataset downloaded today is revised; release-vintage history not replicated',
        'execution_warning':'Month-end adjusted-close fills and constant bps costs are approximations'
    }, indent=2), encoding='utf-8')
    display = ['ticker','strategy','months','total_pct','cagr_pct','sharpe','max_dd_pct','turnover_units']
    print('\nOOS NET RESULTS (zero interest on cash, costs per full position turnover):')
    print(summary[display].round(3).to_string(index=False))
    print('\nFORECAST INFORMATION ADDED BY GPR:')
    print(acc.round(4).to_string(index=False))
    print('\nINCREMENTAL GPR TESTS (paired net PnL and MSE differences, HAC):')
    print(incremental.round(4).to_string(index=False))
    print('\nImportant: final-vintage GPR may have revision bias; trades at adjusted monthly closes are idealized.')
    print(f'Saved: {a.out}')


if __name__ == '__main__':
    main()
