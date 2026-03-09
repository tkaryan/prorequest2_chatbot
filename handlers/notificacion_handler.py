"""
services/notificacion_handler.py
──────────────────────────────────
Lógica de los endpoints /api/notificacion y /api/notificacion/derivado.
Separada de app.py para mantener las rutas Flask limpias.
"""

from collections import defaultdict
from typing import List
from core.states import State
from flask import jsonify
from core.conversationMemory import conversation_memory
from services.notificacion_services import notification_manager
from utils.whatsapp import (
    enviar_plantilla_whatsapp,
    normalizar_numero_whatsapp,
    numero_autorizado,
)


_PLANTILLAS: dict = {
    'documentos_inactivos_masivo':   {'nombre': 'alerta_documentos_inactivos'},
    'documentos_en_stand_by_masivo': {'nombre': 'documentos_stand_by'},
    'documentos_en_firma_masivo':    {'nombre': 'documento_sin_firma'},
    'documentos_antiguos_masivo':    {'nombre': 'documento_sin_respuesta'},
}


def handle_notificacion(request):
    """POST /api/notificacion — notificaciones masivas."""
    try:
        data       = request.get_json()
        tipo       = data.get('tipo')
        cantidad   = data.get('cantidad', 0)
        documentos = data.get('documentos', [])

        if not documentos:
            return jsonify({"error": "No hay documentos en el payload"}), 400

        # Agrupar por destinatario
        por_usuario = defaultdict(list)
        for doc in documentos:
            for tel in doc.get('destinatarios', []):
                tel_norm = normalizar_numero_whatsapp(tel)
                if numero_autorizado(tel_norm):
                    por_usuario[tel_norm].append(doc)
                else:
                    print(f"⚠️  No autorizado: {tel_norm}")

        resultados = {'exitosos': 0, 'fallidos': 0, 'detalles': []}

        for telefono, docs_usuario in por_usuario.items():
            try:
                usuario_info  = numero_autorizado(telefono)
                nombre        = usuario_info.get('nombres', 'Usuario') if usuario_info else 'Usuario'
                cantidad_docs = len(docs_usuario)

                # 1. Guardar en notification_manager
                grupo = notification_manager.store_notifications(
                    phone_number=telefono,
                    notifications_data={"tipo": tipo, "cantidad": cantidad_docs,
                                        "documentos": docs_usuario}
                )
                if not grupo:
                    raise Exception("Error almacenando en notification_manager")

                # 2. Pre-cargar en conversation_memory + guardar tipo_interno en estado
                tipo_interno = notification_manager._identificar_tipo(tipo)
                conversation_memory.set_conversation_documents(
                    phone=telefono,
                    documents=docs_usuario,
                    source_intent=f"notificacion_{tipo_interno}",
                    source_query=f"Notificación: {tipo}"
                )
                s = conversation_memory._get_or_create_state(telefono)
                s["pending_notification_tipo"] = tipo_interno
                conversation_memory._b.set_state(telefono, s)

                print(f"📚 {cantidad_docs} docs pre-cargados para {telefono}")

                # 3. Enviar plantilla
                if tipo not in _PLANTILLAS:
                    raise Exception(f"Tipo no soportado: {tipo}")

                config     = _PLANTILLAS[tipo]
                parametros = [str(cantidad_docs), nombre, str(cantidad_docs)]

                resultado = enviar_plantilla_whatsapp(
                    numero=telefono,
                    nombre_plantilla=config['nombre'],
                    parametros=parametros,
                    idioma="es_PE"
                )

                if resultado.get('status') == 'success':
                    notification_manager.template_message_ids[grupo['id']] = resultado.get('message_id')
                    resultados['exitosos'] += 1
                    resultados['detalles'].append({
                        'telefono': telefono, 'documentos': cantidad_docs,
                        'status': 'success', 'tipo': tipo,
                        'plantilla': config['nombre'], 'notification_id': grupo['id'],
                        'message_id': resultado.get('message_id')
                    })
                else:
                    raise Exception(resultado.get('message', 'Error desconocido'))

            except Exception as e:
                import traceback; traceback.print_exc()
                print(f"❌ Error para {telefono}: {e}")
                resultados['fallidos'] += 1
                resultados['detalles'].append({'telefono': telefono, 'status': 'error', 'error': str(e)})

        return jsonify({
            'status': 'success',
            'message': f'{resultados["exitosos"]} exitosas, {resultados["fallidos"]} fallidas',
            'tipo': tipo, 'total_usuarios': len(por_usuario),
            'total_documentos': cantidad, 'resultados': resultados,
        }), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


