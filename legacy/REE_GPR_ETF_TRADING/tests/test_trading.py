"""Offline tests for timing, look-ahead exclusion, returns and fees."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ree_trading import (load_panel, longest_unbroken, rolling_predictions,
                         net_monthly_returns, monthly_rets, evaluate_one)


def fixture(n=128, seed=21):
    rng = np.random.default_rng(seed)
    months = pd.period_range('2014-01', periods=n, freq='M')
    g = np.exp(np.cumsum(rng.normal(0, .18, n)))*100
    spy = rng.normal(.75, 3.8, n)
    xme = .7*spy + rng.normal(.5, 5., n)
    remx = np.zeros(n)
    shocks = np.r_[0.0, np.diff(np.log1p(g))]
    for t in range(2, n):
        remx[t] = 7.0*shocks[t-2] + .15*remx[t-1] + .3*xme[t-1] + rng.normal(0, 4)
    data = pd.DataFrame({'month': months.astype(str), 'GPR':g,
                         'SPY':spy,'XME':xme,'REMX':remx})
    return data


class StrategyChecks(unittest.TestCase):
    def test_log_to_simple(self):
        log100 = 100*np.log(2)
        self.assertAlmostEqual(float(monthly_rets(log100)),1.0,places=10)

    def test_turnover_and_short_costs(self):
        net, turnover, cost = net_monthly_returns(np.array([1,-1,0]),
                 np.array([.10,-.10,.0]), cost_bps=10., borrow_annual=.12)
        np.testing.assert_allclose(turnover, [1.,2.,1.])
        np.testing.assert_allclose(net, [.099, .088, -.001])
        np.testing.assert_allclose(cost, [.001, .012, .001])

    def test_missing_month_breaks_block(self):
        d = pd.DataFrame({'month': ['2020-01','2020-02','2020-04','2020-05','2020-06'],
                          'GPR':[1,2,3,4,5], 'REMX':[1,2,3,4,5],
                          'SPY':[1]*5, 'XME':[1]*5})
        with tempfile.TemporaryDirectory() as td:
            f = Path(td)/'p.csv';d.to_csv(f,index=False)
            panel=load_panel(f)
        block=longest_unbroken(panel,['REMX','SPY','XME'])
        self.assertEqual(len(block),3)
        self.assertEqual(str(block.index[0]),'2020-04')

    def test_no_future_information(self):
        df=fixture()
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'base.csv'; df.to_csv(f,index=False)
            panel=load_panel(f)
            first=rolling_predictions(panel,'REMX',60)
            mod=df.copy()
            mod.loc[mod.index[-1], 'GPR'] = 1e8
            mod.loc[mod.index[-1], 'REMX'] = -77
            f2=Path(td)/'changed.csv'; mod.to_csv(f2,index=False)
            second=rolling_predictions(load_panel(f2),'REMX',60)
        np.testing.assert_allclose(first['forecast_with_GPR_pp'],second['forecast_with_GPR_pp'], atol=1e-11)
        np.testing.assert_allclose(first['forecast_without_GPR_pp'],second['forecast_without_GPR_pp'], atol=1e-11)
        # last actual return has changed but the forecast for that last month hasn't.
        self.assertNotEqual(float(first.actual_log_return_pp.iloc[-1]),float(second.actual_log_return_pp.iloc[-1]))
        # For each out-of-sample month t, latest usable month is t-2, never t-1 or t.
        for _, row in first.iterrows():
            self.assertEqual(pd.Period(row['asof_month'],freq='M'),pd.Period(row['month'],freq='M')-2)

    def test_summary_complete(self):
        df=fixture(82)
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'p.csv';df.to_csv(f,index=False)
            oc=rolling_predictions(load_panel(f),'REMX',48)
        summary, ledger = evaluate_one(oc, cost_bps=10, borrow_annual=.03)
        self.assertEqual(len(summary),7)
        self.assertEqual(len(ledger),7*len(oc))
        self.assertTrue(np.isfinite(summary['total_pct']).all())


if __name__ == '__main__':
    unittest.main()
