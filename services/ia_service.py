# chatbot_system.py
import requests
import json
import re
from core.constants import *
from config import *
from services.algolia_service import *
from utils.formatter import *
from services.notificacion_services import *

def extraer_parametro_basico(texto, intent):
    """Extrae parámetros básicos según el intent"""
    if intent == "seguimiento_por_numero_documento":
        # Buscar números de documento
        match = re.search(r'(\d+[-/]\d+|[A-Z]{2,}[-/]\d+|\d{4,})', texto)
        return match.group(1) if match else None
        
    elif intent == "seguimiento_por_codigo":
        # Buscar códigos PR-XXXX
        match = re.search(r'(PR[-]?\d+)', texto, re.IGNORECASE)
        return match.group(1) if match else None
        
    elif intent in ["buscar_documentos", "conversacion_general"]:
        return texto
        
    return None

def detectar_intencion_local_mejorado(texto_usuario):
    """Detección local mejorada como fallback"""
    texto = texto_usuario.lower().strip()
    
    # Patrones mejorados
    patrones = {
        "saludo": r'\b(hola|buenos días|buenas tardes|buenas noches|saludos|hey)\b',
        "contactar_encargado": r'\b(contactar|contacto|escribir|hablar|mensaje|encargado|responsable)\b',
        "seguimiento_por_numero_documento": r'\b(seguimiento|historial|estado)\b.*\b(\d+[-/]\d+|[A-Z]{2,}[-/]\d+|\d{4,})\b',
        "seguimiento_por_codigo": r'\b(seguimiento|código)\b.*\bPR[-]?\d+\b',
        "seguimiento_por_proyecto": r'\b(seguimiento|proyecto)\b.*(saneamiento|riego|canal|i\.e\.|colegio)',
        "seguimiento_por_consecutivo": r'(carta\s*n?[°º]?\s*)?\d{3,5}(-\d{4,}-?[a-z]{2,})?',
        "buscar_documentos": r'\b(buscar|busca|encuentra|archivo)\b',
        "despedida": r'\b(adiós|gracias|bye|hasta luego|nos vemos)\b'
    }
    
    for intent, patron in patrones.items():
        if re.search(patron, texto):
            # Extraer parámetro básico
            parametro = extraer_parametro_basico(texto, intent)
            return {"intent": intent, "parametro": parametro}
    
    # Por defecto, conversación general
    return {"intent": "conversacion_general", "parametro": texto_usuario}

#Funciones de detección de intención con IA
def convertir_resultado(resultado):
    """Convierte el formato de  al formato esperado por tu código actual"""
    intent = resultado.get("intent")
    parameters = resultado.get("parameters", {})
    
    parametro = None
    consulta = None
    
    if intent in ["seguimiento_por_codigo", "seguimiento_por_numero_documento"]:
        parametro = parameters.get("document_id")
    elif intent == "seguimiento_por_usuario":
        parametro = parameters.get("usuario")
    elif intent == "seguimiento_por_proyecto":
        parametro = parameters.get("proyecto")
    elif intent == "seguimiento_por_estado":
        parametro = normalizar_estado(parameters.get("estado", ""))
    elif intent in ["buscar_documentos", "seguimiento_por_asunto", "conversacion_general", "resumen"]:
        parametro = parameters.get("consulta")
        consulta = parametro
    
    result = {"intent": intent}
    
    if parametro:
        result["parametro"] = parametro
    if consulta:
        result["consulta"] = consulta
    
    if parameters.get("is_follow_up"):
        result["is_follow_up"] = True
    if parameters.get("context_reference"):
        result["is_contextual_reference"] = True
    
    return result