def handle_notificacion_derivado(request):
    """POST /api/notificacion/derivado — notificación de documento derivado."""
    try:
        data = request.get_json()

        telefono = data.get('telefono')
        if not telefono:
            return jsonify({"error": "Falta el teléfono"}), 400

        def limpiar(v, default="-"):
            return default if v is None or str(v).strip() == "" else str(v)

        nombre           = limpiar(data.get('nombre'), "Usuario")
        numero_documento = limpiar(data.get('numero_documento'))
        asunto           = limpiar(data.get('asunto'))
        proyecto         = limpiar(data.get('proyecto'), "Sin proyecto")
        encargado        = limpiar(data.get('encargado'), "Sin asignar")
        fecha_ingreso    = limpiar(data.get('fecha_ingreso'))
        link             = limpiar(data.get('link'), "https://prorequest.com")

        tel_norm = normalizar_numero_whatsapp(telefono)
        if not numero_autorizado(tel_norm):
            return jsonify({"error": "Número no autorizado"}), 403

        resultado = enviar_plantilla_whatsapp(
            numero=tel_norm,
            nombre_plantilla="derivados_prueba",
            parametros=[nombre, numero_documento, asunto, proyecto, encargado, fecha_ingreso, link],
            idioma="es_PE",
            tiene_boton=False
        )

        if resultado.get('status') == 'success':
            return jsonify({
                'status': 'success',
                'tipo': 'documento_derivado',
                'telefono': tel_norm,
                'numero_documento': numero_documento,
                'message_id': resultado.get('message_id'),
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': resultado.get('message', 'Error al enviar'),
                'details': resultado.get('details', {}),
            }), 500

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


def procesar_notificacion_seleccionada(mensaje: str, numero_telefono: str, intent_data: dict) -> dict:
    """
    Formatea el detalle de un documento seleccionado desde la lista de notificación.

    Dos rutas:
    1. _doc_preresuelto=True → el doc ya viene en intent_data["documento_seleccionado"]
       (lo resolvió flow.py/_handle_awaiting_selection via Python/Gemini)
    2. Normal → busca por índice/código en notification_manager
    """
    try:
        # ── Ruta 1: doc ya resuelto por el FSM ───────────────────────────────
        if intent_data.get("_doc_preresuelto"):
            doc = intent_data["documento_seleccionado"]
            respuesta = _formatear_detalle_doc(doc)

            conversation_memory.set_conversation_state(
                numero_telefono, State.AWAITING_CONFIRMATION,
                {"is_notification_flow": True, "has_document_list": True}
            )
            return {
                "tipo":       "notificacion_seleccionada",
                "respuesta":  respuesta,
                "intent":     "seleccionar_notificacion",
                "parameters": {"documento": doc},
                "pregunta_seguimiento": "¿El documento es lo que estabas buscando?",
            }

        # ── Ruta 2: buscar por índice ─────────────────────────────────────────
        parametro = (
            intent_data.get("parametro")
            or intent_data.get("notification_index")
            or (intent_data.get("documento_seleccionado") or {}).get("posicion_lista")
        )

        if parametro is None:
            return {"tipo": "error", "respuesta": "❌ No especificaste qué notificación ver.",
                    "intent": "error", "parameters": {}}

        notification = notification_manager.get_notification_by_index(numero_telefono, parametro)
        if not notification:
            return {"tipo": "error",
                    "respuesta": f"❌ No encontré la notificación #{parametro}.",
                    "intent": "error", "parameters": {}}

        notification_manager.mark_notification_as_viewed(numero_telefono, notification["id"])
        respuesta = _formatear_detalle_notificacion(notification)

        conversation_memory.set_conversation_state(
            numero_telefono, State.AWAITING_CONFIRMATION,
            {"is_notification_flow": True, "has_document_list": True,
             "last_viewed_notification": notification.get("id")}
        )
        return {
            "tipo":       "notificacion_seleccionada",
            "respuesta":  respuesta,
            "intent":     "seleccionar_notificacion",
            "parameters": {"notification": notification},
            "pregunta_seguimiento": "¿El documento es lo que estabas buscando?",
        }

    except Exception as e:
        import traceback; traceback.print_exc()
        return {"tipo": "error", "respuesta": "❌ Error procesando la notificación.",
                "intent": "error", "parameters": {}}

