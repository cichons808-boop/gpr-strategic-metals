import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gpr_direction_strategy import build_events_final, map_trades, evaluate_strategy

class TestTimingAndTrade(unittest.TestCase):
    def test_release_not_applied_to_prior_return(self):
        months = pd.period_range('2020-01', '2020-05', freq='M')
        gpr = pd.Series([100, 120, 80, 90, 110],index=months)
        events=build_events_final(gpr,release_day=10)
        dates = pd.bdate_range('2020-03-01','2020-06-28')
        prices = pd.DataFrame({'date':dates,'adj_close':100.0+np.arange(len(dates))})
        day, signal_events=map_trades(prices,events)
        first=signal_events.iloc[0]
        self.assertEqual(first.signal_month,'2020-02')
        self.assertEqual(first.assumed_release_date.strftime('%Y-%m-%d'),'2020-03-10')
        self.assertGreater(first.execution_close_date,first.assumed_release_date)
        self.assertGreater(day.date.iloc[0], first.execution_close_date)
        self.assertEqual(int(day.known_signal.iloc[0]),1)
        self.assertTrue((day.date>first.execution_close_date).all())

    def test_future_gpr_change_cannot_change_past_positions(self):
        idx=pd.period_range('2020-01','2021-02',freq='M')
        a=pd.Series(np.arange(10.,24.),index=idx)
        b=a.copy();b.iloc[-2:]=[300,1]
        e1=build_events_final(a,10);e2=build_events_final(b,10)
        up_to='2021-01'
        x=e1[e1.signal_month<up_to].signal.to_list()
        y=e2[e2.signal_month<up_to].signal.to_list()
        self.assertEqual(x,y)

    def test_fees_long_short_direction(self):
        # A non-signal price move before the new publication is never retroactively assigned a new position.
        df=pd.DataFrame({'date':pd.bdate_range('2024-01-01',periods=4),
                         'return':[.1,-.2,.05,0.], 'known_signal':[1,1,-1,-1]})
        result=evaluate_strategy(df,'long_cash',10,.03)
        self.assertEqual(result.position.to_list(),[1.,1.,0.,0.])
        np.testing.assert_allclose(result.net_return.to_numpy(), [.099,-.2,-.001,0.])
        out=evaluate_strategy(df,'long_short',10,.03)
        self.assertEqual(out.position.to_list(),[1.,1.,-1.,-1.])
        self.assertAlmostEqual(float(out.turnover.iloc[2]),2.)

if __name__=='__main__':
    unittest.main()
