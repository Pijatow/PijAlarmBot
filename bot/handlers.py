import asyncio
from textwrap import dedent

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, NetworkError
from telegram.ext import ContextTypes, ConversationHandler

import config
from bot.monitors import stop_alarm_task, start_alarm_task
from bot.ui import AlertManager
from bot.utils import translate_alert_type, is_valid_pair, parse_duration
from .constants import *
from database_manager import DatabaseManager
from logging_config import msg_logger, api_logger, logger


db = DatabaseManager(config.DB_FILE)


# --- Safe Message Sending Wrappers ---
async def send_message(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs
):
    """A wrapper to safely send messages, handling potential NetworkErrors."""
    try:
        message = await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return message
    except NetworkError as e:
        logger.error(f"Failed to send message to {chat_id} due to network error: {e}")
        return None


async def edit_message(query_or_msg, text: str, **kwargs):
    """A wrapper to safely edit messages, handling common errors."""
    try:
        # Check if it's a callback_query or a message object
        if hasattr(query_or_msg, "edit_message_text"):
            await query_or_msg.edit_message_text(text=text, **kwargs)
        else:  # Assumed to be a message object from a reply
            await query_or_msg.edit_text(text=text, **kwargs)
        return True
    except NetworkError as e:
        logger.error(f"Failed to edit message due to network error: {e}")
        return False
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.warning(f"Attempted to edit message with the same content: {e}")
        else:
            logger.error(f"Failed to edit message due to a bad request: {e}")
        return False


