"""
services/whatsapp_handler.py
─────────────────────────────
Lógica del webhook WhatsApp, separada del routing Flask.

Responsabilidades:
  - Parsear mensajes entrantes (texto, botón)
  - Autorizar números
  - Detectar tipo de revisión de notificación (botón o texto)
  - Delegar a chatbot_service.procesar_mensaje
  - Enviar respuestas vía WhatsApp API
  - Actualizar conversation_memory con el resultado
"""

from typing import Any, Dict, List, Optional
from flask import jsonify

from core.conversationMemory import conversation_memory
from core.states import State, PREGUNTA_SELECCION, PREGUNTA_CONFIRMACION
from config import WHATSAPP_VERIFY_TOKEN
from services.chatbot_service import procesar_mensaje
from services.notificacion_services import notification_manager
from services.chatbot_service import formatear_lista_documentos
from utils.whatsapp import enviar_mensaje_whatsapp, normalizar_numero_whatsapp, numero_autorizado

# Cache anti-duplicados (en producción usar Redis con TTL)
_processed_ids: set = set()

# Payloads/textos que disparan revisión de notificación
_TIPOS_REVISION: Dict[str, str] = {
    # payloads de botón
    "revisar_sin_respuesta":  "sin_respuesta",
    "revisar_sin_firma":      "sin_firma",
    "revisar_inactivos":      "inactivos",
    "revisar_stand_by":       "stand_by",
    # textos equivalentes
    "sin respuesta":          "sin_respuesta",
    "sin firma":              "sin_firma",
    "inactivos":              "inactivos",
    "inactivo":               "inactivos",
    "stand by":               "stand_by",
    "revisar sin respuesta":  "sin_respuesta",
    "revisar sin firma":      "sin_firma",
    "revisar inactivos":      "inactivos",
    "revisar inactivo":       "inactivos",
    "revisar stand by":       "stand_by",
}

_PALABRAS_BUSQUEDA = {"buscar", "busqueda", "búsqueda", "search"}


# ── ENTRY POINTS ──────────────────────────────────────────────────────────────

def handle_webhook_get(request):
    """Verificación del webhook de WhatsApp."""
    token     = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if token == WHATSAPP_VERIFY_TOKEN:
        print("✅ Webhook verificado")
        return challenge
    print("❌ Token inválido")
    return 'Token inválido', 403


def handle_webhook_post(request):
    """Procesa mensajes entrantes."""
    try:
        data = request.get_json()

        # Validar estructura mínima
        entry = (data.get('entry') or [{}])[0]
        changes = (entry.get('changes') or [{}])[0]
        value = changes.get('value', {})

        if 'messages' not in value:
            return jsonify({'status': 'no_messages'}), 200

        message = value['messages'][0]
        return _procesar_mensaje_whatsapp(message)

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"❌ Error en webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── PROCESAMIENTO DE MENSAJE ──────────────────────────────────────────────────

def _procesar_mensaje_whatsapp(message: Dict) -> Any:
    # Anti-duplicados
    msg_id = message.get('id', '')
    if msg_id and msg_id in _processed_ids:
        print(f"⚠️  Duplicado ignorado: {msg_id}")
        return jsonify({'status': 'duplicate'}), 200
    if msg_id:
        _processed_ids.add(msg_id)
        if len(_processed_ids) > 1000:
            _processed_ids.clear()

    numero = message['from']
    tipo   = message.get('type')

    # Extraer payload y texto
    button_payload = ""
    texto          = ""

    if tipo == 'button':
        button_payload = message.get('button', {}).get('payload', '')
        texto          = message.get('button', {}).get('text', '').lower().strip()
    elif tipo == 'text':
        texto = message.get('text', {}).get('body', '').lower().strip()
    else:
        return jsonify({'status': 'unsupported_type'}), 200

    # Autorización
    usuario = numero_autorizado(numero)
    if not usuario:
        if "chatbot" not in texto:
            enviar_mensaje_whatsapp(numero, _mensaje_no_autorizado())
        return jsonify({'status': 'unauthorized'}), 200  # 200 para que WhatsApp no reintente

    # ── ¿Es revisión de notificación? ────────────────────────────────────────
    tipo_revision = _TIPOS_REVISION.get(button_payload) or _TIPOS_REVISION.get(texto)

    if tipo_revision:
        return _handle_revision_notificacion(numero, tipo_revision)

    # ── Mensaje normal → chatbot_service ─────────────────────────────────────
    if tipo == 'text':
        return _handle_texto_normal(numero, texto, usuario)

    return jsonify({'status': 'success'}), 200


