import asyncio
import json
import websockets
from websockets.exceptions import ConnectionClosed
import config
from logging_config import api_logger, logger


class BitunixWSClient:
    def __init__(self, url):
        self.url = url
        self.subscriptions = set()
        self.websocket = None
        self.is_running = False

    async def _send_json(self, message):
        if self.websocket:
            await self.websocket.send(json.dumps(message))

    async def _subscribe(self, pair: str):
        """Subscribes to a specific pair's ticker channel."""
        self.subscriptions.add(pair)
        if self.websocket:
            sub_message = {"op": "subscribe", "args": [f"tickers.{pair}"]}
            await self._send_json(sub_message)
            api_logger.info(f"Sent subscription request for {pair}")

    async def _process_message(self, message):
        """Processes incoming messages from the WebSocket."""
        try:
            data = json.loads(message)

            # Handle ping/pong to keep connection alive
            if "ping" in data:
                await self._send_json({"pong": data["ping"]})
                return

            # Handle subscription confirmations
            if data.get("op") == "subscribe":
                api_logger.info(f"Successfully subscribed to: {data.get('arg')}")
                return

            # Process ticker data
            if data.get("table") == "tickers":
                for ticker_data in data.get("data", []):
                    pair = ticker_data.get("symbol")
                    price = ticker_data.get("lastPrice")
                    if pair and price:
                        config.LATEST_PRICES[pair] = float(price)

        except json.JSONDecodeError:
            api_logger.warning(f"Could not decode JSON: {message}")
        except Exception as e:
            logger.exception(f"Error processing WebSocket message: {e}")

    async def run(self):
        """The main loop to connect, reconnect, and process messages."""
        self.is_running = True
        while self.is_running:
            try:
                async with websockets.connect(self.url) as ws:
                    self.websocket = ws
                    api_logger.info("Successfully connected to Bitunix WebSocket API.")

                    # Re-subscribe to all tracked pairs on connection
                    for pair in list(self.subscriptions):
                        await self._subscribe(pair)

                    async for message in self.websocket:
                        await self._process_message(message)

            except (
                ConnectionClosed,
                ConnectionRefusedError,
                asyncio.TimeoutError,
            ) as e:
                api_logger.error(
                    f"WebSocket connection lost: {e}. Reconnecting in 10 seconds..."
                )
            except Exception as e:
                logger.exception(
                    "An unexpected error occurred in the WebSocket client."
                )
            finally:
                self.websocket = None
                await asyncio.sleep(10)

    def add_subscription(self, pair: str):
        """Public method to add a new subscription."""
        if pair not in self.subscriptions:
            api_logger.info(f"Queueing subscription for {pair}")
            # The `run` loop will pick up the new subscription
            # on the next connection or we can send it live
            if self.websocket:
                asyncio.create_task(self._subscribe(pair))
            else:
                self.subscriptions.add(pair)


ws_client = BitunixWSClient(config.BITUNIX_WS_URL)
