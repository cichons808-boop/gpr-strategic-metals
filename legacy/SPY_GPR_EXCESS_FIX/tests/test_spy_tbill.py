"""Regression tests for FRED DTB3 coverage and as-of cash yields (no network)."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spy_gpr_excess import load_tbill


def write_tbill(path, dates, yields):
    pd.DataFrame({'DATE': dates, 'DTB3': yields}).to_csv(path, index=False)


def test_tbill_uses_earlier_fred_fixing_before_first_spy_day(tmp_path):
    path = tmp_path / 'DTB3.csv'
    write_tbill(path, ['2020-01-02', '2020-01-03', '2020-01-06', '2020-01-07', '2020-01-08'],
                [2.0, 3.0, 4.0, 5.0, 6.0])
    spy = pd.DataFrame({'date':pd.to_datetime(['2020-01-06','2020-01-07','2020-01-08'])})
    cash = load_tbill(path, spy, fetch=False)
    expected = np.expm1(np.log1p(np.array([3.0,4.0,5.0]) / 100) / 252)
    np.testing.assert_allclose(cash.to_numpy(), expected, rtol=1e-12)
    assert cash.notna().all()


def test_tbill_refuses_uncovered_price_history(tmp_path):
    path = tmp_path / 'DTB3.csv'
    write_tbill(path, ['2020-01-06','2020-01-07','2020-01-08'], [2., 3., 4.])
    spy = pd.DataFrame({'date':pd.to_datetime(['2010-01-06','2020-01-07'])})
    with pytest.raises(RuntimeError, match='--fetch-tbill'):
        load_tbill(path, spy, fetch=False)


def test_tbill_refreshes_incomplete_cache(tmp_path, monkeypatch):
    path = tmp_path / 'DTB3.csv'
    write_tbill(path, ['2020-01-06','2020-01-07','2020-01-08'], [2., 3., 4.])
    spy = pd.DataFrame({'date':pd.to_datetime(['2010-01-06','2010-01-07'])})
    body = b'DATE,DTB3\n2010-01-01,1.0\n2010-01-04,1.5\n2010-01-05,2.0\n2010-01-06,2.5\n2010-01-07,3.0\n'
    import requests
    class MockResponse:
        content = body * 100  # sufficient length (>1000) but duplicates handled
        def raise_for_status(self): pass
    # Construct one real CSV instead of repeated header lines.
    more = pd.DataFrame({'DATE':pd.date_range('2009-01-01','2010-01-08',freq='B'), 'DTB3':2.0})
    payload = more.to_csv(index=False).encode()
    class RealResponse:
        content = payload
        def raise_for_status(self): pass
    def fake_get(url, params, timeout, headers):
        assert params['cosd'] == '1954-01-01'
        return RealResponse()
    monkeypatch.setattr(requests, 'get', fake_get)
    cash = load_tbill(path, spy, fetch=True)
    assert cash.notna().all()
    assert pd.read_csv(path).shape[0] > 200
