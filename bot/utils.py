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
