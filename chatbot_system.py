# chatbot_system.py - Versión mejorada con memoria conversacional funcional
import requests
import json
import re
from config import *
from constants import *
from algolia_chatbot import *
from utils import *

#Funciones para manejo sin inteligencia artificial
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
    
    # Determinar el parámetro principal basado en la intención
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
    
    # Formato compatible con tu código actual
    result = {"intent": intent}
    
    if parametro:
        result["parametro"] = parametro
    if consulta:
        result["consulta"] = consulta
    
    # 🧠 NUEVO: Mantener flags de contexto
    if parameters.get("is_follow_up"):
        result["is_follow_up"] = True
    if parameters.get("context_reference"):
        result["is_contextual_reference"] = True
    
    return result

def detectar_intencion_optimizado(texto_usuario):
    """Función original mantenida para compatibilidad"""
    # Primero intentar con Gemini
    result_gemini = detectar_intencion_con_contexto(texto_usuario)
    if result_gemini:
        return convertir_resultado(result_gemini)
    
    # Fallback local optimizado
    print("🔄 Usando detección local como fallback...")
    return detectar_intencion_local_mejorado(texto_usuario)
def detectar_intencion_con_contexto(texto_usuario, context=None, documentos = None):
    """Versión mejorada de Gemini que considera contexto conversacional - MEJORADA PARA BUSQUEDA EN LISTA"""
    try:
        # Construir prompt con contexto conversacional más detallado
        context_info = ""
        alert_context = ""
        
        if context and context.get("is_follow_up"):
            context_info += f"\n🧠 CONTEXTO CONVERSACIONAL ACTIVO:\n"
            
            if context.get("last_intent"):
                context_info += f"- Última intención: {context['last_intent']}\n"
            
            if context.get("recent_documents"):
                context_info += f"- Documentos mencionados: {', '.join(context['recent_documents'][:3])}\n"
                
            if context.get("recent_projects"):
                context_info += f"- Proyectos mencionados: {', '.join(context['recent_projects'][:2])}\n"
                
            if context.get("recent_users"):
                context_info += f"- Usuarios mencionados: {', '.join(context['recent_users'][:2])}\n"

            if context.get("last_parameters"):
                context_info += f"- Últimos parámetros: {context['last_parameters']}\n"
        
        # 🆕 NUEVO: Contexto de alerta activa
        if context and context.get("alert_active"):
            alert_context = f"""
🚨 ALERTA ACTIVA DETECTADA:
- Documento: {context.get('document_number', 'N/A')}
- Hay información de encargado disponible para contacto
- El usuario puede querer contactar al responsable
"""

        prompt = f"""
Eres un clasificador de intenciones para sistema de documentos CON MEMORIA CONVERSACIONAL. 

INTENCIONES DISPONIBLES:
- "saludo": Saludos básicos
- "seguimiento_por_numero_documento": Pedir seguimiento/historial de documento. Puede ser solo un número/código.
- "seguimiento_por_codigo": Buscar por código interno formato "PR-001226".
- "seguimiento_por_proyecto": Documentos de un proyecto específico.
- "seguimiento_por_asunto": Búsqueda por asunto o contenido largo.
- "seguimiento_por_usuario": Documentos asignados a un usuario.
- "seguimiento_por_consecutivo": Buscar por código de antamina. La palabra clave es "seguimiento". El formato del código es siempre un número, te daré los ejemplos:'1229', '1218-2025-OXI', 'Carta N° 1225-2025-OXI','1268-2025-OXI'.
- "buscar_documentos": Consulta directa de documentos (palabra clave: "buscar").
- "contactar_encargado": El usuario quiere contactar al encargado/responsable del documento. Palabras clave: "contactar", "contacto", "escribir", "hablar", "mensaje", "encargado", "responsable", "sí", "si", "ok", "está bien", "genial", "perfecto", "quiero contactar".
- "conversacion_general": Chat general o ayuda
- "despedida": Despedidas

🧠 CONTEXTO CONVERSACIONAL:
{context_info}

{alert_context}

⚠️ REGLAS ESPECIALES PARA CONTEXTO:
- Si dice "también", "y este", "el anterior", "ese documento" → usar contexto previo
- Si menciona "más información" o "detalles" → mantener misma intención
- Para referencias como "este proyecto", "ese documento" → usar entidad del contexto
- Si solo dice conectores ("y", "también") → mantener último intent
- Cuando se agregue buscar tienes que usar el intent buscar_documentos para buscarlo por algolia
- 🆕 Si hay una alerta activa y el usuario responde afirmativamente ("sí", "ok", "contactar", etc.) → intent "contactar_encargado"

EJEMPLOS CON CONTEXTO:
Usuario anterior: "seguimiento PR-123"
Usuario actual: "y también este otro" → seguimiento_por_numero_documento con document_id del contexto

🆕 EJEMPLOS DE CONTACTO:
Contexto: Alerta de documento activa
Usuario: "sí" → contactar_encargado
Usuario: "contactar" → contactar_encargado
Usuario: "quiero hablar con el encargado" → contactar_encargado
Usuario: "ok, contactar" → contactar_encargado

ENTRADA: "{texto_usuario}"

Responde SOLO JSON válido:
{{
    "intent": "nombre_intencion",
    "parameters": {{
        "document_id": "codigo_extraido",
        "usuario": "nombre_usuario",
        "proyecto": "nombre_proyecto", 
        "estado": "estado_extraido",
        "consulta": "texto_busqueda",
        "is_follow_up": true/false,
        "context_reference": true/false,
        "wants_contact": true/false
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
                "maxOutputTokens": 500,
                "responseMimeType": "application/json"
            }
        }
        
        response = requests.post(GEMINI_URL, headers=headers, json=data, timeout=12)
        
        if response.status_code == 200:
            result = response.json()
            try:
                content = result["candidates"][0]["content"]["parts"][0]["text"]
                intent_data = json.loads(content)
                print(f"✅ Gemini con contexto: {intent_data.get('intent')} - {intent_data.get('confidence', 'N/A')}")
                print(f"📋 Parámetros: {intent_data.get('parameters', {})}")
                return intent_data
            except Exception as e:
                print("❌ Gemini JSON inválido:", e, content)
                return None
        else:
            print(f"❌ Gemini HTTP {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error Gemini: {e}")
        return None
#Consulta generar de ia
def consultar_ia_con_memoria(consulta, context=None):
    """Versión de  que considera el contexto conversacional"""
    try:
        # Construir contexto enriquecido
        contexto_adicional = ""
        if context and context.get("recent_documents"):
            contexto_adicional += f"\nDocumentos consultados recientemente: {', '.join(context['recent_documents'][:3])}"
        if context and context.get("recent_projects"):
            contexto_adicional += f"\nProyectos consultados recientemente: {', '.join(context['recent_projects'][:2])}"
        if context and context.get("last_intent"):
            contexto_adicional += f"\nÚltima consulta fue sobre: {context['last_intent']}"
        print("CONTEXTO", context)
        print("CONTEXTO ADICIONAl", contexto_adicional)

        prompt = f"""