def _formatear_detalle_doc(doc: dict) -> str:
    """
    Formatea un doc en la estructura que guarda conversation_memory:
    { "documento": {...}, "proyecto": {...}, "encargados": [...], ... }
    """
    inner       = doc.get("documento", doc)
    proyecto    = doc.get("proyecto", {})
    encargados  = doc.get("encargados", [])
    responsables = doc.get("responsables", [])

    codigo  = inner.get("codigo_sistema", "N/A")
    numero  = inner.get("numero_documento", "N/A")
    asunto  = inner.get("asunto", "Sin asunto")
    estado  = inner.get("estado", "N/A")
    fecha   = inner.get("fecha_ingreso", "N/A")
    dias    = inner.get("dias_inactivo")
    proy    = (proyecto.get("nombre") if isinstance(proyecto, dict) else str(proyecto)) or "N/A"

    def _nombres(lista):
        if not lista: return "N/A"
        first = lista[0]
        if isinstance(first, dict):
            return ", ".join(
                f"{e.get('nombres','')} {e.get('apellido_paterno','')}".strip()
                for e in lista
            )
        return ", ".join(str(e) for e in lista)

    enc  = _nombres(encargados)
    resp = _nombres(responsables)

    msg = (
        f"⚠️ *Alerta de Documento* ⚠️\n"
        f"⏱️ Han pasado *15 días sin movimiento*.\n\n"
        f"📄 *Documento:* {numero}\n"
        f"🆔 *Código:* {codigo}\n"
        f"📋 *Asunto:* {asunto}\n"
        f"🏗️ *Proyecto:* {proy}\n"
        f"👤 *Encargado:* {enc}\n"
        f"🔄 *Estado:* {estado}\n"
        f"📅 *Fecha Ingreso:* {fecha}"
    )
    if dias is not None:
        msg += f"\n⏱️ *Días inactivo:* {dias}"
    if resp and resp != "N/A":
        msg += f"\n🏗️ *Responsable:* {resp}"
    msg += "\n\n💬 Responde *'contactar encargado'* para enviar mensaje"
    return msg


def _formatear_detalle_notificacion(notification: dict) -> str:
    payload     = notification.get('payload', {})
    documento   = payload.get('documento', {})
    proyecto    = payload.get('proyecto', {})
    encargados  = payload.get('encargados', [])
    responsables = payload.get('responsables', [])

    codigo   = notification.get('codigo_sistema') or documento.get('codigo_sistema', 'N/A')
    numero   = notification.get('numero_documento') or documento.get('numero_documento', 'N/A')
    asunto   = documento.get('asunto', 'Sin asunto')
    estado   = documento.get('estado', 'N/A')
    fecha    = documento.get('fecha_ingreso', 'N/A')
    dias     = documento.get('dias_inactivo')
    proyecto_nombre = (proyecto.get('nombre') if isinstance(proyecto, dict) else str(proyecto)) or 'N/A'

    def _nombres(lista):
        if not lista:
            return "N/A"
        first = lista[0]
        if isinstance(first, dict):
            return ", ".join(
                f"{e.get('nombres','')} {e.get('apellido_paterno','')}".strip()
                for e in lista
            )
        return ", ".join(str(e) for e in lista)

    enc  = _nombres(encargados)
    resp = _nombres(responsables)

    msg = f"""
        ⚠️ *Alerta de Documento* ⚠️
        ⏱️ Han pasado *15 días sin movimiento*.  
        Por favor, revisa y actualiza su estado a *"Atendido"* si corresponde. 🙏

        📄 *Documento:* {numero}  
        🆔 *Código sistema:* {codigo}  
        📋 *Asunto:* {asunto}  
        🏗️ *Proyecto:* {proyecto_nombre}  
        👤 *Encargado:* {enc}  
        🔄 *Estado:* {estado}  
        📅 *Fecha Ingreso:* {fecha}

   
    """

    
    if dias is not None:
        msg += f"\n⏱️ *Días inactivo:* {dias}"
    msg += f"\n\n💡 *¿Quieres contactar?*  \n👤 *Encargado:* {enc}"

    if responsables:
        mensaje += f"\n🏗️ *Responsable proyecto:* {responsables}"
    return msg


