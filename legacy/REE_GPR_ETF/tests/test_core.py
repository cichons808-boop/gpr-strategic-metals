import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pandas as pd
import polars as pl
from ree_gpr import month_str, normalize_gpr, prices_monthly, run_regressions, event_study

def test_month_parse():
    assert month_str('2025m9') == '2025-09'
    assert month_str('2025-09-01') == '2025-09'
    assert month_str(pd.Timestamp('2025-09-30')) == '2025-09'

def test_prices_gap():
    prices = pd.DataFrame({'date': ['2024-01-15','2024-01-31','2024-03-02','2024-03-29'],
                           'adj_close': [100,110,120,130]})
    p = prices_monthly(prices, 'REMX')
    assert p.height == 2
    assert p.filter(pl.col('month')=='2024-03')['ret_pct'][0] is None

def test_gpr():
    df = normalize_gpr(pd.DataFrame({'month':['2022m1','2022m2'], 'GPR':[100,150]}))
    assert df.height == 2
    assert df['month'].to_list() == ['2022-01','2022-02']

if __name__ == '__main__':
    test_month_parse();test_prices_gap();test_gpr();print('core tests: OK')
