"""
whatsapp_handler.py
────────────────────
Responsabilidades:
  1. Extraer mensaje del payload de WhatsApp
  2. Autorizar usuario
  3. Detectar revisiones por botón de plantilla
  4. Llamar a procesar_mensaje
  5. Componer mensaje final (contenido + pregunta de seguimiento FSM)
  6. Guardar turno en memoria
  7. Retornar string para que el webhook lo envíe UNA sola vez
"""

from services.chatbot_service import *
from services.algolia_service import *
from services.ia_service import *
from core.constants import *
from core.states import State, PREGUNTA_SELECCION, PREGUNTA_CONFIRMACION, MENSAJE_POST_CONFIRMACION, MENSAJE_VOLVER_LISTA
from core.flow import *
from utils.formatter import *
from services.notificacion_services import *
from services.notificacion_services import notification_manager
from core.conversationMemory import conversation_memory

# ── EXTRACCIÓN ────────────────────────────────────────────────────────────────

def extract_message(data: dict) -> dict | None:
    try:
        changes = data['entry'][0]['changes'][0]
        value   = changes.get('value', {})
        if 'messages' not in value:
            return None

        message      = value['messages'][0]
        message_type = message.get('type')
        text, payload = '', ''

        if message_type == 'text':
            text = message.get('text', {}).get('body', '').strip()
        elif message_type == 'button':
            payload = message.get('button', {}).get('payload', '')
            text    = message.get('button', {}).get('text', '').strip()

        return {'phone': message.get('from'), 'text': text,
                'payload': payload, 'type': message_type}
    except (KeyError, IndexError):
        return None


# ── AUTORIZACIÓN ──────────────────────────────────────────────────────────────

def handle_authorization(usuario, phone: str, text: str) -> str | None:
    if usuario or 'chatbot' in text.lower():
        return None
    return (
        "👋 *¡Hola!*\n\n"
        "Este es el chatbot de ProRequest.\n"
        "No estás registrado.\n\n"
        "📞 Contacta con administración\n"
        "👤 Juan David\n"
        "📱 +51 957 133 488"
    )


# ── REVISIONES POR BOTÓN DE PLANTILLA ────────────────────────────────────────

TIPOS_REVISION = {
    # payloads de botón
    'revisar_sin_respuesta': 'sin_respuesta',
    'revisar_sin_firma':     'sin_firma',
    'revisar_inactivos':     'inactivos',
    'revisar_stand_by':      'stand_by',
    # textos equivalentes (mismo resultado que escribir el intent)
    'sin respuesta':         'sin_respuesta',
    'revisar sin respuesta': 'sin_respuesta',
    'sin firma':             'sin_firma',
    'revisar sin firma':     'sin_firma',
    'inactivos':             'inactivos',
    'inactivo':              'inactivos',
    'revisar inactivos':     'inactivos',
    'stand by':              'stand_by',
    'revisar stand by':      'stand_by',
}

def handle_revision_requests(phone: str, text: str, payload: str) -> str | None:
    """
    Detecta revisiones por botón o texto equivalente.
    Retorna el mensaje formateado (lista + pregunta) o None si no aplica.
    """
    tipo = TIPOS_REVISION.get(payload) or TIPOS_REVISION.get(text.lower())
    if not tipo:
        return None

    print(f"🔍 Revisión por plantilla: {tipo}")
    notifications = notification_manager.get_notifications_by_type(phone, tipo)

    if not notifications:
        return f"✅ No tienes documentos pendientes de tipo '{tipo}'."

    notification = notifications[0]
    documentos   = notification.get('documentos', [])

    conversation_memory.set_conversation_documents(
        phone_number=phone,
        documents=documentos,
        source_intent=f'notificacion_{tipo}',
        source_query=f'revision {tipo}'
    )
    conversation_memory.set_conversation_state(
        phone, State.AWAITING_SELECTION,
        {'has_document_list': True, 'notification_type': tipo}
    )
    notification_manager.mark_notification_as_viewed(phone, notification['id'])

    # Lista + pregunta = un solo mensaje
    lista = formatear_lista_documentos(documentos)
    return f"{lista}\n\n{PREGUNTA_SELECCION}"


# ── PROCESAMIENTO MENSAJE DE TEXTO ────────────────────────────────────────────

