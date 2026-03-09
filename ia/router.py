import json
from .gemini_client import ask_gemini_json

def router(mensaje: str, context=None, conversation_state=None):
    """ Función que usa IA para determinar el intent y el próximo estado de la conversación """
    
    # Contexto
    context_info = ""
    if context and context.get("is_follow_up"):
        context_info = "🧠 CONTEXTO PREVIO:\n"
        context_info += f"- Última intención: {context.get('last_intent', 'N/A')}\n"
        context_info += f"- Documentos recientes: {', '.join(context.get('recent_documents', [])[:3])}\n"
        context_info += f"- Alerta activa: {'Sí (Doc: ' + context.get('document_number', '') + ')' if context.get('alert_active') else 'No'}\n"

    # Estado actual
    current_state = conversation_state.get('state', 'INITIAL') if conversation_state else 'INITIAL'
    state_context = f"""
🔄 ESTADO ACTUAL (FSM): {current_state}
- Detalles del estado: {json.dumps(conversation_state) if conversation_state else 'Ninguno'}
"""

  
    prompt = f"""
Eres el enrutador principal (Intent & State Classifier) de un chatbot de gestión documental.
Tu objetivo es analizar el mensaje del usuario y el estado actual de la conversación para decidir la intención (intent) y el estado de destino (next_state).

ENTRADA DEL USUARIO: "{mensaje}"

{state_context}
{context_info}

🎯 INTENCIONES DISPONIBLES (INTENTS):
[Búsqueda y Seguimiento]
- "buscar_documentos": Búsqueda general.
- "seguimiento_por_numero_documento": Buscar por número o código específico (ej. PR-123).
- "seguimiento_por_consecutivo": Buscar por número consecutivo (ej. 1229).
[Notificaciones]
- "listar_notificaciones_todas": Ver todas las alertas.
- "listar_sin_respuesta": Alertas de documentos sin responder.
- "listar_sin_firma": Alertas de documentos sin firmar.
- "listar_inactivos": Alertas de inactividad.
- "listar_stand_by": Alertas en pausa.
[Acciones de FSM]
- "seleccionar_opcion": Usuario elige un índice (1, 2, 3), un código de la lista mostrada, o dice "el primero/segundo".
- "confirmar_seleccion": Usuario responde Sí/No a una validación.
- "accion_post_detalle": Usuario decide qué hacer tras ver un documento (ej. "quiero ver otro de la lista", "nueva búsqueda").
[Contacto y Generales]
- "contactar_encargado" / "contactar_responsable": Quiere hablar con el dueño del doc.
- "saludo" / "despedida" / "conversacion_general".
- "fallback": No encaja en nada de lo anterior.

⚠️ REGLAS DE LA MÁQUINA DE ESTADOS PARA TRANSICIONES:

1. ESTADO "INITIAL":
   - Evalúa cualquier búsqueda o petición de notificación.
    - "documentos sin respuesta" → listar_sin_respuesta
    - "ver sin firma" → listar_sin_firma
    - "documentos inactivos" → listar_inactivos
    - "ver stand by" → listar_stand_by
    - "seguimiento PR-123" → seguimiento_por_codigo
    - "buscar cartas" → buscar_documentos
    - "hola" → saludo
    - "mis notificaciones" → listar_notificaciones
    - "contactar" → contactar_encargado
    - "contactar al responsable" → contactar_responsable
   - Si detecta una búsqueda o notificación, el 'next_state' sugerido debe ser "SEARCH_RESULTS" o "NOTIFICATION_LIST".

2. ESTADO "AWAITING_SELECTION" o "NOTIFICATION_SELECTION":
   - El usuario debe estar eligiendo algo de una lista.
   - Si la entrada es un número (ej: "1", "el dos") o un código de la lista, intent="seleccionar_opcion", next_state="DOCUMENT_DETAIL" (o "AWAITING_CONFIRMATION" si hay dudas).
   - Si hace una búsqueda totalmente nueva, ignora la lista: intent="buscar_documentos", next_state="SEARCH_RESULTS".

3. ESTADO "AWAITING_CONFIRMATION":
   - Esperando Sí/No.
   - Si "sí/correcto", intent="confirmar_seleccion" (positiva=true), next_state="DOCUMENT_DETAIL".
   - Si "no/incorrecto", intent="confirmar_seleccion" (positiva=false), next_state="INITIAL" o "AWAITING_SELECTION".

4. ESTADO "AWAITING_POST_DETAIL_DECISION":
   - Ocurre después de ver un documento.
   - Si dice "ver otro de la lista" -> intent="accion_post_detalle" (action="MORE_FROM_LIST"), next_state="AWAITING_SELECTION".
   - Si dice "buscar otro diferente" -> intent="accion_post_detalle" (action="NEW_SEARCH"), next_state="INITIAL".
   - Si dice "contactar responsable" -> intent="contactar_responsable", next_state="CONTACT_FLOW".

Salida requerida: SOLO un JSON válido, sin markdown adicional.
{{
    "intent": "nombre_intencion",
    "parameters": {{
        "numero_documento": "codigo_extraido",
        "codigo_sistema": "codigo_extraido",
        "posicion_lista": numero_entero_o_null,
        "confirmacion_positiva": true/false/null,
        "post_detail_action": "MORE_FROM_LIST|NEW_SEARCH|CONTACT|null",
        "is_follow_up": true/false
    }},
    "confidence": 0.95,
    "next_state": "AQUI_EL_ESTADO_DESTINO_SEGUN_REGLAS"
}}
"""
    
    intent_data = ask_gemini_json(prompt=prompt, temperature=0.1, max_tokens=300)
    
    if intent_data:
        print(f"✅ Gemini Router | Intent: {intent_data.get('intent')} | Next State: {intent_data.get('next_state')}")
    else:
        print("❌ El router no pudo obtener una respuesta válida de Gemini.")
        
    return intent_data