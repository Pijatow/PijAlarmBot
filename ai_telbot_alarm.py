import logging
import asyncio
from typing import Dict, Any
import requests
import time
import os
import json  # Import json for pretty-printing API responses

# Import configurations and the new logging setup
import config
from ai_database_manager import DatabaseManager
from logging_config import logger, msg_logger, api_logger

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
)

# --- Proxy Settings for local tunneling ---
os.environ["http_proxy"] = "http://127.0.0.1:10808"
os.environ["https_proxy"] = "http://127.0.0.1:10808"


# --- Database Initialization ---
db = DatabaseManager(config.DB_FILE)

# --- Conversation States ---
(
    MAIN_MENU,
    VIEW_ALERT,
    VIEW_ALERT_DETAILS,
    DELETE_CONFIRMATION,
    DELETE_ALL_CONFIRMATION,
    ALERT_TYPE,
    PAIR_INPUT,
    TIMEFRAME_INPUT,
    PRICE_INPUT,
    CANDLE_SLOPE_INPUT,
    DESCRIPTION_INPUT,
) = range(11)


# --- Helper Functions ---
def translate_alert_type(alert_type):
    translations = {"alert_price": "قیمت", "alert_candle": "کندل"}
    return translations.get(alert_type, "ناشناخته")


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


# --- Alarm Task Management ---
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


# --- Alert Formatting ---
class AlertManager:
    @staticmethod
    def format_alert_details(alert_data: Dict[str, Any]) -> str:
        return f"""
💰 **جفت ارز:** #{alert_data.get('pair', 'N/A')}
📈 **نوع:** {translate_alert_type(alert_data.get('alert_type', 'N/A'))}
💵 **قیمت:** {alert_data.get('price', 'N/A')}
📜 **متن:** {alert_data.get('alert_description', 'بدون متن')}
"""

    @staticmethod
    def format_trigger_message(
        alert_data: Dict, trigger_reason: str, current_price: float, trigger_count: int
    ) -> str:
        return f"""
🔔 **آلارم فعال شد!** 🔔

{trigger_reason}

💰 **جفت ارز:** #{alert_data['pair']}
🎯 **قیمت هدف:** {alert_data['price']}
📈 **قیمت فعلی:** {current_price}
📜 **متن:** {alert_data['alert_description']}

🔄 **تعداد تکرار:** {trigger_count}
"""


