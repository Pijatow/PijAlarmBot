import os
import logging
import asyncio
from typing import Dict, Any
from requests import get
import time
from datetime import datetime
from datetime import timezone, timedelta
from dotenv import load_dotenv

from copy import copy


import telegram
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
)

from ai_database_manager import DatabaseManager

# Proxy settings removed for Replit environment

os.environ["http_proxy"] = "http://127.0.0.1:10808"
os.environ["https_proxy"] = "http://127.0.0.1:10808"

BITUNIX = "https://fapi.bitunix.com/api/v1/"

# Load environment variables
load_dotenv()

# Configuration
ADMIN_ID = 79795657
ALLOWED_USERS = [ADMIN_ID, 79795657]
BITUNIX_API = "https://fapi.bitunix.com/api/v1/"
DB_FILE = "alerts.db"
# DB_FILE = ":memory:"
TIMEZONE = timezone(timedelta(hours=3, minutes=30))  # Asia/Tehran timezone

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


db = DatabaseManager(DB_FILE, ALLOWED_USERS)


def translate_alert_type(alert_type):
    if alert_type == "alert_price":
        return "قیمت"
    elif alert_type == "alert_candle":
        return "کندل"


class AlertManager:
    @staticmethod
    def format_alert_message(alert_data: Dict[str, Any]) -> str:
        now = datetime.now(TIMEZONE)

        message = f"""
💰 جفت ارز: #{alert_data['pair']}
📈 نوع: {translate_alert_type(alert_data['alert_type'])}
💵 قیمت: {alert_data['price']}
⏳ تایم فریم: {alert_data['timeframe']}
🕰 تاریخ: {now.strftime('%Y/%m/%d - %H:%M')}
📜 متن: {alert_data['alert_description']}
"""

        return message

    @staticmethod
    def candle_trigger_message(user_data: Dict):
        raw = "🔔 آلارم کندل فعال شد! 🔔"
        msg = f"""
{raw}\n
💰 جفت ارز: #{user_data['pair']}\n
📈 نوع آلارم: {translate_alert_type(user_data['alert_type'])}\n
💵 قیمت: {user_data['price']}\n
📉 شیب تغییر: {user_data['candle_slope']}
⏳ تایم فریم: {user_data['timeframe']}\n
📜 متن: {user_data['alert_description']}\n
"""
        return msg

    @staticmethod
    def price_trigger_message(user_data: Dict, previous_price: float, price: float):
        if previous_price < price:
            raw = f"📈 قیمت بالای {user_data['price']} رسید! 🔔\n"
        elif previous_price > price:
            raw = f"📉 قیمت پایین {user_data['price']} رسید! 🔔\n"
        msg = f"""
{raw}\n
💰 جفت ارز: #{user_data['pair']}\n
📈 نوع آلارم: {translate_alert_type(user_data['alert_type'])}\n
🎯 قیمت هدف: {user_data['price']}\n
⏳ تایم فریم: {user_data['timeframe']}\n
📜 متن: {user_data['alert_description']}\n
"""
        return msg


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # Add user to database
    db.add_user(user_id, user.username, user.first_name)

    # Clear any existing user data
    context.user_data.clear()

    keyboard = [
        [InlineKeyboardButton("🔔 ایجاد آلارم جدید", callback_data="new_alert")],
        [InlineKeyboardButton("📋 مشاهده آلارم‌ها", callback_data="view_alerts")],
        [InlineKeyboardButton("🗑 حذف همه آلارم‌ها", callback_data="delete_all_alerts")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_msg = f"""🔔 خوش آمدید به MbtcAlarmBot! 🎉
👋 سلام {user.first_name}!
📌 لطفاً یکی از گزینه‌های زیر را انتخاب کنید:"""

    await update.effective_chat.send_message(welcome_msg, reply_markup=reply_markup)
    return MAIN_MENU


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "new_alert":
        keyboard = [
            [InlineKeyboardButton("🔔 آلارم قیمت", callback_data="alert_price")],
            [
                InlineKeyboardButton(
                    "🕯 آلارم بسته شدن کندل", callback_data="alert_candle"
                )
            ],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🔔 نوع آلارم را انتخاب کنید: 📌", reply_markup=reply_markup
        )
        return ALERT_TYPE

    elif query.data == "view_alerts":
        fields = ["id", "pair", "alert_type", "price", "timeframe"]
        alerts = db.get_user_alerts(user_id, fields)

        if not alerts:
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "📭 هیچ آلارم فعالی ندارید! 😕", reply_markup=reply_markup
            )
            return MAIN_MENU

        keyboard = []
        alert_text = f"📋 آلارم‌های فعال شما ({len(alerts)} آلارم):\n\n"

        for alert in alerts:
            alert_type_fa = translate_alert_type(alert["alert_type"])
            btn_text = f"🔔 {alert['pair']} - {alert_type_fa} - {alert['price']}"
            keyboard.append(
                [InlineKeyboardButton(btn_text, callback_data=f"alert_{alert['id']}")]
            )

        keyboard.append(
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
        )
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(alert_text, reply_markup=reply_markup)
        return VIEW_ALERT

    elif query.data == "delete_all_alerts":
        # Check if user has any alerts
        alert_count = db.get_alert_count(user_id)

        if alert_count == 0:
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "📭 هیچ آلارم فعالی برای حذف ندارید! 😕", reply_markup=reply_markup
            )
            return MAIN_MENU

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ تایید حذف همه", callback_data="confirm_delete_all"
                )
            ],
            [InlineKeyboardButton("❌ لغو", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"⚠️ آیا از حذف همه آلارم‌های فعال ({alert_count} آلارم) اطمینان دارید؟\n\n"
            "این عمل قابل بازگشت نیست!",
            reply_markup=reply_markup,
        )
        return DELETE_ALL_CONFIRMATION

    elif query.data == "back_to_main":
        return await start(update, context)

    elif query.data == "confirm_delete_all":
        success, message, deleted_count = db.delete_all_user_alerts(user_id)

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔙 بازگشت به منو اصلی", callback_data="back_to_main"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if success:
            await query.edit_message_text(
                f"✅ {message}\n\n🔄 برای ایجاد آلارم جدید به منو اصلی بروید.",
                reply_markup=reply_markup,
            )
        else:
            await query.edit_message_text(
                f"❌ خطا در حذف آلارم‌ها: {message}", reply_markup=reply_markup
            )

        return MAIN_MENU


async def view_alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Extract alert ID from callback data
    alert_id_str = query.data.replace("alert_", "")

    try:
        alert_id = int(alert_id_str)
    except ValueError:
        await query.edit_message_text("❌ شناسه آلارم نامعتبر است!")
        return ConversationHandler.END

    # Get alert details
    alert = db.get_alert_by_id(query.from_user.id, alert_id)

    if not alert:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="view_alerts")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "❌ آلارم یافت نشد یا حذف شده است.", reply_markup=reply_markup
        )
        return VIEW_ALERT

    # Store alert ID for later use
    context.user_data["selected_alert_id"] = alert_id
    context.user_data["selected_alert"] = alert

    # Create action buttons
    keyboard = [
        [InlineKeyboardButton("🗑 حذف آلارم", callback_data="delete_single_alert")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="view_alerts")],
        [InlineKeyboardButton("🏠 منو اصلی", callback_data="back_to_main")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Format and display alert details
    alert_message = AlertManager.format_alert_message(alert)
    full_message = f"📋 جزئیات آلارم (ID: {alert_id}):\n{alert_message}"

    await query.edit_message_text(full_message, reply_markup=reply_markup)
    return VIEW_ALERT_DETAILS


async def view_alert_details_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if query.data == "delete_single_alert":
        alert_id = context.user_data.get("selected_alert_id")
        alert = context.user_data.get("selected_alert")

        if not alert_id or not alert:
            await query.edit_message_text("❌ خطا در بازیابی اطلاعات آلارم.")
            return ConversationHandler.END

        # Show confirmation dialog
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ تایید حذف", callback_data="confirm_delete_single"
                )
            ],
            [InlineKeyboardButton("❌ لغو", callback_data=f"alert_{alert_id}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        alert_summary = f"{alert['pair']} - {translate_alert_type(alert['alert_type'])} - {alert['price']}"
        await query.edit_message_text(
            f"⚠️ آیا از حذف این آلارم اطمینان دارید؟\n\n"
            f"🔔 {alert_summary}\n\n"
            f"این عمل قابل بازگشت نیست!",
            reply_markup=reply_markup,
        )
        return DELETE_CONFIRMATION

    elif query.data == "view_alerts":
        return await main_menu_handler(update, context)

    elif query.data == "back_to_main":
        return await start(update, context)


async def delete_confirmation_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_delete_single":
        alert_id = context.user_data.get("selected_alert_id")
        user_id = query.from_user.id

        if not alert_id:
            await query.edit_message_text("❌ خطا در بازیابی شناسه آلارم.")
            return ConversationHandler.END

        # Perform the delete operation
        success, message = db.delete_user_alert(user_id, alert_id)

        keyboard = [
            [
                InlineKeyboardButton(
                    "📋 مشاهده آلارم‌های باقی‌مانده", callback_data="view_alerts"
                )
            ],
            [InlineKeyboardButton("🏠 منو اصلی", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if success:
            # Clear stored data
            context.user_data.pop("selected_alert_id", None)
            context.user_data.pop("selected_alert", None)

            await query.edit_message_text(
                f"✅ {message}\n\n🔄 آلارم با موفقیت حذف شد!", reply_markup=reply_markup
            )
        else:
            await query.edit_message_text(
                f"❌ خطا در حذف آلارم: {message}", reply_markup=reply_markup
            )

        return MAIN_MENU

    else:
        # User cancelled, go back to alert details
        alert_id = context.user_data.get("selected_alert_id")
        if alert_id:
            # Simulate clicking on the alert again
            query.data = f"alert_{alert_id}"
            return await view_alert_handler(update, context)
        else:
            return await main_menu_handler(update, context)


async def alert_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_main":
        return await start(update, context)

    context.user_data["alert_type"] = query.data

    await query.edit_message_text("💰 جفت ارز را وارد کنید (مثال: BTCUSDT): 📝")
    return PAIR_INPUT


async def pair_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pair = update.message.text.upper().strip()
    context.user_data["pair"] = pair

    keyboard = [
        [
            InlineKeyboardButton("1m", callback_data="1"),
            InlineKeyboardButton("5m", callback_data="5"),
        ],
        [
            InlineKeyboardButton("15m", callback_data="15"),
            InlineKeyboardButton("30m", callback_data="30"),
        ],
        [
            InlineKeyboardButton("1H", callback_data="60"),
            InlineKeyboardButton("4H", callback_data="240"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"⏳ تایم فریم را برای {pair} انتخاب کنید: 📌", reply_markup=reply_markup
    )
    return TIMEFRAME_INPUT


async def timeframe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["timeframe"] = query.data

    await query.edit_message_text("💵 قیمت آلارم را وارد کنید: 📝")
    return PRICE_INPUT


async def price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.lower().strip())
        context.user_data["price"] = price
    except ValueError:
        await update.message.reply_text("❌ لطفاً قیمت معتبر وارد کنید (فقط عدد):")
        return PRICE_INPUT

    if context.user_data["alert_type"] == "alert_candle":
        keyboard = [
            [
                InlineKeyboardButton("افزایشی", callback_data="incremental"),
                InlineKeyboardButton("کاهشی", callback_data="decremental"),
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📉 نوع شیب قیمت:", reply_markup=reply_markup)
        return CANDLE_SLOPE_INPUT

    await update.effective_sender.send_message("📜 متن آلارم را وارد کنید: 📝")
    return SAVE


async def candle_slope_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["candle_slope"] = query.data

    await update.effective_sender.send_message("📜 متن آلارم را وارد کنید: 📝")
    return SAVE


async def add_price_alarm_to_background(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    data = copy(context.user_data)
    interval = int(data["timeframe"])
    target = float(data["price"])
    previous_price = -1
    while True:
        for i in range(12):  # check price 12 times per minute(every 5 seconds)60/12=5
            reached = 0
            try:
                response = get(
                    url=(BITUNIX + "futures/market/tickers"),
                    params={"symbols": data["pair"]},
                    timeout=10,
                )
                price_data = response.json().get("data")
                if not price_data:
                    await asyncio.sleep(5)
                    continue

                price = float(price_data[0].get("lastPrice"))

                if previous_price != -1:
                    if (
                        previous_price < price
                        and previous_price < target
                        and price >= target
                    ):
                        msg = AlertManager().price_trigger_message(
                            data, previous_price, price
                        )
                        print(f"\n\nprice_alarm \t\t {previous_price} -> {price}\n\n")
                        await update.effective_sender.send_message(text=msg)
                        reached += 1
                    elif (
                        previous_price > price
                        and previous_price > target
                        and price <= target
                    ):
                        msg = AlertManager().price_trigger_message(
                            data, previous_price, price
                        )
                        print(f"\n\nprice_alarm \t\t {previous_price} -> {price}\n\n")
                        await update.effective_sender.send_message(text=msg)
                        reached += 1
                    else:
                        print(f"\n\nprice_alarm \t\t {previous_price} -> {price}\n\n")
                previous_price = price
            except Exception as e:
                logger.error(f"Error in price alarm background task: {e}")

            await asyncio.sleep(5)


async def add_kandle_alarm_to_background(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    data = copy(context.user_data)
    kandle_interval_choices = {
        1: "1min",
        3: "3min",
        5: "5min",
        15: "15min",
        30: "30min",
        60: "60min",
        120: "2h",
        240: "4h",
        360: "6h",
    }
    interval = int(data["timeframe"])
    candle_slope = data["candle_slope"]
    target = float(data["price"])
    current_unix_timestamp = int(time.time() * 1000)
    start_time_unix_timestamp = current_unix_timestamp - interval * 60 * 1000
    reached = False
    previous_price = -1

    while not reached:
        try:
            response = get(
                url=(BITUNIX + "futures/market/kline"),
                params={
                    "symbol": data["pair"],
                    "startTime": start_time_unix_timestamp,
                    "endTime": current_unix_timestamp,
                    "interval": kandle_interval_choices.get(interval),
                },
                timeout=10,
            )

            kline_data = response.json().get("data")
            if not kline_data:
                await asyncio.sleep(interval * 60)
                continue

            kandle_closing_price = float(kline_data[0].get("close"))

            msg = AlertManager().candle_trigger_message(data)
            if previous_price != -1:
                if (
                    candle_slope == "incremental"
                    and previous_price < kandle_closing_price >= target
                ):
                    await update.effective_sender.send_message(text=msg)
                    reached = True
                elif (
                    candle_slope == "decremental"
                    and previous_price > kandle_closing_price <= target
                ):
                    await update.effective_sender.send_message(text=msg)
                    reached = True
            previous_price = kandle_closing_price
        except Exception as e:
            logger.error(f"Error in candle alarm background task: {e}")

        await asyncio.sleep(interval * 60)


async def save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    alert_description = update.message.text.strip()
    context.user_data["alert_description"] = alert_description

    # Save alert to database
    alert_data = {
        "user_id": update.effective_user.id,
        "alert_description": context.user_data["alert_description"],
        "alert_type": context.user_data["alert_type"],
        "pair": context.user_data["pair"],
        "timeframe": context.user_data["timeframe"],
        "price": context.user_data["price"],
    }

    try:
        db.save_alert(alert_data)

        # Format and send alert message
        alert_message = AlertManager.format_alert_message(alert_data)
        await update.message.reply_text(alert_message, parse_mode="HTML")

        await update.message.reply_text(
            "✅ آلارم با موفقیت ایجاد شد! 🎉\n"
            "🔔 برای ایجاد آلارم جدید دستور /start را بزنید."
        )

        if context.user_data["alert_type"] == "alert_candle":
            task = asyncio.create_task(add_kandle_alarm_to_background(update, context))
            await update.effective_sender.send_message(
                "🔔 آلارم به سیستم اضافه شد و در حال اجراست! 🚀"
            )
        elif context.user_data["alert_type"] == "alert_price":
            task = asyncio.create_task(add_price_alarm_to_background(update, context))
            await update.effective_sender.send_message(
                "🔔 آلارم به سیستم اضافه شد و در حال اجراست! 🚀"
            )

    except Exception as e:
        logger.error(f"Error saving alert: {e}")
        await update.message.reply_text("❌ خطا در ذخیره آلارم! لطفاً دوباره تلاش کنید.")

    finally:
        context.user_data.clear()

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ عملیات لغو شد! 😔")
    context.user_data.clear()
    return ConversationHandler.END


# Admin commands
async def add_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ دسترسی برای این کار ندارید! 😔")
        return

    if not context.args:
        await update.message.reply_text("📋 استفاده: /adduser <شناسه کاربر>")
        return

    try:
        user_id = int(context.args[0])
        ALLOWED_USERS.append(user_id)
        await update.message.reply_text(f"✅ کاربر {user_id} با موفقیت اضافه شد! 🎉")
    except ValueError:
        await update.message.reply_text("❌ شناسه کاربر نامعتبر است! 😕")


async def remove_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ دسترسی برای این کار ندارید! 😔")
        return

    if not context.args:
        await update.message.reply_text("📋 استفاده: /removeuser <شناسه کاربر>")
        return

    try:
        user_id = int(context.args[0])
        if user_id in ALLOWED_USERS and user_id != ADMIN_ID:
            ALLOWED_USERS.remove(user_id)
            await update.message.reply_text(f"✅ کاربر {user_id} با موفقیت حذف شد! 🎉")
        else:
            await update.message.reply_text("❌ کاربر یافت نشد یا قابل حذف نیست! 😕")
    except ValueError:
        await update.message.reply_text("❌ شناسه کاربر نامعتبر است! 😕")


if __name__ == "__main__":
    # Get bot token from environment
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables!")
        exit()

    # Create application
    application = ApplicationBuilder().token(token).build()

    # Conversation states
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
        SAVE,
    ) = range(11)

    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(main_menu_handler)],
            VIEW_ALERT: [CallbackQueryHandler(view_alert_handler)],
            VIEW_ALERT_DETAILS: [CallbackQueryHandler(view_alert_details_handler)],
            DELETE_CONFIRMATION: [CallbackQueryHandler(delete_confirmation_handler)],
            DELETE_ALL_CONFIRMATION: [CallbackQueryHandler(main_menu_handler)],
            ALERT_TYPE: [CallbackQueryHandler(alert_type_handler)],
            PAIR_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pair_input_handler)
            ],
            TIMEFRAME_INPUT: [CallbackQueryHandler(timeframe_handler)],
            PRICE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, price_handler)
            ],
            CANDLE_SLOPE_INPUT: [CallbackQueryHandler(candle_slope_handler)],
            SAVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # Add handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("adduser", add_user_cmd))
    application.add_handler(CommandHandler("removeuser", remove_user_cmd))

    logger.info("🟡 MbtcAlarmBot started successfully!")

    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except telegram.error.NetworkError:
        print("connection failed!")
