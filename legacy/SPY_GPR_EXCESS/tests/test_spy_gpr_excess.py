"""Small point-in-time checks for SPY GPR backtest; no network needed."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from spy_gpr_excess import event_calendar, build_weights, simulate, summarize, load_spy
from gpr_direction_strategy import build_events_final, map_trades, build_events_vintage


def test_vintages(tmp_path):
    gd=tmp_path/'vintages';gd.mkdir()
    ms=pd.period_range('2019-01','2020-12',freq='M')
    for v in pd.period_range('2019-04','2021-01',freq='M'):
        # Every vintage only includes historical months through v-1.
        historical=ms[ms < v]
        values=np.arange(len(historical),dtype=float)+100
        if len(historical)>=3 and v.month%3==0:
            values[-1]-=5
        pd.DataFrame({'month':historical.astype(str),'GPR':values}).to_stata(
            gd/f'data_gpr_export_{v.year}{v.month:02d}.dta', write_index=False)
    events=event_calendar(build_events_vintage(gd,10),'month_end',10)
    assert len(events) > 10
    for e in events.itertuples(index=False):
        vintage=pd.Period(e.vintage_month,'M')
        assert pd.Period(e.signal_month,'M') == vintage-1
        assert e.assumed_release_date.month == vintage.month
        assert e.assumed_release_date.is_month_end
    dates=pd.bdate_range('2019-01-01','2021-03-31')
    prices=pd.DataFrame({'date':dates,'adj_close':100*np.exp(np.arange(len(dates))*.0004)})
    prices['ma200']=prices.adj_close.rolling(200).mean()
    prices['ma200_tradeable_for_return']=prices.adj_close.gt(prices.ma200).shift(2).fillna(False).astype(bool)
    daily,executions=map_trades(prices,events)
    assert len(daily)>300
    assert all(executions.execution_close_date > executions.assumed_release_date)
    # Signal dated in month m never trades until after end of vintage month m+1.
    for event in executions.itertuples(index=False):
        assert event.execution_close_date > pd.Period(event.vintage_month,'M').end_time.normalize()
    pos=build_weights(daily)
    actual=simulate(daily.assign(cash_return=0.),10,0.03)
    assert len(actual)==len(daily)*len(pos)
    assert pos['spy_buy_hold'].min()==1 and pos['spy_buy_hold'].max()==1
    baseline=actual.loc[actual.strategy=='spy_buy_hold'].net_return.to_numpy()
    ret=daily['return'].to_numpy()
    # 10 bp cost at starting position only for buy-and-hold.
    assert abs(baseline[0]-(ret[0]-.001)) < 1e-12
    assert np.max(np.abs(baseline[1:]-ret[1:]))<1e-12
    score=summarize(actual)
    bh=score.loc[score.strategy=='spy_buy_hold'].iloc[0]
    assert abs(bh['excess_cagr_vs_SPY_pp']) < 1e-12
    # Future archive revision must not change signal extracted from prior vintages.
    before=events.set_index('vintage_month').loc['2019-11','signal']
    later=gd/'data_gpr_export_202101.dta'
    df=pd.read_stata(later)
    df.loc[df.index[-1],'GPR']=10000
    df.to_stata(later,write_index=False)
    after=event_calendar(build_events_vintage(gd,10),'month_end',10).set_index('vintage_month').loc['2019-11','signal']
    assert before==after
    print('PASS vintage dates, no same-day trade, correct fees, no historical revision bleed')

if __name__=='__main__':
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_vintages(Path(d))
