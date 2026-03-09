def handle_fallback(
    mensaje,
    numero_telefono,
    conversation_context,
    conversation_state
):

    respuesta_ia = consultar_ia_con_memoria(
        mensaje,
        conversation_context,
        conversation_state
    )

    if respuesta_ia:
        return {
            "tipo": "ia",
            "respuesta": respuesta_ia,
            "intent": "fallback"
        }

    return {
        "tipo": "error",
        "respuesta": "❌ No entendí tu consulta",
        "intent": "fallback"
    }