import json
import requests
import os

# Idealmente, estas variables vienen de tu archivo .env
GEMINI_URL = os.getenv("GEMINI_URL", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent")

def ask_gemini_json(prompt: str, temperature: float = 0.1, max_tokens: int = 300) -> dict:
    """
    Se comunica con la API de Gemini (compatible con 3.1) forzando una respuesta JSON.
    """
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json"
        }
    }
    
    try:
        response = requests.post(GEMINI_URL, headers=headers, json=data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            content = result["candidates"][0]["content"]["parts"][0]["text"]
            
            content = content.replace('```json', '').replace('```', '').strip()
            
            return json.loads(content)
            
        else:
            print(f"❌ Gemini HTTP Error {response.status_code}: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Error de red al contactar a Gemini: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Error decodificando JSON de Gemini: {e}")
        return None
    except Exception as e:
        print(f"❌ Error inesperado en el cliente de Gemini: {e}")
        return None