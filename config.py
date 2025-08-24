import os
from datetime import timezone, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Telegram Bot Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = 79795657  # Your Telegram User ID
ALLOWED_USERS = [ADMIN_ID, 239339319]  # Start with admin, other users can be added

# --- Database Configuration ---
DB_FILE = "alerts.db"

# --- API Configuration ---
BITUNIX_API_URL = "https://fapi.bitunix.com/api/v1"

# --- Localization & Timezone ---
TIMEZONE = timezone(timedelta(hours=3, minutes=30))  # Asia/Tehran

# --- Bot Settings ---
# A dictionary to hold references to running alarm tasks
# The key is the alert_id and the value is the asyncio.Task object
ACTIVE_ALARM_TASKS = {}
