import os
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
)

import config
from api_manager import ws_client
from bot.handlers import (
    start,
    new_alarm_command,
    list_alarms_command,
    main_menu_handler,
    view_alert_details_handler,
    delete_confirmation_handler,
    alert_type_handler,
    pair_input_handler,
    price_input_handler,
    save_alert_handler,
    cancel,
    summary_command,
    help_command,
    remind_command,
    timeframe_input_handler,
    rsi_period_input_handler,
    rsi_condition_handler,
    rsi_threshold_input_handler,
)
from bot.monitors import start_alarm_task
from bot.constants import *
from database_manager import DatabaseManager
from logging_config import logger

# --- Proxy Settings ---
os.environ["http_proxy"] = "http://12z7.0.0.1:10808"
os.environ["https_proxy"] = "http://127.0.0.1:10808"

# --- Database Initialization ---
db = DatabaseManager(config.DB_FILE)


async def post_init(application: Application):
    logger.info("--- Bot initialization complete ---")
    logger.info("--- Reloading active alerts from database ---")

    active_alerts = db.get_all_active_alerts()
    # Subscribe to all unique pairs from active price alerts
    price_alert_pairs = {
        alert["pair"] for alert in active_alerts if alert["alert_type"] == "alert_price"
    }
    for pair in price_alert_pairs:
        ws_client.add_subscription(pair)
    logger.info(
        f"--- Queued WS subscriptions for {len(price_alert_pairs)} unique pairs ---"
    )

    count = 0
    for alert in active_alerts:
        await start_alarm_task(application, alert)
        count += 1
    logger.info(f"--- Successfully reloaded {count} active alerts ---")


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        logger.critical("FATAL: TELEGRAM_BOT_TOKEN not found!")
        return

    # Configure timeouts for the bot's HTTP requests to make it more resilient
    application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("new_alarm", new_alarm_command),
            CommandHandler("list_alarms", list_alarms_command),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(
                    main_menu_handler, pattern="^new_alert$|^view_alerts$"
                )
            ],
            VIEW_ALERT: [
                CallbackQueryHandler(view_alert_details_handler, pattern="^alert_")
            ],
            VIEW_ALERT_DETAILS: [
                CallbackQueryHandler(delete_confirmation_handler, pattern="^delete_")
            ],
            ALERT_TYPE: [
                CallbackQueryHandler(alert_type_handler, pattern="^alert_(price|rsi)$")
            ],
            PAIR_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pair_input_handler)
            ],
            PRICE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, price_input_handler)
            ],
            DESCRIPTION_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_alert_handler),
                CommandHandler("skip", save_alert_handler),
            ],
            # RSI States
            TIMEFRAME_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, timeframe_input_handler)
            ],
            RSI_PERIOD_INPUT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, rsi_period_input_handler
                )
            ],
            RSI_CONDITION_INPUT: [
                CallbackQueryHandler(
                    rsi_condition_handler, pattern="^rsi_(above|below)$"
                )
            ],
            RSI_THRESHOLD_INPUT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, rsi_threshold_input_handler
                )
            ],
        },
        fallbacks=[
            CallbackQueryHandler(
                view_alert_details_handler, pattern="^back_to_details_"
            ),
            CallbackQueryHandler(start, pattern="^back_to_main$"),
            CommandHandler("cancel", cancel),
        ],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("remind", remind_command))

    loop = asyncio.get_event_loop()
    # Start the WebSocket client in the background
    loop.create_task(ws_client.run())
    logger.info("BACKGROUND: Bitunix WebSocket client started.")

    logger.info("🟡 CryptoAlertBot started successfully! Starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