# --- Reminder Command ---
async def _send_reminder(
    update: Update, context: ContextTypes.DEFAULT_TYPE, seconds: int, message: str
):
    """Waits for a specified duration and then sends the reminder message."""
    await asyncio.sleep(seconds)
    await send_message(context, update.effective_chat.id, f"⏰ یادآوری:\n\n{message}")
    msg_logger.info(
        f"OUTGOING (Reminder) -> User: {update.effective_user.id}, Message: {message}"
    )


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets a reminder for the user."""
    user_id = update.effective_user.id
    msg_logger.info(f"INCOMING -> User: {user_id}, Command: /remind")

    if len(context.args) < 2:
        await send_message(
            context,
            user_id,
            "دستور استفاده: /remind <زمان> <پیام>\n\n"
            "مثال: /remind 1h30m چک کردن فر\n"
            "واحد های زمانی: h (ساعت)، m (دقیقه)، s (ثانیه)",
        )
        return

    duration_str = context.args[0]
    reminder_message = " ".join(context.args[1:])
    seconds = parse_duration(duration_str)

    if seconds <= 0:
        await send_message(
            context,
            user_id,
            "فرمت زمان وارد شده معتبر نیست.\n\n"
            "مثال: /remind 1h30m چک کردن فر\n"
            "واحد های زمانی: h (ساعت)، m (دقیقه)، s (ثانیه)",
        )
        return

    asyncio.create_task(_send_reminder(update, context, seconds, reminder_message))
    await send_message(
        context, user_id, f"✅ ثبت شد! تا {duration_str} دیگر به شما یادآوری می‌شود."
    )
    msg_logger.info(
        f"SET Reminder -> User: {user_id}, Duration: {seconds}s, Message: {reminder_message}"
    )


# --- General Commands ---
async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg_logger.info(f"INCOMING -> User: {user_id}, Command: /summary")

    loading_message = await send_message(
        context, user_id, "🔍 در حال دریافت قیمت‌های درخواستی..."
    )
    if not loading_message:
        return

    target_symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "XRPUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "DOGEUSDT",
        "TRXUSDT",
        "ADAUSDT",
        "AVAXUSDT",
        "BCHUSDT",
        "LINKUSDT",
        "USDCUSDT",
    ]
    symbols_param = ",".join(target_symbols)
    url = f"{config.BITUNIX_API_URL}/futures/market/tickers"
    params = {"symbols": symbols_param}

    try:
        api_response = await asyncio.to_thread(
            requests.get, url, params=params, timeout=10
        )
        api_response.raise_for_status()
        tickers_data = api_response.json().get("data", [])

        if not tickers_data:
            await edit_message(
                loading_message, "❌ اطلاعاتی از بازار دریافت نشد (API response empty)."
            )
            return

        price_map = {ticker["symbol"]: ticker for ticker in tickers_data}
        message_lines = ["📈 خلاصه قیمت ارزهای درخواستی:\n"]
        for symbol in target_symbols:
            display_symbol = symbol.replace("USDT", "-USDT")
            if symbol in price_map:
                price = float(price_map[symbol].get("lastPrice", 0))
                formatted_price = f"{price:,.4f}"
                message_lines.append(f"🔹 {display_symbol}: {formatted_price}")
            else:
                message_lines.append(f"🔸 {display_symbol}: (N/A)")

        final_message = "\n".join(message_lines)
        await edit_message(loading_message, final_message)
        msg_logger.info(f"OUTGOING (EDIT) -> User: {user_id}, Sent custom summary.")

    except requests.RequestException as e:
        logger.error(f"Network error during summary fetch: {e}")
        await edit_message(loading_message, "❌ خطای شبکه در دریافت اطلاعات.")
    except Exception as e:
        logger.exception("UNEXPECTED ERROR in summary_command:")
        await edit_message(loading_message, "❌ یک خطای پیش‌بینی نشده رخ داد.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg_logger.info(f"INCOMING -> User: {user_id}, Command: /help")
    help_text = dedent(
        """
        🆘 راهنمای ربات Crypto Alarm Bot

        در اینجا لیستی از تمام دستورات و ویژگی‌های موجود آمده است:

        دستورات اصلی:
        /start - نمایش منوی اصلی و شروع کار با ربات
        /help - نمایش همین پیام راهنما

        دستورات سریع:
        /new_alarm - شروع فرآیند ایجاد یک آلارم جدید
        /list_alarms - نمایش تمام آلارم‌های فعال شما
        /summary - نمایش قیمت لحظه‌ای ارزهای منتخب
        /remind <زمان> <پیام> - تنظیم یک یادآوری ساده (مثال: /remind 1h30m پیام تست)

        در طول فرآیندها:
        /cancel - لغو عملیات فعلی (مانند ساخت آلارم)
    """
    )
    await send_message(context, user_id, help_text)
    msg_logger.info(f"OUTGOING -> User: {user_id}, Sent help message.")


# --- Main Conversation Flow ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg_logger.info(
        f"INCOMING -> User: {user.id}, Command: /start or callback 'back_to_main'"
    )
    is_allowed = user.id in config.ALLOWED_USERS
    db.add_user(user.id, user.username, user.first_name, is_allowed)

    if not is_allowed:
        await send_message(
            context, user.id, "❌ شما اجازه استفاده از این ربات را ندارید."
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("🔔 ایجاد آلارم جدید", callback_data="new_alert")],
        [InlineKeyboardButton("📋 مشاهده آلارم‌ها", callback_data="view_alerts")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_msg = dedent(
        f"""
        🔔 خوش آمدید به Crypto Alarm Bot! 🎉
        👋 سلام {user.first_name}!

        برای شروع از دکمه‌ها استفاده کنید یا از دستورات سریع زیر کمک بگیرید:
        /new_alarm - ساخت آلارم جدید
        /list_alarms - مشاهده آلارم‌ها
        /summary - قیمت لحظه‌ای ارزها
        /help - راهنما
    """
    )

    if update.message:
        await send_message(context, user.id, welcome_msg, reply_markup=reply_markup)
    elif update.callback_query:
        await edit_message(
            update.callback_query, welcome_msg, reply_markup=reply_markup
        )
    msg_logger.info(f"OUTGOING -> User: {user.id}, Sent welcome message.")
    return MAIN_MENU


async def new_alarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg_logger.info(f"INCOMING -> User: {user_id}, Command: /new_alarm")
    keyboard = [
        [InlineKeyboardButton("🔔 آلارم قیمت", callback_data="alert_price")],
        [InlineKeyboardButton("📈 آلارم RSI", callback_data="alert_rsi")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")],
    ]
    await send_message(
        context,
        user_id,
        "🔔 نوع آلارم را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ALERT_TYPE


async def list_alarms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg_logger.info(f"INCOMING -> User: {user_id}, Command: /list_alarms")
    alerts = db.get_user_alerts(
        user_id, ["id", "pair", "alert_type", "price", "rsi_threshold"]
    )

    if not alerts:
        await send_message(context, user_id, "📭 هیچ آلارم فعالی ندارید!")
        return ConversationHandler.END

    keyboard = []
    for alert in alerts:
        if alert["alert_type"] == "alert_rsi":
            value = f"RSI {alert['rsi_threshold']}"
        else:
            value = alert["price"]
        btn_text = f"🔔 {alert['pair']} - {translate_alert_type(alert['alert_type'])} - {value}"
        keyboard.append(
            [InlineKeyboardButton(btn_text, callback_data=f"alert_{alert['id']}")]
        )
    await send_message(
        context,
        user_id,
        f"📋 آلارم‌های فعال شما ({len(alerts)}):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return VIEW_ALERT


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    msg_logger.info(f"INCOMING (Callback) -> User: {user_id}, Data: {query.data}")
    await query.answer()

    if query.data == "new_alert":
        keyboard = [
            [InlineKeyboardButton("🔔 آلارم قیمت", callback_data="alert_price")],
            [InlineKeyboardButton("📈 آلارم RSI", callback_data="alert_rsi")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")],
        ]
        await edit_message(
            query,
            "🔔 نوع آلارم را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ALERT_TYPE
    elif query.data == "view_alerts":
        alerts = db.get_user_alerts(
            user_id, ["id", "pair", "alert_type", "price", "rsi_threshold"]
        )
        if not alerts:
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
            ]
            await edit_message(
                query,
                "📭 هیچ آلارم فعالی ندارید!",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return MAIN_MENU

        keyboard = []
        for alert in alerts:
            if alert["alert_type"] == "alert_rsi":
                value = f"RSI {alert['rsi_threshold']}"
            else:
                value = alert["price"]
            btn_text = f"🔔 {alert['pair']} - {translate_alert_type(alert['alert_type'])} - {value}"
            keyboard.append(
                [InlineKeyboardButton(btn_text, callback_data=f"alert_{alert['id']}")]
            )
        keyboard.append(
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
        )
        await edit_message(
            query,
            f"📋 آلارم‌های فعال شما ({len(alerts)}):",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return VIEW_ALERT


async def view_alert_details_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    alert_id = int(query.data.split("_")[-1])
    context.user_data["selected_alert_id"] = alert_id
    user_id = query.from_user.id
    alert = db.get_alert_by_id(user_id, alert_id)

    if not alert:
        await edit_message(query, "❌ آلارم یافت نشد.")
        return MAIN_MENU

    keyboard = [
        [InlineKeyboardButton("🗑 حذف", callback_data=f"delete_{alert_id}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="view_alerts")],
    ]
    message_text = f"📋 جزئیات آلارم:\n{AlertManager.format_alert_details(alert)}"
    await edit_message(
        query, text=message_text, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return VIEW_ALERT_DETAILS


async def delete_confirmation_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()
    alert_id = int(query.data.split("_")[-1])
    user_id = query.from_user.id

    alert_data = db.get_alert_by_id(user_id, alert_id)
    stop_alarm_task(alert_id)
    success, message = db.delete_user_alert(user_id, alert_id)

    await edit_message(query, message)

    if success and alert_data and alert_data.get("last_message_id"):
        try:
            await context.bot.delete_message(
                chat_id=user_id, message_id=alert_data["last_message_id"]
            )
        except (BadRequest, NetworkError) as e:
            logger.warning(
                f"Could not delete trigger message {alert_data['last_message_id']}: {e}"
            )

    await start(update, context)  # This will implicitly handle MAIN_MENU return
    return ConversationHandler.END


# --- Alert Creation Conversation ---
async def alert_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["alert_type"] = query.data

    if query.data == "alert_rsi":
        await edit_message(
            query, "📈 لطفاً تایم فریم را وارد کنید (مثال: 1m, 5m, 1h, 4h, 1d):"
        )
        return TIMEFRAME_INPUT
    else:  # alert_price
        await edit_message(query, "💰 لطفاً جفت ارز را وارد کنید (مثال: BTCUSDT):")
        return PAIR_INPUT


async def timeframe_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    timeframe = update.message.text.lower().strip()
    valid_timeframes = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
    if timeframe not in valid_timeframes:
        await send_message(
            context,
            user_id,
            f"❌ تایم فریم نامعتبر است. لطفاً یکی از این موارد را انتخاب کنید:\n{', '.join(valid_timeframes)}",
        )
        return TIMEFRAME_INPUT

    context.user_data["timeframe"] = timeframe
    await send_message(
        context, user_id, "💰 لطفاً جفت ارز را وارد کنید (مثال: BTCUSDT):"
    )
    return PAIR_INPUT


async def pair_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pair = update.message.text.upper().strip()

    valid = await asyncio.to_thread(is_valid_pair, pair)
    if not valid:
        await send_message(
            context,
            user_id,
            "❌ جفت ارز نامعتبر است یا خطای شبکه رخ داده. لطفاً دوباره تلاش کنید (مثال: BTCUSDT):",
        )
        return PAIR_INPUT

    context.user_data["pair"] = pair
    alert_type = context.user_data.get("alert_type")

    if alert_type == "alert_rsi":
        await send_message(
            context, user_id, "🔢 لطفاً دوره RSI را وارد کنید (معمولاً 14):"
        )
        return RSI_PERIOD_INPUT
    else:  # alert_price
        await send_message(context, user_id, "💵 لطفاً قیمت مورد نظر را وارد کنید:")
        return PRICE_INPUT


async def rsi_period_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        period = int(update.message.text.strip())
        if not 2 <= period <= 100:
            raise ValueError
        context.user_data["rsi_period"] = period
        keyboard = [
            [InlineKeyboardButton("⬆️ بالاتر از", callback_data="rsi_above")],
            [InlineKeyboardButton("⬇️ پایین‌تر از", callback_data="rsi_below")],
        ]
        await send_message(
            context,
            user_id,
            "شرط RSI را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return RSI_CONDITION_INPUT
    except (ValueError, TypeError):
        await send_message(
            context, user_id, "❌ دوره نامعتبر است. لطفاً یک عدد بین 2 تا 100 وارد کنید."
        )
        return RSI_PERIOD_INPUT


async def rsi_condition_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["rsi_condition"] = query.data.split("_")[1]  # 'above' or 'below'
    await edit_message(query, "🎯 لطفاً مقدار آستانه RSI را وارد کنید (بین 0 تا 100):")
    return RSI_THRESHOLD_INPUT


async def rsi_threshold_input_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    try:
        threshold = float(update.message.text.strip())
        if not 0 <= threshold <= 100:
            raise ValueError
        context.user_data["rsi_threshold"] = threshold
        # Price is not used for RSI alerts, so we set a dummy value
        context.user_data["price"] = 0
        await send_message(
            context,
            user_id,
            "📜 لطفاً یک متن کوتاه برای آلارم وارد کنید (یا /skip برای رد شدن):",
        )
        return DESCRIPTION_INPUT
    except (ValueError, TypeError):
        await send_message(
            context,
            user_id,
            "❌ مقدار نامعتبر است. لطفاً یک عدد بین 0 تا 100 وارد کنید.",
        )
        return RSI_THRESHOLD_INPUT


async def price_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        price = float(update.message.text.strip())
        context.user_data["price"] = price
        await send_message(
            context,
            user_id,
            "📜 لطفاً یک متن کوتاه برای آلارم وارد کنید (یا /skip برای رد شدن):",
        )
        return DESCRIPTION_INPUT
    except ValueError:
        await send_message(
            context, user_id, "❌ قیمت نامعتبر است. لطفاً یک عدد وارد کنید:"
        )
        return PRICE_INPUT


async def save_alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Handle /skip command
    if update.message.text and update.message.text.lower().strip() == "/skip":
        context.user_data["alert_description"] = ""
    else:
        context.user_data["alert_description"] = update.message.text.strip()

    context.user_data["user_id"] = user_id

    # Save the alert to the database
    alert_id = db.save_alert(context.user_data)

    if alert_id:
        full_alert_data = db.get_alert_by_id(user_id, alert_id)
        if full_alert_data:
            await start_alarm_task(context.application, full_alert_data)
            message_text = f"✅ آلارم با موفقیت ایجاد شد!\n\n{AlertManager.format_alert_details(full_alert_data)}"
            await send_message(context, user_id, message_text)
        else:
            await send_message(context, user_id, "❌ خطا در بازیابی آلارم پس از ذخیره.")
    else:
        await send_message(
            context, user_id, "❌ خطا در ذخیره آلارم. لطفاً دوباره تلاش کنید."
        )

    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_message(context, update.effective_chat.id, "❌ عملیات لغو شد.")
    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END
