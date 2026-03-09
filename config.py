import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Configuración MySQL
DB_CONFIG = {
    'host': os.getenv("DB_HOST", ""),
    'user': os.getenv("DB_USER", ""),
    'password': os.getenv("DB_PASSWORD", ""),
    'database': os.getenv("DB_NAME", ""),
    'port': int(os.getenv('DB_PORT', )),
    'charset': 'utf8mb4',
}

# Configuración Algolia
ALGOLIA_APP_ID = os.getenv("ALGOLIA_APP_ID", "")
ALGOLIA_API_KEY = os.getenv("ALGOLIA_API_KEY", "")
ALGOLIA_INDEX = os.getenv("ALGOLIA_INDEX", "")

# Configuración DeepSeek
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent"


# Configuración WhatsApp
WHATSAPP_TOKEN = os.getenv('WHATSAPP_TOKEN', '')
WHATSAPP_PHONE_ID = os.getenv('WHATSAPP_PHONE_ID', '')
WHATSAPP_VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN', '')
WHATSAPP_API_URL = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_ID}/messages"