# --- Background Monitors ---
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
                            alert_data, reason, current_price, new_trigger_count
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
                                    parse_mode="Markdown",
                                )
                                msg_logger.info(
                                    f"OUTGOING (EDIT) -> User: {user_id}, Message ID: {last_message_id}"
                                )
                            except BadRequest as e:
                                if "message to edit not found" in e.message.lower():
                                    new_message = await application.bot.send_message(
                                        user_id, msg_text, parse_mode="Markdown"
                                    )
                                    msg_logger.info(
                                        f"OUTGOING (SEND - after edit fail) -> User: {user_id}, New Message ID: {new_message.message_id}"
                                    )
                                else:
                                    raise e
                        else:
                            new_message = await application.bot.send_message(
                                user_id, msg_text, parse_mode="Markdown"
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


# --- Market Summary ---
async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg_logger.info(f"INCOMING -> User: {user_id}, Command: /summary")

    await update.message.reply_text("🔍 در حال دریافت خلاصه‌ای از بازار...")
    msg_logger.info(
        f"OUTGOING -> User: {user_id}, Text: 'در حال دریافت خلاصه‌ای از بازار...'"
    )

    url = f"{config.BITUNIX_API_URL}/futures/market/tickers"
    api_logger.info(f"REQUEST -> summary_command: URL={url}")
    try:
        response = requests.get(url, timeout=10)
        api_logger.info(f"RESPONSE -> summary_command: Status={response.status_code}")
        response.raise_for_status()

        # Log the raw response for debugging
        raw_data = response.json()
        api_logger.info(
            f"RAW JSON RESPONSE -> summary_command:\n{json.dumps(raw_data, indent=2)}"
        )

        all_tickers = raw_data.get("data", [])

        if not all_tickers:
            await update.message.reply_text(
                "❌ اطلاعاتی از بازار دریافت نشد (API response empty)."
            )
            msg_logger.warning(
                f"OUTGOING (FAIL) -> User: {user_id}, Reason: API response empty"
            )
            return

        usdt_pairs = [
            t
            for t in all_tickers
            if t.get("symbol", "").endswith("USDT") and t.get("turnover24h")
        ]
        api_logger.info(
            f"Filtered {len(usdt_pairs)} USDT pairs from {len(all_tickers)} total tickers."
        )

        usdt_pairs.sort(key=lambda x: float(x.get("turnover24h", 0)), reverse=True)

        top_10 = usdt_pairs[:10]

        if not top_10:
            await update.message.reply_text("❌ جفت‌ارزهای USDT برای نمایش یافت نشد.")
            msg_logger.warning(
                f"OUTGOING (FAIL) -> User: {user_id}, Reason: No USDT pairs found after filtering."
            )
            return

        message_lines = ["📈 **خلاصه قیمت ۱۰ ارز برتر (بر اساس حجم معاملات):**\n"]
        for pair in top_10:
            symbol = pair.get("symbol", "N/A").replace("USDT", "-USDT")
            price = float(pair.get("lastPrice", 0))
            message_lines.append(f"🔹 **{symbol}:** `{price:,.4f}`")

        final_message = "\n".join(message_lines)
        await update.message.reply_text(final_message, parse_mode="Markdown")
        msg_logger.info(f"OUTGOING (SUCCESS) -> User: {user_id}, Sent summary.")

    except requests.RequestException as e:
        api_logger.error(f"RESPONSE ERROR -> summary_command: {e}")
        await update.message.reply_text("❌ خطای شبکه در دریافت اطلاعات.")
    except Exception as e:
        logger.exception("UNEXPECTED ERROR in summary_command:")
        await update.message.reply_text("❌ یک خطای پیش‌بینی نشده رخ داد.")


# --- UI Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg_logger.info(
        f"INCOMING -> User: {user.id}, Command: /start or callback 'back_to_main'"
    )
    is_allowed = user.id in config.ALLOWED_USERS
    db.add_user(user.id, user.username, user.first_name, is_allowed)

    if not is_allowed:
        if update.message:
            await update.message.reply_text(
                "❌ شما اجازه استفاده از این ربات را ندارید."
            )
        msg_logger.warning(
            f"OUTGOING (REJECT) -> User: {user.id}, Reason: Not allowed."
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("🔔 ایجاد آلارم جدید", callback_data="new_alert")],
        [InlineKeyboardButton("📋 مشاهده آلارم‌ها", callback_data="view_alerts")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_msg = f"""🔔 خوش آمدید به **Crypto Alarm Bot**! 🎉
👋 سلام {user.first_name}!
📌 برای مشاهده قیمت ۱۰ ارز برتر از دستور /summary استفاده کنید.
👇🏼 یا یکی از گزینه‌های زیر را انتخاب کنید:"""

    if update.message:
        await update.message.reply_text(
            welcome_msg, reply_markup=reply_markup, parse_mode="Markdown"
        )
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            welcome_msg, reply_markup=reply_markup, parse_mode="Markdown"
        )

    msg_logger.info(f"OUTGOING -> User: {user.id}, Sent welcome message.")
    return MAIN_MENU


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    msg_logger.info(f"INCOMING (Callback) -> User: {user_id}, Data: {query.data}")
    await query.answer()

    if query.data == "new_alert":
        keyboard = [
            [InlineKeyboardButton("🔔 آلارم قیمت", callback_data="alert_price")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")],
        ]
        await query.edit_message_text(
            "🔔 نوع آلارم را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ALERT_TYPE

    elif query.data == "view_alerts":
        return await view_alerts_list(update, context)


async def view_alerts_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    alerts = db.get_user_alerts(user_id, ["id", "pair", "alert_type", "price"])

    if not alerts:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]]
        await query.edit_message_text(
            "📭 هیچ آلارم فعالی ندارید!", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MAIN_MENU

    keyboard = []
    for alert in alerts:
        btn_text = f"🔔 {alert['pair']} - {translate_alert_type(alert['alert_type'])} - {alert['price']}"
        keyboard.append(
            [InlineKeyboardButton(btn_text, callback_data=f"alert_{alert['id']}")]
        )
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")])
    await query.edit_message_text(
        f"📋 آلارم‌های فعال شما ({len(alerts)}):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return VIEW_ALERT


async def view_alert_details_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()
    alert_id = int(query.data.split("_")[1])
    user_id = query.from_user.id
    alert = db.get_alert_by_id(user_id, alert_id)

    if not alert:
        await query.edit_message_text("❌ آلارم یافت نشد.")
        return await view_alerts_list(update, context)

    context.user_data["selected_alert_id"] = alert_id
    keyboard = [
        [InlineKeyboardButton("🗑 حذف آلارم", callback_data=f"delete_{alert_id}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="view_alerts")],
    ]
    await query.edit_message_text(
        f"📋 **جزئیات آلارم:**\n{AlertManager.format_alert_details(alert)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return DELETE_CONFIRMATION


async def delete_confirmation_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()
    alert_id = int(query.data.split("_")[1])
    user_id = query.from_user.id

    alert_data = db.get_alert_by_id(user_id, alert_id)
    stop_alarm_task(alert_id)
    success, message = db.delete_user_alert(user_id, alert_id)

    if success:
        await query.edit_message_text(f"✅ {message}")
        if alert_data and alert_data.get("last_message_id"):
            try:
                await context.bot.delete_message(
                    chat_id=user_id, message_id=alert_data["last_message_id"]
                )
            except BadRequest:
                pass
    else:
        await query.edit_message_text(f"❌ {message}")

    query.data = "view_alerts"
    return await main_menu_handler(update, context)


async def alert_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["alert_type"] = query.data
    await query.edit_message_text("💰 لطفاً جفت ارز را وارد کنید (مثال: BTCUSDT):")
    return PAIR_INPUT


async def pair_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pair = update.message.text.upper().strip()
    if await is_valid_pair(pair):
        context.user_data["pair"] = pair
        await update.message.reply_text("💵 لطفاً قیمت مورد نظر را وارد کنید:")
        return PRICE_INPUT
    else:
        await update.message.reply_text(
            "❌ جفت ارز نامعتبر است. لطفاً دوباره تلاش کنید (مثال: BTCUSDT):"
        )
        return PAIR_INPUT


async def price_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
        context.user_data["price"] = price
        await update.message.reply_text("📜 لطفاً یک متن کوتاه برای آلارم وارد کنید:")
        return DESCRIPTION_INPUT
    except ValueError:
        await update.message.reply_text("❌ قیمت نامعتبر است. لطفاً یک عدد وارد کنید:")
        return PRICE_INPUT


async def save_alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["alert_description"] = update.message.text.strip()
    context.user_data["user_id"] = update.effective_user.id
    alert_id = db.save_alert(context.user_data)

    if alert_id:
        full_alert_data = db.get_alert_by_id(context.user_data["user_id"], alert_id)
        await start_alarm_task(context.application, full_alert_data)
        await update.message.reply_text(
            f"✅ آلارم با موفقیت ایجاد شد!\n\n{AlertManager.format_alert_details(context.user_data)}",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("❌ خطا در ذخیره آلارم. لطفاً دوباره تلاش کنید.")

    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ عملیات لغو شد.")
    context.user_data.clear()
    return ConversationHandler.END


# --- Post-Init Function for Persistence ---
async def post_init(application: Application):
    logger.info("--- Bot initialization complete ---")
    logger.info("--- Reloading active alarms from database ---")
    active_alerts = db.get_all_active_alerts()
    count = 0
    for alert in active_alerts:
        await start_alarm_task(application, alert)
        count += 1
    logger.info(f"--- Successfully reloaded {count} active alarms ---")


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        logger.critical("FATAL: TELEGRAM_BOT_TOKEN not found!")
        return

    application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(
                    main_menu_handler, pattern="^new_alert$|^view_alerts$"
                )
            ],
            VIEW_ALERT: [
                CallbackQueryHandler(view_alert_details_handler, pattern="^alert_")
            ],
            DELETE_CONFIRMATION: [
                CallbackQueryHandler(delete_confirmation_handler, pattern="^delete_")
            ],
            ALERT_TYPE: [
                CallbackQueryHandler(alert_type_handler, pattern="^alert_price$")
            ],
            PAIR_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pair_input_handler)
            ],
            PRICE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, price_input_handler)
            ],
            DESCRIPTION_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_alert_handler)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(start, pattern="^back_to_main$"),
            CommandHandler("cancel", cancel),
        ],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("summary", summary_command))

    logger.info("🟡 CryptoAlarmBot started successfully! Starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
