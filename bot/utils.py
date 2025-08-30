import re
import requests
import config
from bot.decorators import retry_on_network_error
from logging_config import api_logger


def translate_alert_type(alert_type):
    return {"alert_price": "قیمت", "alert_candle": "کندل", "alert_rsi": "RSI"}.get(
        alert_type, "ناشناخته"
    )


@retry_on_network_error(max_retries=2, initial_delay=1)
def is_valid_pair(pair: str) -> bool:
    """Synchronous version of is_valid_pair for use in async handlers."""
    url = f"{config.BITUNIX_API_URL}/futures/market/tickers"
    params = {"symbols": pair}
    api_logger.info(f"REQUEST -> is_valid_pair: URL={url}, Params={params}")

    response = requests.get(url=url, params=params, timeout=5)
    api_logger.info(
        f"RESPONSE -> is_valid_pair: Status={response.status_code}, Body={response.text}"
    )
    response.raise_for_status()  # Will trigger retry if status code is an error

    if response.status_code == 200 and response.json().get("data"):
        return True
    return False


def parse_duration(duration_str: str) -> int:
    """
    Parses a duration string like '1h30m10s' into total seconds.
    Supports h, m, and s units. Returns 0 if the format is invalid.
    """
    parts = re.findall(r"(\d+)([hms])", duration_str.lower())
    if not parts:
        return 0

    seconds = 0
    for value, unit in parts:
        value = int(value)
        if unit == "h":
            seconds += value * 3600
        elif unit == "m":
            seconds += value * 60
        elif unit == "s":
            seconds += value
    return seconds
