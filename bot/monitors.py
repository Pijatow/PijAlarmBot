import asyncio
from typing import Dict, Any

import requests
from telegram.ext import Application
from telegram.error import BadRequest

import config
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

    if alert_data["alert_type"] == "alert_price":
        task = asyncio.create_task(price_alarm_monitor(application, alert_data))
    else:
        logger.warning(
            f"Unsupported alert_type for task start: {alert_data['alert_type']}"
        )
        return

    config.ACTIVE_ALARM_TASKS[alert_id] = task
    logger.info(f"Started alarm task for alert_id: {alert_id}")


async def price_alarm_monitor(application: Application, alert_data: Dict[str, Any]):
    user_id = alert_data["user_id"]
    pair = alert_data["pair"]
    target_price = float(alert_data["price"])
    alert_id = alert_data["id"]
    last_price = None

    url = f"{config.BITUNIX_API_URL}/futures/market/tickers"
    params = {"symbols": pair}

    while True:
        try:
            current_alert_state = db.get_alert_by_id(user_id, alert_id)
            if not current_alert_state or not current_alert_state["is_active"]:
                logger.info(f"Alert {alert_id} is no longer active. Stopping task.")
                stop_alarm_task(alert_id)
                break

            target_price = float(current_alert_state["price"])

            api_logger.info(
                f"REQUEST -> price_alarm_monitor (Alert ID: {alert_id}): URL={url}, Params={params}"
            )
            response = requests.get(url, params=params, timeout=10)
            api_logger.info(
                f"RESPONSE -> price_alarm_monitor (Alert ID: {alert_id}): Status={response.status_code}"
            )

            if response.status_code == 200:
                data = response.json().get("data")
                if data:
                    current_price = float(data[0].get("lastPrice"))
                    triggered, reason = False, ""

                    if last_price is not None:
                        if last_price < target_price and current_price >= target_price:
                            triggered, reason = (
                                True,
                                f"📈 قیمت به بالای {target_price} رسید!",
                            )
                        elif (
                            last_price > target_price and current_price <= target_price
                        ):
                            triggered, reason = (
                                True,
                                f"📉 قیمت به پایین {target_price} رسید!",
                            )

                    if triggered:
                        new_trigger_count = (
                            current_alert_state.get("trigger_count", 0) + 1
                        )
                        msg_text = AlertManager.format_trigger_message(
                            current_alert_state,
                            reason,
                            current_price,
                            new_trigger_count,
                        )
                        last_message_id = current_alert_state.get("last_message_id")
                        new_message = None

                        logger.info(
                            f"TRIGGERED -> Alert ID: {alert_id} for User: {user_id}. Reason: {reason}"
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

            await asyncio.sleep(15)
        except requests.RequestException as e:
            api_logger.error(
                f"RESPONSE ERROR -> price_alarm_monitor (Alert ID: {alert_id}): {e}"
            )
            await asyncio.sleep(60)
        except Exception as e:
            logger.exception(
                f"UNEXPECTED ERROR in price_alarm_monitor for alert {alert_id}:"
            )
            stop_alarm_task(alert_id)
            break
