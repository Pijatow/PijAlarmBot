import requests
import pandas as pd
import numpy as np
from typing import List, Optional

import config
from bot.decorators import retry_on_network_error
from logging_config import api_logger, logger


@retry_on_network_error()
def get_kline_data(
    pair: str, timeframe: str, limit: int = 200
) -> Optional[List[float]]:
    """
    Fetches historical k-line (candlestick) data from the BitUnix REST API.
    Returns a list of closing prices.
    """
    url = f"{config.BITUNIX_API_URL}/futures/market/kline"
    params = {"symbol": pair, "interval": timeframe, "limit": limit}
    api_logger.info(f"REQUEST -> get_kline_data: URL={url}, Params={params}")

    response = requests.get(url, params=params, timeout=10)
    api_logger.info(f"RESPONSE -> get_kline_data: Status={response.status_code}")
    response.raise_for_status()

    data = response.json().get("data", [])
    # The closing price is the 5th element (index 4) in each sub-array.
    # Added a check to ensure the candle list is well-formed before accessing index 4.
    closing_prices = [
        float(candle[4])
        for candle in data
        if isinstance(candle, list) and len(candle) > 4
    ]
    return closing_prices


def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """
    Calculates the Relative Strength Index (RSI) for a given list of prices.
    """
    if len(prices) < period:
        return None

    series = pd.Series(prices)
    delta = series.diff()

    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    # Return the most recent RSI value
    return rsi.iloc[-1]
