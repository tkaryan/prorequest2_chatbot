import requests
import json

GEMINI_API_KEY = "AIzaSyDOSlRSy7g7QZBqYsAXAGJh06127KDGnoE"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"

def probar_gemini(prompt: str):
    """Envía un prompt simple a Gemini y devuelve la respuesta"""
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }

    data = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    try:
        response = requests.post(GEMINI_URL, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            # Extraer respuesta de Gemini
            content = result["candidates"][0]["content"]["parts"][0]["text"]
            print("✅ Respuesta Gemini:", content)
            return content
        else:
            print(f"❌ Error HTTP {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error al conectar con Gemini: {e}")
        return None

# 🔹 Ejemplo de prueba
if __name__ == "__main__":
    probar_gemini("Explain how AI works in a few words")
