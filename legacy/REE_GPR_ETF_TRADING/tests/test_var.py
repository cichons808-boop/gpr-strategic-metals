"""Offline tests for VAR research module; never claims real-data results."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import numpy as np
import pandas as pd
from ree_var import contiguous_sample, fit_var, girf_gpr_to_etf, bootstrap_girf


def test_missing_month_not_spliced():
    d = pd.DataFrame({'month':['2024-01','2024-02','2024-04','2024-05','2024-06'],
                      'gpr_shock_sd': [1,2,3,4,5], 'REMX':[1,2,3,4,5]})
    block, lost = contiguous_sample(d, ['gpr_shock_sd','REMX'])
    assert len(block) == 3 and lost == 2
    assert str(block.index[0]) == '2024-04'


def test_var_detects_known_lagged_effect():
    rng = np.random.default_rng(42)
    n=170
    z=np.zeros(n); ret=np.zeros(n)
    for t in range(1,n):
        z[t]=.3*z[t-1]+rng.normal()
        ret[t]=.2*ret[t-1]+1.8*z[t-1]+rng.normal(scale=1.5)
    s = pd.DataFrame({'gpr_shock_sd': z, 'REMX': ret})
    fit, selection = fit_var(s, user_maxlags=2)
    a = girf_gpr_to_etf(fit, 'REMX', horizon=3)
    assert len(a) == 4 and a[1] > 0.75
    assert fit.test_causality('REMX', ['gpr_shock_sd'], kind='f').pvalue < .01
    ci = bootstrap_girf(fit, 'REMX', horizon=3, draws=40, seed=4)
    assert ci is not None
    assert np.all(ci['low'] <= ci['high'])


if __name__ == '__main__':
    test_missing_month_not_spliced()
    test_var_detects_known_lagged_effect()
    print('VAR tests: OK (synthetic samples)')
