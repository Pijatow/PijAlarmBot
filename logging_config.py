import logging
import os

# --- Log Directory ---
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# --- Log File Paths ---
ERROR_LOG_FILE = os.path.join(LOG_DIR, "errors.log")
MESSAGES_LOG_FILE = os.path.join(LOG_DIR, "messages.log")
API_LOG_FILE = os.path.join(LOG_DIR, "api.log")


def setup_logging():
    """Configures the logging system for the application."""

    # --- Root Logger Configuration (General Logs & Unhandled Exceptions) ---
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(ERROR_LOG_FILE),
            logging.StreamHandler(),  # Also print to console
        ],
    )

    # --- Message Logger (for user interactions) ---
    msg_logger = logging.getLogger("MessageLogger")
    msg_logger.setLevel(logging.INFO)
    msg_logger.propagate = False  # Prevent messages from being sent to the root logger
    msg_handler = logging.FileHandler(MESSAGES_LOG_FILE)
    msg_formatter = logging.Formatter("%(asctime)s - %(message)s")
    msg_handler.setFormatter(msg_formatter)
    msg_logger.addHandler(msg_handler)

    # --- API Logger (for external API requests) ---
    api_logger = logging.getLogger("ApiLogger")
    api_logger.setLevel(logging.INFO)
    api_logger.propagate = False
    api_handler = logging.FileHandler(API_LOG_FILE)
    api_formatter = logging.Formatter("%(asctime)s - %(message)s")
    api_handler.setFormatter(api_formatter)
    api_logger.addHandler(api_handler)

    return logging.getLogger(), msg_logger, api_logger


# Initialize the loggers
logger, msg_logger, api_logger = setup_logging()
