import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Configuración MySQL
DB_CONFIG = {
    'host': os.getenv("DB_HOST", "plaindes-db.cvkmsooisfec.us-east-2.rds.amazonaws.com"),
    'user': os.getenv("DB_USER", "admin"),
    'password': os.getenv("DB_PASSWORD", "j~BwbFPPyu<~SF!H>j~80Y6cuIqi"),
    'database': os.getenv("DB_NAME", "prorequestdb"),
    'port': int(os.getenv('DB_PORT', 3306)),
    'charset': 'utf8mb4',
}

# Configuración Algolia
ALGOLIA_APP_ID = os.getenv("ALGOLIA_APP_ID", "396GH2QXFY")
ALGOLIA_API_KEY = os.getenv("ALGOLIA_API_KEY", "eeb4681ad7152a71fac9b5559a58672d")
ALGOLIA_INDEX = os.getenv("ALGOLIA_INDEX", "drive_documents")

# Configuración DeepSeek
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "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")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


# Configuración de OpenRouter/DEEPSEEK
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")
MODEL = os.getenv("MODEL", "mistralai/mistral-small-3.2-24b-instruct:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

OLLAMA_URL = "http://localhost:11434"
MODEL_OLLAMA = "phi3:mini"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDOSlRSy7g7QZBqYsAXAGJh06127KDGnoE")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


# Configuración WhatsApp
WHATSAPP_TOKEN = os.getenv('WHATSAPP_TOKEN', 'EAAU5QP99BPwBPc7ZAfBYIMsiM7wkEwPb2GVYFH8W0R8i9fAt8dXWTDr75Q7HjhtShk0oFi63ZAAi1ZCPUDBgcgaKVQADjdj0Dlxc1RahqJV4G3Ja9ZCF10EBe8crtGXyuybP4N8Sb16R0FPO8jGIUWZCeWTRJqB2tTTcsAIIofWo8njYUFknQf7zCWD1zbMOqmJGyLLFp8xhWdTKGf1sZBBuNIZBlsfLR3HY23Yv2X3zYTOFGU3GgxGlfaTZAQZDZD')
WHATSAPP_PHONE_ID = os.getenv('WHATSAPP_PHONE_ID', '677005342171863')
WHATSAPP_VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN', 'miverificacion123')
WHATSAPP_API_URL = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_ID}/messages"