👋 ¡Hola! Soy tu asistente de ProRequest con MEMORIA CONVERSACIONAL.

Eres un asistente especializado en **documentos administrativos, trámites, expedientes y seguimientos**.  
Prioriza siempre dar instrucciones claras para que el usuario consulte la base de datos interna (MySQL y Algolia).  

🧠 CONTEXTO CONVERSACIONAL ACTIVO:
{contexto_adicional}

🔍 INSTRUCCIONES ESPECIALES:
- Si el usuario hace referencia a conversaciones previas ("el anterior", "ese documento", "también", etc.), utiliza el contexto proporcionado
- Debes comprender el flujo conversacional: el bot puede estar en fase de *selección* (cuando hay varias opciones y debe pedir al usuario elegir), 
*confirmación* (cuando espera un sí/no antes de continuar) o *ejecución* (cuando entrega la información solicitada). 
La memoria guarda intención, parámetros y fase, para que el asistente continúe en el punto correcto del diálogo.
- Si pregunta por algo relacionado a documentos/proyectos mencionados antes, haz la conexión
- ⚠️ Si el mensaje contiene una alerta de documento con encargado o responsable (ejemplo: "💡 ¿Quieres contactar? 👤 Encargado: ..."),  
  entonces responde con un mensaje corto y un link directo de WhatsApp al encargado o responsable según indique el usuario 
  (sólo te responde que se quiere contactar y no especifica que por defecto sea al encargado).
  - Si en mi "contexto de documentos" aparece: ¿El documento es lo que estabas buscando? entonces debes responder a eso segun lo que te diga el usuario:
     Si dice que "si" o algo que indique afirmación entonces respondele: "Perfecto, ¿En qué más puedo ayudarte?", Si te dice que "no" o una negación, permite indicarle que haga la busqueda nuevamente.



Si el usuario pregunta algo fuera de los documentos o proyectos, puedes responder con información general, pero **siempre recuerda al usuario que puede hacer búsquedas como**:
* Consultar el seguimiento de un documento (usar palabra clave "seguimiento")
* Buscar archivo (usar palabra clave "buscar")

