"""Synthetic offline checks (no claim about actual REMX performance)."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ma200_gpr_var_strategy import (load_prices, load_monthly_panel, event_var_forecasts,
                                    assemble_daily, positions, score)
from gpr_direction_strategy import build_events_final

class TestMA200(unittest.TestCase):
    def build_data(self, n=140):
        rng=np.random.default_rng(8)
        months=pd.period_range('2012-01',periods=n,freq='M')
        gpr=pd.Series(105*np.exp(np.cumsum(rng.normal(.001,.14,n))), index=months)
        daily_dates=pd.bdate_range(months[0].start_time, months[-1].end_time)
        ret=rng.normal(.0002,.016,len(daily_dates))
        price=np.exp(np.cumsum(ret))*50
        prices=pd.DataFrame({'date':daily_dates,'adj_close':price})
        prices['ma200']=prices.adj_close.rolling(200,min_periods=200).mean()
        prices['above_ma200_at_close']=prices.adj_close>prices.ma200
        prices['ma200_eligible_for_return']=prices.above_ma200_at_close.shift(2).astype('boolean').fillna(False).astype(bool)
        q=prices.assign(month=prices.date.dt.to_period('M')).groupby('month').adj_close.last()
        pct=100*np.log(q/q.shift(1))
        panel=pd.DataFrame({'GPR':gpr,'REMX':pct, 'SPY':rng.normal(.5,3,n),
                            'XME':rng.normal(.3,5,n)},index=months)
        return prices,panel,gpr

    def test_past_only_forecasts_and_ma200(self):
        prices,panel,gpr=self.build_data()
        events=build_events_final(gpr,10)
        fitted=event_var_forecasts(events,panel,gpr,'final',Path('/unused'),48)
        good=fitted[fitted.var_forecast_log_pp.notna()]
        self.assertGreater(len(good),35)
        changed=panel.copy()
        # A huge mutation of future data must not change a forecast issued earlier.
        changed.loc[changed.index[-1],'REMX'] += 5000
        newer=event_var_forecasts(events,panel=changed,gpr_final=gpr,source='final',vintage_dir=Path('/unused'),train_months=48)
        self.assertAlmostEqual(float(fitted.var_forecast_log_pp.iloc[80]),float(newer.var_forecast_log_pp.iloc[80]),places=9)
        daily,mapped=assemble_daily(prices,fitted)
        self.assertTrue((daily.date>mapped.loc[mapped.var_forecast_log_pp.notna(),'execution_close_date'].iloc[0]).all())
        # The position for a return ending today cannot use today's close as MA200 gate.
        sample=daily.iloc[12]
        i=prices.index[prices.date.eq(sample.date)][0]
        self.assertEqual(bool(sample.ma200_eligible_for_return),bool(prices.above_ma200_at_close.iloc[i-2]))
        pos=positions(daily)
        self.assertTrue(np.all(pos['ma200_gpr'][~daily.ma200_eligible_for_return.to_numpy(bool)]==0))
        self.assertTrue(np.all(pos['ma200_var_ls'][~daily.ma200_eligible_for_return.to_numpy(bool)]==0))
        summary, ledger=score(daily,10,.03)
        self.assertEqual(len(summary),9)
        self.assertTrue(np.isfinite(summary.cagr_pct).all())

    def test_previous_close_ma_filter(self):
        # Condition flips at previous close; it cannot affect return ending same day.
        dates=pd.bdate_range('2021-01-01',periods=6)
        base=pd.DataFrame({'date':dates,'return':[.0]*6,
            'ma200_eligible_for_return':[False,False,True,True,False,False],
            'known_signal':[1,1,1,1,1,1],
            'var_forecast_log_pp':[1.0]*6})
        p=positions(base)
        np.testing.assert_array_equal(p['ma200_gpr'],[0,0,1,1,0,0])
        np.testing.assert_array_equal(p['ma200_var'],[0,0,1,1,0,0])

if __name__=='__main__':unittest.main()
