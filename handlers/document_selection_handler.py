def handle_document_selection(
    numero_telefono,
    mensaje,
    intent_data,
    conversation_state
):

    documentos = conversation_memory.get_conversation_documents(numero_telefono)

    if not documentos:
        return {
            "tipo": "error",
            "respuesta": "❌ No hay documentos disponibles.",
            "intent": "seleccionar_documento"
        }

    resultado = seleccionar_respuesta(
        mensaje,
        None,
        documentos,
        conversation_state
    )

    docs = resultado.get("documentos_encontrados")

    if len(docs) == 1:

        doc = docs[0]

        respuesta = formatear_documento_detalle_notificacion(doc)

        return {
            "tipo": "detalle",
            "respuesta": respuesta,
            "intent": "seleccionar_documento",
            "resultados": [doc]
        }

    return {
        "tipo": "lista",
        "respuesta": formatear_lista_documentos(docs),
        "intent": "seleccionar_documento",
        "resultados": docs
    }