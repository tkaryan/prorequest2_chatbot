"""
handlers/notificaciones_handler.py
────────────────────────────────────
Handler para intents de listado de notificaciones.
Se llama desde procesar_mensaje cuando el intent es listar_sin_respuesta, etc.

Responsabilidad:
  - Obtener documentos del tipo solicitado
  - Guardarlos en conversation_memory
  - Setear estado FSM a AWAITING_SELECTION
  - Retornar respuesta estandarizada para que _construir_respuesta_final
    agregue la pregunta de selección automáticamente (tipo='lista')
"""

from core.states import State
from core.conversationMemory import ConversationMemory
from services.notificacion_services import notification_manager
from utils.formatter import formatear_lista_documentos

conversation_memory = ConversationMemory()

TIPO_MAP = {
    "listar_sin_respuesta": "sin_respuesta",
    "listar_sin_firma":     "sin_firma",
    "listar_inactivos":     "inactivos",
    "listar_stand_by":      "stand_by",
}


def handle_notificaciones(numero_telefono: str, intent: str) -> dict:
    """
    Maneja intents de listado de notificaciones.
    Retorna tipo='lista' para que whatsapp_handler agregue PREGUNTA_SELECCION.
    Retorna tipo='consulta' si no hay documentos (sin pregunta de seguimiento).
    """
    tipo = TIPO_MAP.get(intent)
    if not tipo:
        return {
            "tipo":       "error",
            "respuesta":  f"❌ Tipo de notificación desconocido: {intent}",
            "intent":     intent,
            "parameters": {}
        }

    notifications = notification_manager.get_notifications_by_type(numero_telefono, tipo)

    # Sin notificaciones
    if not notifications:
        return {
            "tipo":       "consulta",
            "respuesta":  f"✅ No tienes documentos pendientes de tipo '{tipo}'.",
            "intent":     intent,
            "parameters": {}
        }

    # Consolidar todos los documentos del tipo en una lista plana
    documentos = notification_manager.get_all_documents_by_type(numero_telefono, tipo)

    if not documentos:
        return {
            "tipo":       "consulta",
            "respuesta":  f"✅ No hay documentos en las notificaciones de tipo '{tipo}'.",
            "intent":     intent,
            "parameters": {}
        }

    # Persistir en memoria con source_intent para que flow.py sepa el origen
    conversation_memory.set_conversation_documents(
        phone_number=numero_telefono,
        documents=documentos,
        source_intent=f"notificacion_{tipo}",
        source_query=f"Notificaciones {tipo}"
    )

    # Setear estado FSM — whatsapp_handler también lo hará al ver tipo='lista',
    # pero setearlo aquí garantiza consistencia si algo falla después
    conversation_memory.set_conversation_state(
        numero_telefono,
        State.AWAITING_SELECTION,
        {
            "has_document_list":          True,
            "notification_type":          tipo,
            "last_search_results_count":  len(documentos),
        }
    )

    # Marcar la primera notificación como vista
    if notifications[0].get("id"):
        notification_manager.mark_notification_as_viewed(
            numero_telefono,
            notifications[0]["id"]
        )

    respuesta = formatear_lista_documentos(documentos)

    return {
        "tipo":       "lista",           
        "respuesta":  respuesta,
        "intent":     intent,
        "parameters": {"results_count": len(documentos)},
        "resultados": documentos,
        "notification_type": tipo,
    }