Nunca inventes documentos que no existen en la base!!    
👉 Si no sabes algo o no hay respuesta clara, indícalo y redirige a estas opciones de búsqueda.

Al final de responder y en caso sólo tengas como resulta un documento, osea una estructura de tipo,carta,asunto,,estado...- Tienes que agregar el mensaje final "¿El documento es lo que estabas buscando?"


CONSULTA ACTUAL: "{consulta}"

Recuerda que sólo tienes un máximo de 300 tokens para responder.
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
                "temperature": 0.3,  # Aumentado ligeramente para mejor contexto
                "maxOutputTokens": 400,
                "topP": 0.8
            }
        }
        
        response = requests.post(GEMINI_URL, headers=headers, json=data, timeout=15)
        
        if response.status_code == 200:
            result = response.json()
            try:
                content = result["candidates"][0]["content"]["parts"][0]["text"]
                print(f"✅ IA con contexto respondió: {content[:100]}...")
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

def seleccionar_respuesta(texto_usuario, context=None, documentos = None):
    """Versión mejorada de Gemini que considera contexto conversacional - MEJORADA PARA BUSQUEDA EN LISTA"""
    try:
        context_info = ""
        alert_context = ""
        instruccion_alerta = ""
        last_result = ""
        instruccion_last_result = ""
        instruccion_busqueda_lista = ""


        
        if context and context.get("is_follow_up"):
            context_info += f"\n🧠 CONTEXTO CONVERSACIONAL ACTIVO:\n"
            
            if context.get("last_intent"):
                context_info += f"- Última intención: {context['last_intent']}\n"
            
            if context.get("recent_documents"):
                context_info += f"- Documentos mencionados: {', '.join(context['recent_documents'][:3])}\n"
                
            if context.get("recent_projects"):
                context_info += f"- Proyectos mencionados: {', '.join(context['recent_projects'][:2])}\n"
                
            if context.get("recent_users"):
                context_info += f"- Usuarios mencionados: {', '.join(context['recent_users'][:2])}\n"

            if context.get("last_parameters"):
                context_info += f"- Últimos parámetros: {context['last_parameters']}\n"

        print("SELECCION DE RESPUESTA: ", documentos)
        
            
        prompt=f"""🆕 
        
        IMPORTANTE:

        - PRimer criterio es que si la respuesta del usuario es algun afirmativo o algún negativo o rechazo, significa que está respondiendo a esta pregunta "¿El documento es lo que estabas buscando?"

            - Según lo que te diga el usuario, si dice que "si" entonces respondele: "Perfecto, ¿En qué más puedo ayudarte?"
            si te dice que "no", entonces respondele: " ¿Podrías especificar nuevamente el documento?. Si te responde con algo diferente a una afirmacion o negacion y parece que este haciendo una busqueda nuevamente, entonces consideralo como otra consulta

        MI CONTEXTO :{context_info}
        
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

                EJEMPLOS:
                - Usuario: "1"  (posición 1)
                - Usuario: "148"   (buscar '148' en alguno de sus claves (puedes ser numero_documento, numero_consecutivo,codigo_sistema...))
                - Usuario: "valorización"  (buscar por asunto)
                - Usuario: "PR-001803"  (buscar por código)

                Por otro lado, cuando se encuentre el documento tienes que tener en cuenta lo siguiente:


                IMPORTANTE: Solo buscar en los resultados guardados, NO en toda la base de datos.

                
ENTRADA: "{texto_usuario}"


Responde SOLO JSON válido:
{{
    "intent": "select_document",
    "parameters": {{
        "document_id": "codigo_extraido",
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
        "is_follow_up": true/false,
        "context_reference": true/false,
        "search_in_saved": true/false
        
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
                "maxOutputTokens": 500,
                "responseMimeType": "application/json"
            }
        }
        
        response = requests.post(GEMINI_URL, headers=headers, json=data, timeout=12)
        print("RESPONSA DE GEMINI", response)
        if response.status_code == 200:
            result = response.json()
            try:
                content = result["candidates"][0]["content"]["parts"][0].get("text", "").strip()

                if not content:
                    print("❌ Gemini devolvió respuesta vacía")
                    return None
                # Si viene con bloque de código ```json ... ```
                if content.startswith("```"):
                    content = content.strip("`")  # quita backticks
                    if content.lower().startswith("json"):
                        content = content[4:].strip()
                try:
                    intent_data = json.loads(content)
                    return intent_data
                except json.JSONDecodeError as e:
                    print("❌ Gemini JSON inválido:", e, content)
                    return None
            except Exception as e:
                print("❌ Gemini JSON inválido:", e, content)
                return None
        else:
            print(f"❌ Gemini HTTP {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error Gemini: {e}")
        return None