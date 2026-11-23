import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from etf_gpr_forecast import (
    bh_qvalues, expanding_oos, load_gpr_signals,
    pnl_from_forecast, make_design, load_prices
)


def test_bh_qvalues():
    p=pd.Series([.01,.04,.02,np.nan])
    got=bh_qvalues(p)
    assert np.allclose(got.iloc[:3],[.03,.04,.03])
    assert np.isnan(got.iloc[-1])


def test_gpr_lag_no_nowcasting(tmp_path):
    raw=tmp_path/'raw';raw.mkdir()
    values=pd.DataFrame({'month':['2022-01','2022-02','2022-03','2022-04'],
                         'GPR':[90,100,120,999]})
    values.to_csv(raw/'data_gpr_export.csv',index=False)
    d=load_gpr_signals('final',raw,tmp_path/'v',False,'2022-01',pd.Period('2022-04'))
    # Month April close uses March and February, NEVER April value 999.
    assert d.loc[pd.Period('2022-04'),'gpr_month_used']=='2022-03'
    expected=np.log1p(120)-np.log1p(100)
    assert abs(d.loc[pd.Period('2022-04'),'gpr_dlog']-expected)<1e-12


def test_oos_predictions_unchanged_by_future_data():
    rng=np.random.default_rng(123)
    idx=pd.period_range('2014-01',periods=120,freq='M')
    ret=pd.DataFrame({'SPY':rng.normal(0,3,len(idx)),'REMX':rng.normal(0,7,len(idx))},index=idx)
    gpr=pd.DataFrame({'gpr_dlog':rng.normal(0,.3,len(idx))},index=idx)
    d=make_design(ret,gpr,'REMX')
    p1=expanding_oos(d.iloc[:70], 'REMX', 24, 10)
    d2=d.copy()
    d2.loc[d2.index[71]:,'y_next_log_pp']=99999
    d2.loc[d2.index[71]:,'gpr_dlog']=-99999
    p2=expanding_oos(d2, 'REMX', 24, 10)
    a=p1.iloc[:30].forecast_gpr_log_pp.to_numpy()
    b=p2.iloc[:30].forecast_gpr_log_pp.to_numpy()
    assert np.allclose(a,b)


def test_no_trade_before_signal_available_and_costs():
    p=pd.DataFrame({'ticker':['SPY','SPY'], 'return_month':['2024-02','2024-03'],
                    'forecast_gpr_log_pp':[2.,-1.],
                    'observed_log_pp':[1.,2.],
                    'trade_return_simple':[.04,-.05]})
    q=pnl_from_forecast(p,'forecast_gpr_log_pp','long_short',cost_bps=10,borrow_rate=.03)
    assert q.position.tolist()==[1.0,-1.0]
    # enter long costs 0.1%; switch +1 to -1 costs 0.2%; borrow 0.25%/month
    assert abs(q.net_return.iloc[0]-(.04-.001))<1e-12
    assert abs(q.net_return.iloc[1]-(.05-.002-.0025))<1e-12


def test_executable_returns_first_close_after_signal(tmp_path):
    raw=tmp_path/'raw';raw.mkdir()
    periods=pd.period_range('2020-01','2026-09',freq='M')
    rows=[]
    # Double print first/last close every month. First close of March=310,
    # first close of April=410: position entered March 1st session earns 410/310-1.
    for j,m in enumerate(periods):
        day1=m.start_time + pd.Timedelta(days=1)
        day2=m.end_time.normalize()-pd.Timedelta(days=1)
        rows += [{'date':day1,'adj_close':100+10*j},
                 {'date':day2,'adj_close':200+10*j}]
    pd.DataFrame(rows).to_csv(raw/'SPY_adjusted_daily.csv',index=False)
    _,entry=load_prices(raw,['SPY'],'2020-01-01',False,True,'2026-10-17')
    x=entry.loc[pd.Period('2025-03'),'SPY']
    j=list(periods).index(pd.Period('2025-03'))
    assert abs(x-((100+10*(j+1))/(100+10*j)-1))<1e-12