def handle_text_message(phone: str, text: str, usuario: dict) -> str | None:
    print(f"📩 [{phone}] {text}")

    conversation_memory.set_user_role(phone, usuario['nivel_acceso'])

    state   = conversation_memory.get_conversation_state(phone)
    context = conversation_memory.get_conversation_context(phone)

    print(f"🧠 Estado={state['state']} | Turnos={context['session_length']}")

    intent_forzado = _detectar_busqueda_forzada(text)

    resultado = procesar_mensaje(
        text, phone,
        conversation_state=state,
        conversation_context=context,
        intent_forzado=intent_forzado
    )

    return _construir_respuesta_final(phone, text, resultado, context)


def _detectar_busqueda_forzada(text: str) -> str | None:
    PALABRAS = {'buscar', 'busqueda', 'búsqueda', 'search'}
    if any(p in text.lower() for p in PALABRAS):
        return 'buscar_documentos'
    return None


# ── CONSTRUCCIÓN RESPUESTA FINAL ──────────────────────────────────────────────
#
#  REGLAS FSM:
#    tipo='lista'   → setear AWAITING_SELECTION  + agregar PREGUNTA_SELECCION
#    tipo='detalle' → setear AWAITING_CONFIRMATION + agregar PREGUNTA_CONFIRMACION
#    tipo='confirmacion_positiva' → setear INITIAL + agregar MENSAJE_POST_CONFIRMACION
#    tipo='confirmacion_negativa' → setear AWAITING_SELECTION + agregar MENSAJE_VOLVER_LISTA
#    otros          → no cambiar estado, no agregar pregunta
#
def _construir_respuesta_final(phone: str, user_text: str,
                                resultado: dict, context: dict) -> str | None:
    if not isinstance(resultado, dict):
        _guardar_turno(phone, user_text, str(resultado), 'general', {}, context)
        return str(resultado) or None

    contenido  = resultado.get('respuesta', '')
    tipo       = resultado.get('tipo', 'consulta')
    intent     = resultado.get('intent', 'unknown')
    parameters = resultado.get('parameters') or {}
    resultados = resultado.get('resultados') or []

    if not contenido:
        print('⚠️  procesar_mensaje no generó respuesta')
        return None

    # ── Transición FSM + pregunta de seguimiento ──────────────────────────────

    if tipo == 'lista':
        if resultados:
            conversation_memory.set_conversation_documents(
                phone_number=phone,
                documents=resultados,
                source_intent=intent,
                source_query=user_text
            )
        conversation_memory.set_conversation_state(
            phone, State.AWAITING_SELECTION,
            {'has_document_list': True, 'last_search_results_count': len(resultados)}
        )
        mensaje_final = f"{contenido}\n\n{PREGUNTA_SELECCION}"

    elif tipo == 'detalle':
        conversation_memory.set_conversation_state(phone, State.AWAITING_CONFIRMATION)
        mensaje_final = f"{contenido}\n\n{PREGUNTA_CONFIRMACION}"

    elif tipo == 'confirmacion_positiva':
        # Vuelve a INITIAL pero documentos siguen en memoria
        # Si el usuario escribe 'Hola' se limpian, si no puede seguir preguntando
        conversation_memory.set_conversation_state(phone, State.INITIAL)
        mensaje_final = f"{contenido}\n\n{MENSAJE_POST_CONFIRMACION}" if MENSAJE_POST_CONFIRMACION not in contenido else contenido

    elif tipo == 'confirmacion_negativa':
        # Vuelve a mostrar la lista anterior
        conversation_memory.set_conversation_state(phone, State.AWAITING_SELECTION)
        mensaje_final = f"{contenido}\n\n{MENSAJE_VOLVER_LISTA}"

    else:
        # consulta, saludo, error, contacto, ia, algolia → sin pregunta adicional
        mensaje_final = contenido

    # ── Guardar turno ─────────────────────────────────────────────────────────
    _guardar_turno(phone, user_text, mensaje_final, intent, parameters, context)

    print(f"📤 tipo='{tipo}' intent='{intent}' ({len(mensaje_final)} chars)")
    return mensaje_final


def _guardar_turno(phone: str, user_text: str, bot_response: str,
                   intent: str, parameters: dict, context: dict) -> None:
    conversation_memory.add_turn(
        phone=phone,
        user_message=user_text,
        bot_response=bot_response,
        intent=intent,
        parameters=parameters,
        context=context,
    )


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def process_whatsapp_message(message: dict) -> str | None:
    phone    = message['phone']
    text     = message['text']
    payload  = message['payload']
    msg_type = message['type']

    usuario = numero_autorizado(phone)

    auth = handle_authorization(usuario, phone, text)
    if auth:
        return auth

    revision = handle_revision_requests(phone, text, payload)
    if revision:
        return revision

    if msg_type == 'text':
        return handle_text_message(phone, text, usuario)

    return None