def consultar_ia_con_memoria(consulta, context=None, conversation_state=None):
    """Versión mejorada que considera contexto y estados de conversación"""
    try:
        # Construir contexto enriquecido
        contexto_adicional = ""
        estado_info = ""
        
        if context and context.get("recent_documents"):
            contexto_adicional += f"\nDocumentos consultados recientemente: {', '.join(context['recent_documents'][:3])}"
        if context and context.get("recent_projects"):
            contexto_adicional += f"\nProyectos consultados recientemente: {', '.join(context['recent_projects'][:2])}"
        if context and context.get("last_intent"):
            contexto_adicional += f"\nÚltima consulta fue sobre: {context['last_intent']}"
        
        if conversation_state:
            estado = conversation_state.get('state', 'initial')
            estado_info = f"""
🔄 ESTADO ACTUAL DE CONVERSACIÓN: {estado}
"""
            if estado == "awaiting_choice":
                estado_info += "- Usuario debe elegir de una lista de documentos mostrada\n"
            elif estado == "awaiting_verification":
                estado_info += "- Usuario debe confirmar si un documento es correcto\n"
            elif estado == "filtered_search":
                estado_info += "- Búsquedas se realizan solo en documentos previamente encontrados\n"
            
            if conversation_state.get('has_document_list'):
                estado_info += f"- Tiene {conversation_state.get('last_search_results_count', 'N/A')} documentos en memoria\n"

        print("CONTEXTO", context)
        print("CONTEXTO ADICIONAL", contexto_adicional)
        print("ESTADO INFO", estado_info)

        prompt = f"""
👋 ¡Hola! Soy tu asistente de ProRequest con MEMORIA CONVERSACIONAL Y ESTADOS AVANZADOS.

Eres un asistente especializado en **documentos administrativos, trámites, expedientes y seguimientos**.  
Prioriza siempre dar instrucciones claras para que el usuario consulte la base de datos interna (MySQL y Algolia).  

🧠 CONTEXTO CONVERSACIONAL ACTIVO:
{contexto_adicional}

{estado_info}

🔍 INSTRUCCIONES ESPECIALES SEGÚN ESTADO:

📋 SI ESTADO = "awaiting_choice" (esperando elección):
- El usuario debe elegir un documento de una lista mostrada anteriormente
- Puede elegir escribiendo un número (1, 2, 3...) o mencionando código/asunto
- Si pregunta algo diferente, recordarle que primero debe elegir

✅ SI ESTADO = "awaiting_verification" (esperando confirmación):
- Se mostró un documento específico y espera confirmación
- Si dice "sí/si/correcto" → responder: "Perfecto, ¿En qué más puedo ayudarte?"
- Si dice "no/incorrecto" → responder: "Entiendo. ¿Podrías especificar mejor el documento que buscas?"

🔍 SI ESTADO = "filtered_search" (búsqueda filtrada):
- Las búsquedas se realizan solo en documentos previamente encontrados
- Mencionar que está buscando dentro de los resultados anteriores
- Para buscar en toda la BD, debe escribir "hola" para reiniciar

🏠 SI ESTADO = "initial" (estado normal):
- Funcionamiento normal, puede buscar en toda la base de datos

🚨 ALERTAS Y CONTACTO:
- Si el mensaje contiene información de alerta con encargado/responsable
- Si usuario responde afirmativamente a contactar → generar link WhatsApp
- Formato: "Puedes contactar al encargado aquí: https://wa.me/51XXXXXXXXX"

⚠️ REGLAS GENERALES:
- Si el usuario hace referencia a conversaciones previas ("el anterior", "ese documento", "también", etc.), utiliza el contexto proporcionado
- Si pregunta por algo relacionado a documentos/proyectos mencionados antes, haz la conexión
- Nunca inventes documentos que no existen en la base
- Si no sabes algo, indícalo y redirige a opciones de búsqueda

OPCIONES DE BÚSQUEDA DISPONIBLES:
* Consultar el seguimiento de un documento (usar palabra clave "seguimiento")
* Buscar archivo (usar palabra clave "buscar")
* Contactar encargado (si hay alerta activa)

CONSULTA ACTUAL: "{consulta}"

Recuerda que tienes un máximo de 300 tokens para responder.
"""

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
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 400,
                "topP": 0.8
            }
        }
        
        response = requests.post(GEMINI_URL, headers=headers, json=data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            try:
                content = result["candidates"][0]["content"]["parts"][0]["text"]
                print(f"✅ IA con contexto y estados respondió: {content[:100]}...")
                return content
            except Exception as e:
                print("❌ Error parseando respuesta IA:", e)
                return None
                
        elif response.status_code == 429:
            return "⚠️ Servicio temporalmente no disponible por límite de uso."
            
        elif response.status_code == 401:
            return "❌ API Key inválida"
            
        else:
            return f"❌ Error IA: {response.status_code} - {response.text}"
            
    except requests.exceptions.Timeout:
        return "⏰ El servicio de IA está tardando mucho en responder."
        
    except requests.exceptions.ConnectionError:
        return "🔌 Error de conexión con el servicio de IA."
        
    except Exception as e:
        return f"❌ Error inesperado IA: {e}"


def seleccionar_respuesta(texto_usuario, context=None, documentos=None, conversation_state=None):
    """Función para seleccionar documento de lista con estados integrados"""
    try:
        print("DOCUMENTOS:", documentos)
        context_info = ""
        state_info = ""
        
        if context and context.get("is_follow_up"):
            context_info += f"\n🧠 CONTEXTO CONVERSACIONAL ACTIVO:\n"
            if context.get("last_intent"):
                context_info += f"- Última intención: {context['last_intent']}\n"
            if context.get("recent_documents"):
                context_info += f"- Documentos mencionados: {', '.join(context['recent_documents'][:3])}\n"

        if conversation_state:
            state_info = f"""
🔄 ESTADO CONVERSACIÓN: {conversation_state.get('state', 'unknown')}
- ¿Esperando confirmación?: {conversation_state.get('awaiting_confirmation', False)}
- Tipo confirmación: {conversation_state.get('confirmation_type', 'N/A')}
"""

        print("SELECCIÓN DE RESPUESTA documentos:", len(documentos) if documentos else 0)
        
        prompt = f"""
Eres un selector inteligente de documentos con ESTADOS DE CONVERSACIÓN.

{state_info}

{context_info}

🎯 FUNCIÓN PRINCIPAL:
 MODO BÚSQUEDA EN LISTA GUARDADA:
                El usuario está seleccionando de una lista previamente mostrada.
                Los resultados disponibles son: {documentos}
                
                Se pide al usuario que seleccione uno de los resultados
                Instrucciones: 
                - Esto lo puede hacer escribiendo un número (1,2,3...) esto haciendo referencia al orden de la lista
                Ejemplo: Si se escribe 1, entonces está eligiendo el primer elemento de la lista.
                - Si no lo hace de esa manera puede buscar o hacer referencia al valor cuyo clave es codigo_sistema, tipo, numero_documento, asunto. (Sólo se busca por esos valores)
                Nota: No tiene que escribir exactamente el valor, debes entenderlo o puede estar incluido, por ejemplo si su numero documento es 30610-COS-CAR-C01-2025-149, entonces el usuario escribe
                "149" y debes encontrarlo. Cabe resaltar que si en esta selección se encuentra mas de un posible resultado, tienes que devolver todas las que coincidan (idealmente, solo deberia retornar una,
                pero si el usuario no pone algo tan especifico entonces no hay otra manera que devolver todo lo que se coincidió).


📋 CRITERIOS DE SELECCIÓN:

1️⃣ POR POSICIÓN:
- Usuario escribe número: "1", "2", "3" etc.
- Corresponde a la posición en la lista (1 = primer documento), en su defecto puedes buscar por el "cache_id" y te guías del último número +1.
Ejemplo: Si pongo 1, debería salir el que tenga ->'cache_id': '51994018002_1758298904_0' (Lo importante es el último dígito)

2️⃣ POR IDENTIFICACIÓN:
- Usuario menciona código: "PR-001640", "148", "149"
- Usuario menciona asunto: "valorización", "hospital"
- Usuario menciona tipo: "carta", "oficio"
- Buscar en campos: codigo_sistema, tipo, numero_documento, asunto, numero_consecutivo

3️⃣ CONFIRMACIÓN/NEGACIÓN:
- "sí/si/correcto/exacto/ese" → confirmar_seleccion (positiva)
- "no/incorrecto/otro/diferente" → confirmar_seleccion (negativa)

⚠️ REGLAS ESPECIALES:
- Si encuentra MÚLTIPLES coincidencias → devolver todas
- Si NO encuentra coincidencias → indicar error
- SOLO buscar en los documentos proporcionados, NO en toda la base
- Si usuario hace consulta nueva → marcar "nueva_consulta": true

EJEMPLOS:
Usuario: "1" → Selecciona documento en posición 1 o cache_id con último número ".._0"
Usuario: "2" → Selecciona documento en posición 2 o cache_id con último número ".._1"
Usuario: "149" → Busca "149" en todos los campos del documento  
Usuario: "valorización" → Busca en asuntos que contengan "valorización"
Usuario: "sí" → Confirmación positiva
Usuario: "no es ese" → Confirmación negativa

ENTRADA DEL USUARIO: "{texto_usuario}"

Responde SOLO JSON válido:
{{
    "intent": "select_document" | "confirmar_seleccion" | "nueva_consulta",
    "parameters": {{
        "document_id": "id del diccionario",
        "codigo_sistema":"codigo_sistema"(siempre tiene este formato:PR-000801 ),
        "tipo": "tipo del documento (Carta, Solicitud ...)",
        "numero_documento": "numero_documento",
        "asunto": "asunto", 
        "estado_flujo": "estado_flujo",
        "prioridad_nombre": "prioridad_nombre",
        "responsable_proyecto":responsable_proyecto,
        "encargados":encargados,
        "proyecto_nombre": "proyecto_nombre",
        "fecha_ingreso": "fecha_ingreso",
        "fecha_limite":"fecha_limite",
        "posicion_lista": numero_si_es_seleccion,
        "confirmacion_positiva": true/false/null,
        "nueva_consulta": true/false,
        "search_in_saved": true,
        "error": "mensaje_si_no_encuentra"

    }},
    "confidence": 0.95
}}
"""

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
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1000,
                "responseMimeType": "application/json"
            }
        }
        
        response = requests.post(GEMINI_URL, headers=headers, json=data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            try:
                content = result["candidates"][0]["content"]["parts"][0].get("text", "").strip()
                print("🔎 RAW Gemini:", content)

                if not content:
                    print("❌ Gemini devolvió respuesta vacía")
                    return None
                    
                # Limpiar formato de código si existe
                if content.startswith("```"):
                    content = content.strip("`")
                    if content.lower().startswith("json"):
                        content = content[4:].strip()
                
                intent_data = json.loads(content)
                if "documentos_encontrados" not in intent_data:
                    intent_data["documentos_encontrados"] = {}

                intent_data["documentos_encontrados"] = documentos
                print(f"✅ Selección procesada: {intent_data.get('intent')} - encontrados: {len(intent_data.get('documentos_encontrados', []))}")
                return intent_data
                
            except json.JSONDecodeError as e:
                print("❌ Gemini JSON inválido:", e, content[:200])
                return None
                
        else:
            print(f"❌ Gemini HTTP {response.status_code}: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Error Gemini selección: {e}")
        return None
    




def seleccionar_de_lista(texto_usuario: str, resumen: list) -> dict | None:
    """
    Resuelve qué documento de la lista quiso decir el usuario.

    Args:
        texto_usuario: lo que escribió el usuario
        resumen: lista de dicts con keys: idx, codigo, numero, asunto, encargado

    Returns:
        {"idx": N} con posición 1-based, o None si no se pudo resolver
    """
    # ── Capa 1: Python puro ───────────────────────────────────────────────────
    resultado_local = _seleccionar_localmente(texto_usuario, resumen)
    if resultado_local:
        print(f"✅ seleccionar_de_lista (local): idx={resultado_local['idx']}")
        return resultado_local

    # ── Capa 2: Gemini ────────────────────────────────────────────────────────
    resultado_gemini = _seleccionar_con_gemini(texto_usuario, resumen)
    if resultado_gemini:
        print(f"✅ seleccionar_de_lista (Gemini): idx={resultado_gemini['idx']}")
        return resultado_gemini

    print(f"⚠️  seleccionar_de_lista: no se pudo resolver '{texto_usuario}'")
    return None


def _seleccionar_localmente(texto: str, resumen: list) -> dict | None:
    """
    Intenta resolver la selección sin IA.
    Cubre: número de posición, código exacto/parcial, substring asunto.
    """
    texto_lower = texto.lower().strip()

    # Número de posición puro ("1", "2", ...)
    if re.match(r'^\s*\d+\s*$', texto):
        idx = int(texto.strip())
        if 1 <= idx <= len(resumen):
            return {"idx": idx}

    # Ordinal textual
    ordinales = {
        "primero": 1, "primera": 1,
        "segundo": 2, "segunda": 2,
        "tercero": 3, "tercera": 3,
        "cuarto":  4, "cuarta":  4,
        "quinto":  5, "quinta":  5,
    }
    for palabra, idx in ordinales.items():
        if palabra in texto_lower and idx <= len(resumen):
            return {"idx": idx}

    # Código o número de documento — buscar en codigo y numero
    tokens = re.findall(r'[A-Z0-9][\w-]*\d[\w-]*', texto, re.IGNORECASE)
    for token in tokens:
        token_upper = token.upper()
        matches = [
            doc for doc in resumen
            if token_upper in str(doc.get("codigo") or "").upper()
            or token_upper in str(doc.get("numero") or "").upper()
        ]
        if len(matches) == 1:
            return {"idx": matches[0]["idx"]}
        if len(matches) > 1:
            # Intentar match exacto
            exactos = [
                d for d in matches
                if token_upper == str(d.get("numero") or "").upper()
                or token_upper == str(d.get("codigo") or "").upper()
            ]
            if len(exactos) == 1:
                return {"idx": exactos[0]["idx"]}
            # Ambiguo — dejar a Gemini
            return None

    # Substring del asunto (solo si texto tiene más de 3 chars)
    if len(texto_lower) > 3:
        matches_asunto = [
            doc for doc in resumen
            if texto_lower in str(doc.get("asunto") or "").lower()
        ]
        if len(matches_asunto) == 1:
            return {"idx": matches_asunto[0]["idx"]}

    # Nombre de encargado
    if len(texto_lower) > 2:
        matches_enc = [
            doc for doc in resumen
            if texto_lower in str(doc.get("encargado") or "").lower()
        ]
        if len(matches_enc) == 1:
            return {"idx": matches_enc[0]["idx"]}

    return None


def _seleccionar_con_gemini(texto_usuario: str, resumen: list) -> dict | None:
    """
    Fallback: Gemini resuelve selecciones ambiguas o en lenguaje natural.
    Solo se llama si la detección local no encontró nada.
    Prompt mínimo para reducir tokens.
    """
    try:
        prompt = f"""
El usuario quiere seleccionar un documento de esta lista escribiendo: "{texto_usuario}"

LISTA (máx 20):
{json.dumps(resumen[:20], ensure_ascii=False)}

Identifica cuál documento corresponde.
El usuario pudo escribir: número de posición, código parcial, parte del asunto, nombre del encargado.

Responde SOLO JSON:
{{"encontrado": true/false, "idx": <número 1-based o null>}}
"""
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": GEMINI_API_KEY
        }
        data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 100,
                "responseMimeType": "application/json"
            }
        }

        response = requests.post(GEMINI_URL, headers=headers, json=data, timeout=15)

        if response.status_code == 200:
            content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            resultado = json.loads(content)
            print(f"🤖 Gemini selección: {resultado}")

            if resultado.get("encontrado") and resultado.get("idx") is not None:
                idx = int(resultado["idx"])
                if 1 <= idx <= len(resumen):
                    return {"idx": idx}

        return None

    except Exception as e:
        print(f"❌ Error Gemini en seleccionar_de_lista: {e}")
        return None