def _handle_revision_notificacion(numero: str, tipo_revision: str) -> Any:
    """Usuario presionó botón o escribió para revisar un tipo de notificación."""
    print(f"🔔 Revisión solicitada: [{tipo_revision}] para {numero}")

    notifications = notification_manager.get_notifications_by_type(numero, tipo_revision)

    if not notifications:
        enviar_mensaje_whatsapp(numero,
            f"✅ No tienes notificaciones pendientes de tipo *{tipo_revision.replace('_', ' ')}*.")
        return jsonify({'status': 'success'}), 200

    # Tomar el grupo más reciente
    notification = notifications[0]
    documentos   = notification.get('documentos', [])

    print(f"📄 {len(documentos)} docs para {numero} [{tipo_revision}]")

    # Mostrar lista
    respuesta_lista = formatear_lista_documentos(documentos)
    enviar_mensaje_whatsapp(numero, respuesta_lista)

    # Guardar docs en memoria
    conversation_memory.set_conversation_documents(
        phone=numero,
        documents=documentos,
        source_intent=f"notificacion_{tipo_revision}",
        source_query=f"Revisión: {tipo_revision}"
    )

    # Actualizar estado
    conversation_memory.set_conversation_state(
        phone=numero,
        state=State.AWAITING_SELECTION,
        additional_info={
            "has_document_list":         True,
            "last_search_results_count": len(documentos),
            "is_notification_flow":      True,
            "pending_notification_tipo": tipo_revision,
            "notification_id":           notification.get('id'),
        }
    )

    # Marcar como vista y enviar pregunta
    notification_manager.mark_notification_as_viewed(numero, notification['id'])
    enviar_mensaje_whatsapp(numero, PREGUNTA_SELECCION)

    return jsonify({'status': 'success'}), 200


def _handle_texto_normal(numero: str, texto: str, usuario: Dict) -> Any:
    """Procesa mensaje de texto libre."""
    # Rol en memoria
    conversation_memory.set_user_role(numero, usuario.get("nivel_acceso", "user"))

    conv_state = conversation_memory.get_conversation_state(numero)
    conv_ctx   = conversation_memory.get_conversation_context(numero)

    print(f"🧠 Estado={conv_state['state']} | Turnos={conv_ctx['session_length']}")

    # Detectar intent forzado
    intent_forzado = None
    if any(p in texto for p in _PALABRAS_BUSQUEDA):
        intent_forzado = "buscar_documentos"

    # Procesar
    resultado = procesar_mensaje(
        mensaje=texto,
        numero_telefono=numero,
        conversation_state=conv_state,
        conversation_context=conv_ctx,
        intent_forzado=intent_forzado,
    )

    print(f"🔍 Resultado: tipo={resultado.get('tipo')} intent={resultado.get('intent')}")

    # Extraer respuesta
    respuesta = resultado.get("respuesta")
    if isinstance(respuesta, dict):
        respuesta = respuesta.get("contenido") or respuesta.get("message") or str(respuesta)

    tipo_resp  = resultado.get("tipo", "consulta")
    intent     = resultado.get("intent", "unknown")
    parameters = resultado.get("parameters", {})

    if not respuesta:
        print("⚠️  Sin respuesta generada")
        return jsonify({'status': 'success'}), 200

    # Enviar respuesta principal
    if not enviar_mensaje_whatsapp(numero, respuesta):
        print(f"❌ Error enviando a {numero}")
        return jsonify({'status': 'send_error'}), 200

    # Guardar turno
    message_type = _determinar_message_type(tipo_resp, intent)
    conversation_memory.add_turn(
        phone=numero,
        user_message=texto,
        bot_response=respuesta,
        intent=intent,
        parameters=parameters,
        context=conv_ctx,
        message_type=message_type,
    )

    # Guardar resultados en memoria
    resultados = resultado.get("resultados") or parameters.get("resultados")
    if resultados and isinstance(resultados, list):
        conversation_memory.set_conversation_documents(
            phone=numero,
            documents=resultados,
            source_intent=intent,
            source_query=texto,
        )

    # Enviar pregunta de seguimiento si corresponde
    pregunta = resultado.get("pregunta_seguimiento")
    if pregunta:
        enviar_mensaje_whatsapp(numero, pregunta)
    elif tipo_resp == "lista":
        enviar_mensaje_whatsapp(numero, PREGUNTA_SELECCION)
    elif tipo_resp in ("detalle", "select_document"):
        enviar_mensaje_whatsapp(numero, PREGUNTA_CONFIRMACION)

    # Post-confirmación
    if intent == "confirmar_seleccion":
        _handle_post_confirmacion(numero, parameters, conv_state)

    return jsonify({'status': 'success'}), 200


def _handle_post_confirmacion(numero: str, parameters: Dict, conv_state: Dict) -> None:
    """Envía mensaje contextual después de una confirmación."""
    positiva = parameters.get("confirmacion_positiva", False)
    estado   = conv_state.get("state")

    if positiva:
        if estado == State.AWAITING_SELECTION:
            enviar_mensaje_whatsapp(numero,
                "Perfecto! Ahora puedes hacer consultas específicas sobre estos documentos. "
                "¿En qué más te puedo ayudar?")
        else:
            enviar_mensaje_whatsapp(numero,
                "¡Perfecto! ¿Necesitas algo más? Escribe *'hola'* para empezar de nuevo.")
    else:
        enviar_mensaje_whatsapp(numero,'')


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _determinar_message_type(tipo_resp: str, intent: str) -> str:
    if tipo_resp in ("detalle", "select_document", "notificacion_seleccionada"):
        return "verificacion"
    if tipo_resp == "lista":
        return "eleccion"
    if intent == "confirmar_seleccion":
        return "confirmacion"
    return "consulta"


def _mensaje_no_autorizado() -> str:
    return (
        "👋 *¡Hola!*\n\n"
        "Este es el chatbot de ProRequest. "
        "Actualmente no estás registrado en nuestro sistema.\n\n"
        "📞 *Para agregar tus datos:*\n"
        "Comunicarse con la administración\n"
        "👤 *Juan David*\n📱 +51 957 133 488"
    )