def handle_notificacion(request):
    """POST /api/notificacion — notificaciones masivas."""
    try:
        data       = request.get_json()
        tipo       = data.get('tipo')
        cantidad   = data.get('cantidad', 0)
        documentos = data.get('documentos', [])

        if not documentos:
            return jsonify({"error": "No hay documentos en el payload"}), 400

        # Agrupar por destinatario
        por_usuario = defaultdict(list)
        for doc in documentos:
            for tel in doc.get('destinatarios', []):
                tel_norm = normalizar_numero_whatsapp(tel)
                if numero_autorizado(tel_norm):
                    por_usuario[tel_norm].append(doc)
                else:
                    print(f"⚠️  No autorizado: {tel_norm}")

        resultados = {'exitosos': 0, 'fallidos': 0, 'detalles': []}

        for telefono, docs_usuario in por_usuario.items():
            try:
                usuario_info  = numero_autorizado(telefono)
                nombre        = usuario_info.get('nombres', 'Usuario') if usuario_info else 'Usuario'
                cantidad_docs = len(docs_usuario)

                # 1. Guardar en notification_manager
                grupo = notification_manager.store_notifications(
                    phone_number=telefono,
                    notifications_data={"tipo": tipo, "cantidad": cantidad_docs,
                                        "documentos": docs_usuario}
                )
                if not grupo:
                    raise Exception("Error almacenando en notification_manager")

                # 2. Pre-cargar en conversation_memory + guardar tipo_interno en estado
                tipo_interno = notification_manager._identificar_tipo(tipo)
                conversation_memory.set_conversation_documents(
                    phone=telefono,
                    documents=docs_usuario,
                    source_intent=f"notificacion_{tipo_interno}",
                    source_query=f"Notificación: {tipo}"
                )
                s = conversation_memory._get_or_create_state(telefono)
                s["pending_notification_tipo"] = tipo_interno
                conversation_memory._b.set_state(telefono, s)

                print(f"📚 {cantidad_docs} docs pre-cargados para {telefono}")

                # 3. Enviar plantilla
                if tipo not in _PLANTILLAS:
                    raise Exception(f"Tipo no soportado: {tipo}")

                config     = _PLANTILLAS[tipo]
                parametros = [str(cantidad_docs), nombre, str(cantidad_docs)]

                resultado = enviar_plantilla_whatsapp(
                    numero=telefono,
                    nombre_plantilla=config['nombre'],
                    parametros=parametros,
                    idioma="es_PE"
                )

                if resultado.get('status') == 'success':
                    notification_manager.template_message_ids[grupo['id']] = resultado.get('message_id')
                    resultados['exitosos'] += 1
                    resultados['detalles'].append({
                        'telefono': telefono, 'documentos': cantidad_docs,
                        'status': 'success', 'tipo': tipo,
                        'plantilla': config['nombre'], 'notification_id': grupo['id'],
                        'message_id': resultado.get('message_id')
                    })
                else:
                    raise Exception(resultado.get('message', 'Error desconocido'))

            except Exception as e:
                import traceback; traceback.print_exc()
                print(f"❌ Error para {telefono}: {e}")
                resultados['fallidos'] += 1
                resultados['detalles'].append({'telefono': telefono, 'status': 'error', 'error': str(e)})

        return jsonify({
            'status': 'success',
            'message': f'{resultados["exitosos"]} exitosas, {resultados["fallidos"]} fallidas',
            'tipo': tipo, 'total_usuarios': len(por_usuario),
            'total_documentos': cantidad, 'resultados': resultados,
        }), 200

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


def handle_notificacion_derivado(request):
    """POST /api/notificacion/derivado — notificación de documento derivado."""
    try:
        data = request.get_json()

        telefono = data.get('telefono')
        if not telefono:
            return jsonify({"error": "Falta el teléfono"}), 400

        def limpiar(v, default="-"):
            return default if v is None or str(v).strip() == "" else str(v)

        nombre           = limpiar(data.get('nombre'), "Usuario")
        numero_documento = limpiar(data.get('numero_documento'))
        asunto           = limpiar(data.get('asunto'))
        proyecto         = limpiar(data.get('proyecto'), "Sin proyecto")
        encargado        = limpiar(data.get('encargado'), "Sin asignar")
        fecha_ingreso    = limpiar(data.get('fecha_ingreso'))
        link             = limpiar(data.get('link'), "https://prorequest.com")

        tel_norm = normalizar_numero_whatsapp(telefono)
        if not numero_autorizado(tel_norm):
            return jsonify({"error": "Número no autorizado"}), 403

        resultado = enviar_plantilla_whatsapp(
            numero=tel_norm,
            nombre_plantilla="derivados_prueba",
            parametros=[nombre, numero_documento, asunto, proyecto, encargado, fecha_ingreso, link],
            idioma="es_PE",
            tiene_boton=False
        )

        if resultado.get('status') == 'success':
            return jsonify({
                'status': 'success',
                'tipo': 'documento_derivado',
                'telefono': tel_norm,
                'numero_documento': numero_documento,
                'message_id': resultado.get('message_id'),
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': resultado.get('message', 'Error al enviar'),
                'details': resultado.get('details', {}),
            }), 500

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
