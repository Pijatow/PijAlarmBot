import asyncio
from typing import Dict, Any

from telegram.ext import Application
from telegram.error import BadRequest

import config
from api_manager import ws_client
from bot.data_fetcher import get_kline_data, calculate_rsi
from database_manager import DatabaseManager
from logging_config import logger, api_logger, msg_logger
from bot.ui import AlertManager

db = DatabaseManager(config.DB_FILE)


def stop_alarm_task(alert_id: int):
    task = config.ACTIVE_ALARM_TASKS.pop(alert_id, None)
    if task:
        task.cancel()
        logger.info(f"Cancelled alarm task for alert_id: {alert_id}")


async def start_alarm_task(application: Application, alert_data: Dict[str, Any]):
    alert_id = alert_data.get("id")
    if not alert_id:
        logger.error(f"Attempted to start task for alert with no ID: {alert_data}")
        return

    alert_type = alert_data.get("alert_type")

    if alert_type == "alert_price":
        # Ensure we have a WebSocket subscription for this pair
        ws_client.add_subscription(alert_data["pair"])
        task = asyncio.create_task(price_alert_monitor(application, alert_data))
    elif alert_type == "alert_rsi":
        task = asyncio.create_task(rsi_alert_monitor(application, alert_data))
    else:
        logger.warning(f"Unsupported alert_type for task start: {alert_type}")
        return

    config.ACTIVE_ALARM_TASKS[alert_id] = task
    logger.info(f"Started '{alert_type}' task for alert_id: {alert_id}")


async def rsi_alert_monitor(application: Application, alert_data: Dict[str, Any]):
    user_id = alert_data["user_id"]
    alert_id = alert_data["id"]
    pair = alert_data["pair"]
    timeframe = alert_data["timeframe"]
    rsi_period = alert_data["rsi_period"]
    rsi_condition = alert_data["rsi_condition"]
    rsi_threshold = float(alert_data["price"])  # Using 'price' column for threshold

    while True:
        try:
            current_alert_state = db.get_alert_by_id(user_id, alert_id)
            if not current_alert_state or not current_alert_state["is_active"]:
                logger.info(f"Alert {alert_id} is no longer active. Stopping task.")
                stop_alarm_task(alert_id)
                break

            closing_prices = get_kline_data(pair, timeframe, limit=rsi_period + 100)

            if closing_prices:
                current_rsi = calculate_rsi(closing_prices, rsi_period)
                if current_rsi is not None:
                    triggered, reason = False, ""

                    if rsi_condition == "above" and current_rsi > rsi_threshold:
                        triggered = True
                        reason = (
                            f"📈 RSI ({current_rsi:.2f}) از {rsi_threshold} بالاتر رفت!"
                        )
                    elif rsi_condition == "below" and current_rsi < rsi_threshold:
                        triggered = True
                        reason = f"📉 RSI ({current_rsi:.2f}) از {rsi_threshold} پایین تر آمد!"

                    if triggered:
                        # To prevent spamming, we will temporarily disable the alert after it triggers.
                        # A more advanced implementation might re-enable it after a cooldown.
                        db.update_alert_field(alert_id, "is_active", 0)

                        new_trigger_count = (
                            current_alert_state.get("trigger_count", 0) + 1
                        )
                        msg_text = AlertManager.format_trigger_message(
                            current_alert_state,
                            reason,
                            current_rsi,
                            new_trigger_count,
                        )
                        await application.bot.send_message(user_id, msg_text)
                        logger.info(
                            f"TRIGGERED (RSI) -> Alert ID: {alert_id} for User: {user_id}. Reason: {reason}"
                        )

                        # Since this alert type is now disabled, we stop the monitor task.
                        stop_alarm_task(alert_id)
                        break

            # Check frequency based on timeframe to be efficient
            await asyncio.sleep(60)  # Check every minute

        except Exception as e:
            logger.exception(
                f"UNEXPECTED ERROR in rsi_alert_monitor for alert {alert_id}:"
            )
            stop_alarm_task(alert_id)
            break


async def price_alert_monitor(application: Application, alert_data: Dict[str, Any]):
    user_id = alert_data["user_id"]
    pair = alert_data["pair"]
    alert_id = alert_data["id"]
    last_price = config.LATEST_PRICES.get(pair)

    while True:
        try:
            current_alert_state = db.get_alert_by_id(user_id, alert_id)
            if not current_alert_state or not current_alert_state["is_active"]:
                logger.info(f"Alert {alert_id} is no longer active. Stopping task.")
                stop_alarm_task(alert_id)
                break

            target_price = float(current_alert_state["price"])
            current_price = config.LATEST_PRICES.get(pair)

            if current_price:
                triggered, reason = False, ""

                if last_price is not None:
                    if last_price < target_price and current_price >= target_price:
                        triggered, reason = (
                            True,
                            f"📈 قیمت به بالای {target_price} رسید!",
                        )
                    elif last_price > target_price and current_price <= target_price:
                        triggered, reason = (
                            True,
                            f"📉 قیمت به پایین {target_price} رسید!",
                        )

                if triggered:
                    new_trigger_count = current_alert_state.get("trigger_count", 0) + 1
                    msg_text = AlertManager.format_trigger_message(
                        current_alert_state,
                        reason,
                        current_price,
                        new_trigger_count,
                    )
                    last_message_id = current_alert_state.get("last_message_id")
                    new_message = None

                    logger.info(
                        f"TRIGGERED (Price) -> Alert ID: {alert_id} for User: {user_id}. Reason: {reason}"
                    )

                    if last_message_id:
                        try:
                            await application.bot.edit_message_text(
                                chat_id=user_id,
                                message_id=last_message_id,
                                text=msg_text,
                            )
                            msg_logger.info(
                                f"OUTGOING (EDIT) -> User: {user_id}, Message ID: {last_message_id}"
                            )
                        except BadRequest as e:
                            if "message to edit not found" in e.message.lower():
                                new_message = await application.bot.send_message(
                                    user_id, msg_text
                                )
                                msg_logger.info(
                                    f"OUTGOING (SEND - after edit fail) -> User: {user_id}, New Message ID: {new_message.message_id}"
                                )
                            else:
                                raise e
                    else:
                        new_message = await application.bot.send_message(
                            user_id, msg_text
                        )
                        msg_logger.info(
                            f"OUTGOING (SEND) -> User: {user_id}, New Message ID: {new_message.message_id}"
                        )

                    message_id_to_save = (
                        new_message.message_id if new_message else last_message_id
                    )
                    db.update_alert_trigger_info(alert_id, message_id_to_save)

                last_price = current_price

            await asyncio.sleep(1)  # Check every second
        except Exception as e:
            logger.exception(
                f"UNEXPECTED ERROR in price_alert_monitor for alert {alert_id}:"
            )
            stop_alarm_task(alert_id)
            break
