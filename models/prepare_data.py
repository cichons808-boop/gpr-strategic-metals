"""Read the adjusted daily ETF prices from the saved provider responses."""

import json

import pandas as pd

from paths import RAW, PROCESSED

prices = []
for asset in ["REMX", "LIT", "COPX", "SPY"]:
    source = RAW / "market" / "daily" / f"{asset}_daily.json"
    data = json.loads(source.read_text())["chart"]["result"][0]
    dates = (
        pd.to_datetime(data["timestamp"], unit="s", utc=True)
        .tz_convert("America/New_York")
        .tz_localize(None)
        .normalize()
    )
    series = pd.Series(
        data["indicators"]["adjclose"][0]["adjclose"], index=dates, name=asset
    )
    assert series.index.is_unique
    prices.append(series)

prices = pd.concat(prices, axis=1).dropna().loc[:"2026-10-31"]
assert (prices > 0).all().all()
prices.to_csv(PROCESSED / "market" / "daily_adjusted_prices.csv", index_label="date")
