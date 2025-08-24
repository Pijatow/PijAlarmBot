import logging
import asyncio
from typing import Dict, Any
import requests
import time
import os

# Import configurations and DatabaseManager
import config
from ai_database_manager import DatabaseManager

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

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Proxy Settings for local tunneling ---
# Required for connectivity in specific regions via local proxy (e.g., v2ray).
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
    """Check if a trading pair is valid by querying the API."""
    try:
        response = requests.get(
            url=f"{config.BITUNIX_API_URL}/futures/market/tickers",
            params={"symbols": pair},
            timeout=5,
        )
        if response.status_code == 200 and response.json().get("data"):
            return True
        return False
    except requests.RequestException:
        return False


# --- Alarm Task Management ---
def stop_alarm_task(alert_id: int):
    """Stops a running background task for a given alert ID."""
    task = config.ACTIVE_ALARM_TASKS.pop(alert_id, None)
    if task:
        task.cancel()
        logger.info(f"Cancelled alarm task for alert_id: {alert_id}")


async def start_alarm_task(application: Application, alert_data: Dict[str, Any]):
    """Starts a background monitoring task for a given alert."""
    alert_id = alert_data.get("id")
    if not alert_id:
        return

    if alert_data["alert_type"] == "alert_price":
        task = asyncio.create_task(price_alarm_monitor(application, alert_data))
    elif alert_data["alert_type"] == "alert_candle":
        task = asyncio.create_task(candle_alarm_monitor(application, alert_data))
    else:
        return

    config.ACTIVE_ALARM_TASKS[alert_id] = task
    logger.info(f"Started alarm task for alert_id: {alert_id}")


# --- Alert Formatting ---
class AlertManager:
    @staticmethod
    def format_alert_details(alert_data: Dict[str, Any]) -> str:
        """Formats the full details of an alert for display."""
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
        """Formats the message sent when an alarm is triggered."""
        return f"""
🔔 **آلارم فعال شد!** 🔔

{trigger_reason}

💰 **جفت ارز:** #{alert_data['pair']}
🎯 **قیمت هدف:** {alert_data['price']}
📈 **قیمت فعلی:** {current_price}
📜 **متن:** {alert_data['alert_description']}

🔄 **تعداد تکرار:** {trigger_count}
"""


# --- Background Monitors (The Magic) ---
async def price_alarm_monitor(application: Application, alert_data: Dict[str, Any]):
    """Continuously monitors the price for a price-based alarm."""
    user_id = alert_data["user_id"]
    pair = alert_data["pair"]
    target_price = float(alert_data["price"])
    alert_id = alert_data["id"]
    last_price = None

    while True:
        try:
            # Re-fetch the latest alert data from DB in each loop
            # This ensures we have the latest message_id and trigger_count
            current_alert_state = db.get_alert_by_id(user_id, alert_id)
            if not current_alert_state or not current_alert_state["is_active"]:
                logger.info(f"Alert {alert_id} is no longer active. Stopping task.")
                stop_alarm_task(alert_id)
                break

            response = requests.get(
                f"{config.BITUNIX_API_URL}/futures/market/tickers",
                params={"symbols": pair},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json().get("data")
                if data:
                    current_price = float(data[0].get("lastPrice"))
                    triggered = False
                    reason = ""

                    if last_price is not None:
                        if last_price < target_price and current_price >= target_price:
                            triggered = True
                            reason = f"📈 قیمت به بالای {target_price} رسید!"
                        elif (
                            last_price > target_price and current_price <= target_price
                        ):
                            triggered = True
                            reason = f"📉 قیمت به پایین {target_price} رسید!"

                    if triggered:
                        new_trigger_count = (
                            current_alert_state.get("trigger_count", 0) + 1
                        )
                        msg_text = AlertManager.format_trigger_message(
                            alert_data, reason, current_price, new_trigger_count
                        )

                        last_message_id = current_alert_state.get("last_message_id")
                        new_message = None

                        if last_message_id:
                            try:
                                # Try to EDIT the last message
                                await application.bot.edit_message_text(
                                    chat_id=user_id,
                                    message_id=last_message_id,
                                    text=msg_text,
                                    parse_mode="Markdown",
                                )
                            except BadRequest as e:
                                # If editing fails (e.g., message deleted), send a new one
                                if "message to edit not found" in e.message.lower():
                                    new_message = await application.bot.send_message(
                                        user_id, msg_text, parse_mode="Markdown"
                                    )
                                else:
                                    raise e
                        else:
                            # If no previous message, SEND a new one
                            new_message = await application.bot.send_message(
                                user_id, msg_text, parse_mode="Markdown"
                            )

                        # If we sent a new message, get its ID. Otherwise, keep the old one.
                        message_id_to_save = (
                            new_message.message_id if new_message else last_message_id
                        )
                        db.update_alert_trigger_info(alert_id, message_id_to_save)

                    last_price = current_price

            await asyncio.sleep(15)  # Check every 15 seconds to avoid spamming edits
        except requests.RequestException as e:
            logger.error(f"Network error in price_alarm_monitor: {e}")
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(
                f"Unexpected error in price_alarm_monitor for alert {alert_id}: {e}"
            )
            stop_alarm_task(alert_id)
            break


async def candle_alarm_monitor(application: Application, alert_data: Dict[str, Any]):
    pass


# --- UI Handlers (Conversation Flow) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_allowed = user.id in config.ALLOWED_USERS
    db.add_user(user.id, user.username, user.first_name, is_allowed)

    if not is_allowed:
        if update.message:
            await update.message.reply_text(
                "❌ شما اجازه استفاده از این ربات را ندارید."
            )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("🔔 ایجاد آلارم جدید", callback_data="new_alert")],
        [InlineKeyboardButton("📋 مشاهده آلارم‌ها", callback_data="view_alerts")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_msg = f"""🔔 خوش آمدید به **Crypto Alarm Bot**! 🎉
👋 سلام {user.first_name}!
📌 لطفاً یکی از گزینه‌های زیر را انتخاب کنید:"""

    # Ensure we handle both message and callback_query updates correctly
    if update.message:
        await update.message.reply_text(
            welcome_msg, reply_markup=reply_markup, parse_mode="Markdown"
        )
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            welcome_msg, reply_markup=reply_markup, parse_mode="Markdown"
        )
    return MAIN_MENU


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "new_alert":
        keyboard = [
            [InlineKeyboardButton("🔔 آلارم قیمت", callback_data="alert_price")],
            [
                InlineKeyboardButton(
                    "🕯 آلارم کندل (غیرفعال)", callback_data="alert_candle_disabled"
                )
            ],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")],
        ]
        await query.edit_message_text(
            "🔔 نوع آلارم را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard),
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
        # Clean up by deleting the last alert message from the chat
        if alert_data and alert_data.get("last_message_id"):
            try:
                await context.bot.delete_message(
                    chat_id=user_id, message_id=alert_data["last_message_id"]
                )
            except BadRequest:
                pass  # Ignore if message is already deleted
    else:
        await query.edit_message_text(f"❌ {message}")

    query.data = "view_alerts"
    return await view_alerts_list(update, context)


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


async def post_init(application: Application):
    logger.info("--- Reloading active alarms from database ---")
    active_alerts = db.get_all_active_alerts()
    count = 0
    for alert in active_alerts:
        await start_alarm_task(application, alert)
        count += 1
    logger.info(f"--- Successfully reloaded {count} active alarms ---")


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment or config!")
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
    logger.info("🟡 CryptoAlarmBot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
