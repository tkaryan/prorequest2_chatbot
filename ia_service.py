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
def detectar_intencion_con_contexto(texto_usuario, context=None, conversation_state=None):
    """Versión mejorada que integra estados de conversación y búsqueda inteligente"""
    try:
        # Construir información de contexto
        context_info = ""
        alert_context = ""
        state_context = ""
        
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
        
        # 🆕 NUEVO: Información de estado de conversación
        if conversation_state:
            state_context = f"""
🔄 ESTADO DE CONVERSACIÓN:
- Estado actual: {conversation_state.get('state', 'initial')}
- ¿Esperando confirmación?: {conversation_state.get('awaiting_confirmation', False)}
- Tipo confirmación: {conversation_state.get('confirmation_type', 'N/A')}
- ¿Tiene lista documentos?: {conversation_state.get('has_document_list', False)}
- ¿Debe buscar BD completa?: {conversation_state.get('should_search_full_db', True)}
"""
        
        # 🆕 NUEVO: Contexto de alerta activa  
        if context and context.get("alert_active"):
            alert_context = f"""
🚨 ALERTA ACTIVA DETECTADA:
- Documento: {context.get('document_number', 'N/A')}
- Hay información de encargado disponible para contacto
- El usuario puede querer contactar al responsable
"""

        prompt = f"""
Eres un clasificador de intenciones para sistema de documentos CON MEMORIA CONVERSACIONAL Y ESTADOS. 

ENTRADA: "{texto_usuario}"

Nota: 
- Si el texto del usuario puede tener errores ortográficos, normalmente puede usar la palabra buscar, consultar, seguimiento, quiero ver, así que ten en cuenta posibles errores ortográficos como:
"bscar, uscar, usxar, buszar,busxar (buscar), buscr,consita, consultr,eguimient,segmento, seguimiento,segimiento,sejimiento,consultr,onsultar,consultar,kiero ver,quiero ver,etc.
 - También puede pasar que ciertas palabras pueden estar junto con la palabra de busqueda, ejemplo: "seguimientcaserio de morc", en este caso la palabra clave seguimiento esta incluido pero incompleto. Mas eejemplos:
buscar123, busca21-2025.etc

INTENCIONES DISPONIBLES:
- "saludo": Saludos básicos o palabra "hola" (siempre resetea estado)
	Para los que son seguimiento debes tener en cuenta la palabras claves como consuulta o seguimiento, también considerar los errores ortográficos o puede estar incluido con otro texto
	por algun error. Ejmplo (seguimiento088-2025 -> seguimiento ,palabra clave 088-2025) errores ortograficos: segmento, sgmientu.... Lo mismo con "consulta"
- "seguimiento_por_numero_documento": Pedir seguimiento/historial de documento. Puede ser solo un número/código o combinados, además si indico número documento es ese.
- "seguimiento_por_codigo": Buscar por código interno formato "PR-001226".
- "seguimiento_por_proyecto": Documentos de un proyecto específico.
- "seguimiento_por_asunto": Búsqueda por asunto o contenido largo.
- "seguimiento_por_usuario": Documentos asignados a un usuario.
- "seguimiento_por_consecutivo": Buscar por código de antamina. La palabra clave es "seguimiento". El formato del código es siempre un número, te daré los ejemplos:'1229', '1218-2025-OXI', 'Carta N° 1225-2025-OXI','1268-2025-OXI'.
- "buscar_documentos": Consulta directa de documentos (palabra clave: "buscar") - ejemplo: Si la entrada contiene "buscar", "búsqueda", "búsqueda avanzada", "uscar", "busarc" o posibles errores 
o que esté incluido dentro del texto (quizas al usuario se le olvidó separar ejm, buscaragua, buscragua), deberías optar por este intent. NO AFECTA ESTADOS
- "contactar_encargado": El usuario quiere contactar al encargado/responsable del documento - NO AFECTA ESTADOS
- "conversacion_general": Chat general o ayuda
- "despedida": Despedidas
- "confirmar_seleccion": Usuario responde a pregunta de confirmación (sí/no)
- "seleccionar_documento": Usuario selecciona de una lista mostrada anteriormente

🧠 CONTEXTO CONVERSACIONAL:
{context_info}

{state_context}

{alert_context}

⚠️ REGLAS ESPECIALES PARA ESTADOS:

🔄 ESTADO "awaiting_choice" (esperando elección de lista):
- Si usuario dice número (1, 2, 3...) → "seleccionar_documento"
- Si usuario dice código/nombre documento → "seleccionar_documento" 
- Si usuario dice "sí/no" → "confirmar_seleccion"
- Si usuario hace nueva búsqueda → mantener intent original PERO marcar "search_in_filtered": true

🔄 ESTADO "awaiting_verification" (esperando verificación):
- Si usuario dice "sí/si/correcto/exacto" → "confirmar_seleccion" con confirmacion_positiva: true
- Si usuario dice "no/incorrecto/otro" → "confirmar_seleccion" con confirmacion_positiva: false
- Si hace nueva consulta → intent original


🔄 ESTADO "initial" (estado normal):
- Búsqueda normal en toda la base de datos
- "contactar_encargado" y "buscar_documentos" no cambian estado
- Si boto un "hola" debe volver al estado initial

⚠️ REGLAS CONTEXTUALES:
- Si dice "también", "y este", "el anterior", "ese documento" → usar contexto previo
- Si menciona "más información" o "detalles" → mantener misma intención
- Para referencias como "este proyecto", "ese documento" → usar entidad del contexto
- Si solo dice conectores ("y", "también") → mantener último intent
- Si hay alerta activa y responde afirmativamente → "contactar_encargado"

EJEMPLOS SEGÚN ESTADO:

Estado "initial":
- "seguimiento PR-123" → seguimiento_por_codigo
- "buscar cartas" → buscar_documentos
- "hola" → saludo

Estado "awaiting_choice":
- "1" → seleccionar_documento (posicion: 1)
- "PR-123" → seleccionar_documento (buscar código)
- "sí" → confirmar_seleccion (positiva)
- "no" → confirmar_seleccion (negativa)
- "buscar cartas en estos" → buscar_documentos (search_in_filtered: true)

Estado "awaiting_verification":
- "sí es correcto" → confirmar_seleccion (positiva)
- "no, no es" → confirmar_seleccion (negativa)
- "buscar otro similar" → buscar_documentos (search_in_filtered: depende si hay lista)

🆕 EJEMPLOS DE CONTACTO:
Contexto: Alerta de documento activa
Usuario: "sí" → contactar_encargado
Usuario: "contactar" → contactar_encargado
Usuario: "quiero hablar con el encargado" → contactar_encargado
Usuario: "ok, contactar" → contactar_encargado



Responde SOLO JSON válido:
{{
    "intent": "nombre_intencion",
    "parameters": {{
        "document_id": "codigo_extraido",
        "usuario": "nombre_usuario",
        "proyecto": "nombre_proyecto", 
        "estado": "estado_extraido",
        "consulta": "texto_busqueda", (no incluir el "buscar" o sus variaciones en texto_busqueda" del mensaje)
        "posicion_lista": numero_si_selecciona_por_posicion,
        "confirmacion_positiva": true/false (solo si es confirmar_seleccion),
        "is_follow_up": true/false,
        "context_reference": true/false,
        "search_in_filtered": true/false,
        "wants_contact": true/false
    }},
    "confidence": 0.95,
    "state_action": "maintain/reset/transition" 
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
                "maxOutputTokens": 600,
                "responseMimeType": "application/json"
            }
        }
        
        response = requests.post(GEMINI_URL, headers=headers, json=data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            try:
                content = result["candidates"][0]["content"]["parts"][0]["text"]
                print("CONTENT DE RESULTADOS", content)
                intent_data = json.loads(content)
                print(f"✅ Gemini con estados: {intent_data.get('intent')} - {intent_data.get('confidence', 'N/A')}")
                print(f"📋 Parámetros: {intent_data.get('parameters', {})}")
                print(f"🔄 Acción estado: {intent_data.get('state_action', 'maintain')}")
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
        
        # 🆕 NUEVO: Información de estado
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

        # 🆕 NUEVO: Información de estado
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
       # "documentos_encontrados": [lista_de_documentos_que_coinciden],

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

                # guardamos los docs encontrados
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
