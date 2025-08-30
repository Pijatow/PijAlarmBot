import re
import requests
import config
from logging_config import api_logger


def translate_alert_type(alert_type):
    return {"alert_price": "قیمت", "alert_candle": "کندل"}.get(alert_type, "ناشناخته")


async def is_valid_pair(pair: str) -> bool:
    url = f"{config.BITUNIX_API_URL}/futures/market/tickers"
    params = {"symbols": pair}
    api_logger.info(f"REQUEST -> is_valid_pair: URL={url}, Params={params}")
    try:
        response = requests.get(url=url, params=params, timeout=5)
        api_logger.info(
            f"RESPONSE -> is_valid_pair: Status={response.status_code}, Body={response.text}"
        )
        if response.status_code == 200 and response.json().get("data"):
            return True
        return False
    except requests.RequestException as e:
        api_logger.error(f"RESPONSE ERROR -> is_valid_pair: {e}")
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
