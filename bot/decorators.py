import asyncio
import time
from functools import wraps
from requests.exceptions import RequestException
from telegram.error import NetworkError
from logging_config import logger


def retry_on_network_error(max_retries=3, initial_delay=2):
    """
    A decorator to retry a function if a RequestException or
    Telegram NetworkError occurs, using exponential backoff.
    """

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (RequestException, NetworkError) as e:
                    logger.warning(
                        f"Network error in '{func.__name__}' (Attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay} seconds..."
                    )
                    if attempt == max_retries - 1:
                        logger.error(
                            f"Function '{func.__name__}' failed after {max_retries} attempts."
                        )
                        return None
                    await asyncio.sleep(delay)
                    delay *= 2
            return None

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except RequestException as e:
                    logger.warning(
                        f"Network error in '{func.__name__}' (Attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay} seconds..."
                    )
                    if attempt == max_retries - 1:
                        logger.error(
                            f"Function '{func.__name__}' failed after {max_retries} attempts."
                        )
                        return None
                    time.sleep(delay)
                    delay *= 2
            return None

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
