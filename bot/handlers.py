from textwrap import dedent

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes, ConversationHandler

import config
from bot.monitors import stop_alarm_task, start_alarm_task
from bot.ui import AlertManager
from bot.utils import translate_alert_type, is_valid_pair
from .constants import *
from database_manager import DatabaseManager
from logging_config import msg_logger, api_logger, logger

db = DatabaseManager(config.DB_FILE)


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg_logger.info(f"INCOMING -> User: {user_id}, Command: /summary")

    loading_message = await update.message.reply_text(
        "🔍 در حال دریافت قیمت‌های درخواستی..."
    )
    msg_logger.info(
        f"OUTGOING -> User: {user_id}, Text: 'در حال دریافت قیمت‌های درخواستی...'"
    )

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
    api_logger.info(f"REQUEST -> summary_command: URL={url}, Params={params}")

    try:
        response = requests.get(url, params=params, timeout=10)
        api_logger.info(f"RESPONSE -> summary_command: Status={response.status_code}")
        response.raise_for_status()

        tickers_data = response.json().get("data", [])
        if not tickers_data:
            await loading_message.edit_text(
                "❌ اطلاعاتی از بازار دریافت نشد (API response empty)."
            )
            return

        price_map = {ticker["symbol"]: ticker for ticker in tickers_data}
        message_lines = ["📈 خلاصه قیمت ارزهای درخواستی:\n"]
        for symbol in target_symbols:
            display_symbol = symbol.replace("USDT", "-USDT")
            if symbol in price_map:
                price = float(price_map[symbol].get("lastPrice", 0))
                # Format with commas and 4 decimal places
                formatted_price = f"{price:,.4f}"
                message_lines.append(f"🔹 {display_symbol}: {formatted_price}")
            else:
                message_lines.append(f"🔸 {display_symbol}: (N/A)")

        final_message = "\n".join(message_lines)
        await loading_message.edit_text(final_message)
        msg_logger.info(f"OUTGOING (EDIT) -> User: {user_id}, Sent custom summary.")

    except requests.RequestException as e:
        await loading_message.edit_text("❌ خطای شبکه در دریافت اطلاعات.")
    except Exception as e:
        logger.exception("UNEXPECTED ERROR in summary_command:")
        await loading_message.edit_text("❌ یک خطای پیش‌بینی نشده رخ داد.")


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

        در طول فرآیندها:
        /cancel - لغو عملیات فعلی (مانند ساخت آلارم)
    """
    )
    await update.message.reply_text(help_text)
    msg_logger.info(f"OUTGOING -> User: {user_id}, Sent help message.")


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
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            welcome_msg, reply_markup=reply_markup
        )
    msg_logger.info(f"OUTGOING -> User: {user.id}, Sent welcome message.")
    return MAIN_MENU


async def new_alarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg_logger.info(f"INCOMING -> User: {user_id}, Command: /new_alarm")
    keyboard = [
        [InlineKeyboardButton("🔔 آلارم قیمت", callback_data="alert_price")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")],
    ]
    await update.message.reply_text(
        "🔔 نوع آلارم را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ALERT_TYPE


async def list_alarms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg_logger.info(f"INCOMING -> User: {user_id}, Command: /list_alarms")
    alerts = db.get_user_alerts(user_id, ["id", "pair", "alert_type", "price"])

    if not alerts:
        await update.message.reply_text("📭 هیچ آلارم فعالی ندارید!")
        return ConversationHandler.END

    keyboard = []
    for alert in alerts:
        btn_text = f"🔔 {alert['pair']} - {translate_alert_type(alert['alert_type'])} - {alert['price']}"
        keyboard.append(
            [InlineKeyboardButton(btn_text, callback_data=f"alert_{alert['id']}")]
        )
    await update.message.reply_text(
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
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")],
        ]
        await query.edit_message_text(
            "🔔 نوع آلارم را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ALERT_TYPE
    elif query.data == "view_alerts":
        alerts = db.get_user_alerts(user_id, ["id", "pair", "alert_type", "price"])
        if not alerts:
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
            ]
            await query.edit_message_text(
                "📭 هیچ آلارم فعالی ندارید!",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return MAIN_MENU
        keyboard = []
        for alert in alerts:
            btn_text = f"🔔 {alert['pair']} - {translate_alert_type(alert['alert_type'])} - {alert['price']}"
            keyboard.append(
                [InlineKeyboardButton(btn_text, callback_data=f"alert_{alert['id']}")]
            )
        keyboard.append(
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
        )
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

    alert_id = int(query.data.split("_")[-1])

    context.user_data["selected_alert_id"] = alert_id
    user_id = query.from_user.id
    alert = db.get_alert_by_id(user_id, alert_id)

    if not alert:
        await query.edit_message_text("❌ آلارم یافت نشد.")
        return MAIN_MENU

    keyboard = [
        [
            InlineKeyboardButton("🗑 حذف", callback_data=f"delete_{alert_id}"),
            InlineKeyboardButton("✏️ ویرایش", callback_data=f"update_{alert_id}"),
        ],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="view_alerts")],
    ]
    message_text = f"📋 جزئیات آلارم:\n{AlertManager.format_alert_details(alert)}"
    await query.edit_message_text(
        text=message_text, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return VIEW_ALERT_DETAILS


async def alert_actions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, alert_id_str = query.data.split("_")
    alert_id = int(alert_id_str)
    context.user_data["selected_alert_id"] = alert_id

    if action == "delete":
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ بله، حذف کن", callback_data=f"confirm_delete_{alert_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ لغو", callback_data=f"back_to_details_{alert_id}"
                )
            ],
        ]
        await query.edit_message_text(
            "⚠️ آیا از حذف این آلارم اطمینان دارید؟",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return DELETE_CONFIRMATION
    elif action == "update":
        keyboard = [
            [InlineKeyboardButton("💵 قیمت", callback_data="update_field_price")],
            [
                InlineKeyboardButton(
                    "📜 متن", callback_data="update_field_alert_description"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت", callback_data=f"back_to_details_{alert_id}"
                )
            ],
        ]
        await query.edit_message_text(
            "کدام قسمت را می‌خواهید ویرایش کنید؟",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return UPDATE_SELECTION


async def delete_confirmation_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()
    action, alert_id_str = query.data.split("_")
    alert_id = int(alert_id_str)
    user_id = query.from_user.id

    alert_data = db.get_alert_by_id(user_id, alert_id)
    stop_alarm_task(alert_id)
    success, message = db.delete_user_alert(user_id, alert_id)

    if success:
        await query.edit_message_text(message)
        if alert_data and alert_data.get("last_message_id"):
            try:
                await context.bot.delete_message(
                    chat_id=user_id, message_id=alert_data["last_message_id"]
                )
            except BadRequest:
                pass
    else:
        await query.edit_message_text(message)

    await start(update, context)
    return ConversationHandler.END


async def update_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    field_to_update = query.data.replace("update_field_", "")
    context.user_data["field_to_update"] = field_to_update
    prompt_text = {
        "price": "💵 لطفاً قیمت جدید را وارد کنید:",
        "alert_description": "📜 لطفاً متن جدید را وارد کنید:",
    }
    await query.edit_message_text(
        prompt_text.get(field_to_update, "لطفاً مقدار جدید را وارد کنید:")
    )
    return UPDATE_GET_VALUE


async def update_get_value_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    alert_id = context.user_data.get("selected_alert_id")
    field = context.user_data.get("field_to_update")
    new_value = update.message.text

    if not all([alert_id, field]):
        await update.message.reply_text(
            "❌ خطا: اطلاعات ویرایش یافت نشد. لطفاً دوباره تلاش کنید."
        )
        return ConversationHandler.END

    if field == "price":
        try:
            new_value = float(new_value)
        except ValueError:
            await update.message.reply_text(
                "❌ قیمت نامعتبر است. لطفاً فقط عدد وارد کنید."
            )
            return UPDATE_GET_VALUE

    success = db.update_alert_field(alert_id, field, new_value)
    if not success:
        await update.message.reply_text("❌ خطا در به‌روزرسانی دیتابیس.")
        return ConversationHandler.END

    stop_alarm_task(alert_id)
    updated_alert = db.get_alert_by_id(user_id, alert_id)

    if updated_alert:
        await start_alarm_task(context.application, updated_alert)
        await update.message.reply_text(
            "✅ آلارم با موفقیت به‌روزرسانی شد و در حال اجراست!"
        )
        msg_logger.info(
            f"UPDATED -> Alert ID: {alert_id}, Field: {field}, User: {user_id}"
        )
    else:
        await update.message.reply_text("❌ خطا در ری‌استارت کردن تسک پس‌زمینه.")

    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END


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
        message_text = f"✅ آلارم با موفقیت ایجاد شد!\n\n{AlertManager.format_alert_details(context.user_data)}"
        await update.message.reply_text(message_text)
    else:
        await update.message.reply_text("❌ خطا در ذخیره آلارم. لطفاً دوباره تلاش کنید.")

    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ عملیات لغو شد.")
    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END
