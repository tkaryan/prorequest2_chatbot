"""
services/chatbot_service.py
────────────────────────────
Orquestador principal. Recibe mensaje + contexto → devuelve respuesta estructurada.

Flujo:
  procesar_mensaje
    → detectar_intencion_con_contexto  (flow.py / ia/router.py)
    → ejecutar handler según intent
    → guardar turno en conversation_memory
    → retornar dict {tipo, respuesta, intent, parameters, resultados}
"""

from typing import Any, Dict, List, Optional

from core.conversationMemory import conversation_memory
from core.flow import detectar_intencion_con_contexto
from core.states import State, PREGUNTA_CONFIRMACION, PREGUNTA_SELECCION, MENSAJE_VOLVER_LISTA
from core.constants import SUGERENCIAS_BUSQUEDA

from services.notificacion_services import notification_manager
from services.db_service import (
    consultar_por_numero_documento,
    consultar_por_codigo_sistema,
    consultar_documentos_por_usuario,
    consultar_documentos_por_proyecto,
    consultar_documento_por_asunto,
    consultar_por_numero_consecutivo,
)
from services.algolia_service import generar_respuesta_busqueda_algolia
from utils.formatter import formatear_seguimiento


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def procesar_mensaje(
    mensaje: str,
    numero_telefono: str,
    conversation_state: Dict = None,
    conversation_context: Dict = None,
    intent_forzado: str = None,
) -> Dict[str, Any]:
    """Procesa un mensaje entrante y devuelve la respuesta estructurada."""
    try:
        # Reset manual
        if mensaje.lower().strip() in {"hola", "hello", "hi"}:
            conversation_memory._reset(numero_telefono)
            return _mk("saludo", _respuesta_saludo(), "saludo", {"reset_triggered": True})

        if conversation_context is None:
            conversation_context = conversation_memory.get_conversation_context(numero_telefono)
        if conversation_state is None:
            conversation_state = conversation_memory.get_conversation_state(numero_telefono)

        # ── Recuperar docs en memoria (con fallback a notification_manager) ──
        documentos = _recuperar_documentos(numero_telefono, conversation_state)

        should_filter = (
            not conversation_state.get("should_search_full_db", True)
            and bool(documentos)
        )
        if should_filter:
            print(f"📚 Modo filtrado: {len(documentos)} docs")

        # ── Detección de intención ────────────────────────────────────────────
        intent_data = detectar_intencion_con_contexto(
            mensaje, numero_telefono, conversation_context, conversation_state
        )
        if not intent_data:
            return _error("❌ No pude procesar tu mensaje. Intenta de nuevo.")

        intent    = intent_data.get("intent", "unknown")
        parametro = intent_data.get("parametro")

        print(f"🎯 Intent={intent} | Param={parametro} | Estado={conversation_state.get('state')}")

        # ── Bloque AWAITING_SELECTION ─────────────────────────────────────────
        estado = conversation_state.get("state")
        if estado == State.AWAITING_SELECTION and intent not in (
            "error_seleccion_lista", "error_seleccion_notificacion", "saludo"
        ):
            return _handle_awaiting_selection(
                intent, intent_data, documentos, numero_telefono, mensaje
            )

        # ── Chain de intents ──────────────────────────────────────────────────
        return _dispatch(
            intent, intent_data, parametro, mensaje,
            numero_telefono, conversation_context, conversation_state,
            documentos, should_filter, intent_forzado,
        )

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"❌ Error en procesar_mensaje: {e}")
        return _error("❌ Disculpa, ocurrió un error interno. Inténtalo de nuevo.")


# ── AWAITING SELECTION ────────────────────────────────────────────────────────

def _handle_awaiting_selection(
    intent: str,
    intent_data: Dict,
    documentos: List[Dict],
    numero_telefono: str,
    mensaje: str,
) -> Dict[str, Any]:
    """
    Maneja la selección de un documento de la lista.
    El FSM (flow.py) ya resolvió el match; aquí solo formateamos y actualizamos estado.

    Si la lista viene de una notificación (is_notification_flow=True) usa
    procesar_notificacion_seleccionada para el formato detallado de alerta.
    Si viene de búsqueda normal usa formatear_seguimiento.
    """
    if intent != "seleccionar_documento":
        print(f"⚠️  Intent '{intent}' inesperado en AWAITING_SELECTION")
        return _error("❌ No entendí tu selección. Intenta con número o código.")

    doc = intent_data.get("documento_seleccionado")
    if not doc:
        return _error("❌ No encontré ese documento en la lista.")

    # ── ¿Viene de notificación? ───────────────────────────────────────────────
    conv_state = conversation_memory.get_conversation_state(numero_telefono)
    es_notificacion = (
        conv_state.get("is_notification_flow", False)
        or (documentos and documentos[0].get("source_intent", "").startswith("notificacion_"))
    )

    if es_notificacion:
        from services.notificacion_handler import procesar_notificacion_seleccionada
        # Inyectar el doc ya resuelto en intent_data para que el handler lo use directamente
        intent_data["documento_seleccionado"] = doc
        intent_data["_doc_preresuelto"]       = True
        return procesar_notificacion_seleccionada(mensaje, numero_telefono, intent_data)

    # ── Búsqueda normal ───────────────────────────────────────────────────────
    formato   = formatear_seguimiento(doc)
    respuesta = formato["contenido"] if isinstance(formato, dict) else formato
    tipo      = formato.get("tipo", "detalle") if isinstance(formato, dict) else "detalle"

    conversation_memory.set_conversation_state(
        numero_telefono, State.AWAITING_CONFIRMATION, {"has_document_list": True}
    )
    return {
        "tipo":       tipo,
        "respuesta":  respuesta,
        "intent":     intent,
        "parameters": {"documento": doc},
        "resultados": intent_data.get("resultados"),
        "pregunta_seguimiento": PREGUNTA_CONFIRMACION,
    }


# ── DISPATCH DE INTENTS ───────────────────────────────────────────────────────

def _dispatch(
    intent: str, intent_data: Dict, parametro: Optional[str],
    mensaje: str, numero_telefono: str,
    conversation_context: Dict, conversation_state: Dict,
    documentos: List[Dict], should_filter: bool, intent_forzado: Optional[str],
) -> Dict[str, Any]:

    if intent == "saludo":
        return _mk("saludo", _respuesta_saludo_contextual(conversation_context), "saludo")

    if intent == "confirmar_seleccion":
        parametros = intent_data.get("parameters", {})
        es_positivo = parametros.get("confirmacion_positiva", False)

        if es_positivo:
            # ── SÍ: volver a SEARCHING pero conservar la lista activa ────────
            conversation_memory.set_conversation_state(
                numero_telefono, State.SEARCHING,
                {
                    "has_document_list":    True,   # ← conserva el cache
                    "is_notification_flow": conversation_state.get("is_notification_flow", False),
                }
            )
            return {
                "tipo":      "confirmacion",
                "respuesta": (
                    "✅ Perfecto. Puedes seleccionar otro documento de la lista "
                    "o buscar uno nuevo escribiendo su código o número."
                ),
                "intent":     intent,
                "parameters": {},
            }
        else:
            # ── NO: volver a AWAITING_SELECTION si hay lista ─────────────────
            if conversation_state.get("has_document_list"):
                conversation_memory.set_conversation_state(
                    numero_telefono, State.AWAITING_SELECTION,
                    {"has_document_list": True}
                )
                return {
                    "tipo":      "seleccion",
                    "respuesta": "Entendido. ¿Cuál de los documentos te interesa?",
                    "intent":    intent,
                    "parameters": {},
                    "pregunta_seguimiento": PREGUNTA_SELECCION,
                }
            conversation_memory.set_conversation_state(
                numero_telefono, State.INITIAL, {}
            )
            return {
                "tipo":      "info",
                "respuesta": "De acuerdo. ¿En qué puedo ayudarte?",
                "intent":    intent,
                "parameters": {},
            }
        return _handle_confirmacion(
            intent_data, conversation_state, documentos, numero_telefono
        )

    if intent == "seleccionar_documento":
        return _handle_seleccion_directa(intent_data, documentos)

    if intent in ("contactar_encargado", "contactar_responsable"):
        from services.contact_service import manejar_contacto_encargado
        resp = manejar_contacto_encargado(
            numero_telefono, conversation_context,
            tipo_contacto=intent.replace("contactar_", "")
        )
        return _mk("contacto", resp, intent)

    if intent in ("listar_sin_respuesta", "listar_sin_firma",
                  "listar_inactivos", "listar_stand_by"):
        from services.notificacion_handler import handle_notificaciones
        return handle_notificaciones(numero_telefono, intent)

    # ── Búsqueda dentro del cache (SEARCHING + lista activa) ─────────────────
    if intent in ("buscar_en_lista", "sublista_filtrada"):
        sub = intent_data.get("resultados", [])
        query = intent_data.get("query", "")
        if not sub:
            return _mk("info", "No encontré documentos que coincidan. Escribe 'Hola' para nueva búsqueda.",
                       intent, {})
        from utils.formatter import formatear_lista_documentos
        prefijo = f"🔍 Encontré *{len(sub)}* documentos con *'{query}'*:\n\n" if query else ""
        respuesta_lista = prefijo + formatear_lista_documentos(sub)
        conversation_memory.set_conversation_state(
            numero_telefono, State.AWAITING_SELECTION,
            {"has_document_list": True, "last_search_results_count": len(sub),
             "is_notification_flow": conversation_state.get("is_notification_flow", False)}
        )
        return {
            "tipo":       "lista",
            "respuesta":  respuesta_lista,
            "intent":     intent,
            "parameters": {"results_count": len(sub)},
            "resultados": sub,
            "pregunta_seguimiento": PREGUNTA_SELECCION,
        }

    if intent == "buscar_documentos" or intent_forzado == "buscar_documentos":
        return _handle_busqueda_algolia(
            parametro, intent_data, conversation_context, numero_telefono
        )

    if intent in {
        "seguimiento_por_numero_documento", "seguimiento_por_codigo",
        "seguimiento_por_usuario", "seguimiento_por_proyecto",
        "seguimiento_por_asunto", "seguimiento_por_consecutivo",
    } and intent_forzado != "buscar_documentos":
        return _handle_seguimiento(
            intent, parametro, documentos, should_filter,
            conversation_context, numero_telefono
        )

    if intent == "seleccionar_notificacion":
        from services.notificacion_handler import procesar_notificacion_seleccionada
        return procesar_notificacion_seleccionada(mensaje, numero_telefono, intent_data)

    if intent == "error_seleccion_notificacion":
        msg = intent_data.get("error") or f"❌ No encontré '{parametro}' en la lista."
        return _mk("error_notificacion", msg, intent, {"parametro": parametro})

    if intent == "error_seleccion_lista":
        msg = intent_data.get("error") or (
            f"❌ No encontré *'{parametro or ''}'* en la lista.\n\n"
            "Intenta con:\n• Número de posición: 1, 2, 3...\n"
            "• Código: ej. PR-001540\n• Parte del asunto\n• Nombre del encargado\n\n"
            "Si quieres iniciar una nueva búsqueda, escribe *'Hola'*"
        )
        return _mk("error_seleccion", str(msg), intent)

    # Fallback
    return _handle_fallback(mensaje, conversation_context, conversation_state)


# ── HANDLERS ESPECÍFICOS ──────────────────────────────────────────────────────

def _handle_confirmacion(
    intent_data: Dict, conversation_state: Dict,
    documentos: List[Dict], numero_telefono: str,
) -> Dict[str, Any]:
    positiva = intent_data.get("confirmacion_positiva")
    if positiva:
        conversation_memory.set_conversation_state(numero_telefono, State.SEARCHING)
        return _mk("confirmacion_positiva",
                   "Perfecto! ¿En qué más puedo ayudarte?\n"
                   "Si quieres iniciar una nueva búsqueda, escribe *'Hola'*",
                   "confirmar_seleccion")
    else:
        if documentos:
            conversation_memory.set_conversation_state(
                numero_telefono, State.AWAITING_SELECTION)
            return _mk("confirmacion_negativa", MENSAJE_VOLVER_LISTA, "confirmar_seleccion")
        conversation_memory.set_conversation_state(numero_telefono, State.INITIAL)
        return _mk("confirmacion_negativa",
                   "Entiendo. ¿Podrías especificar mejor lo que buscas?\n"
                   "Si quieres iniciar una nueva búsqueda, escribe *'Hola'*",
                   "confirmar_seleccion")


def _handle_seleccion_directa(intent_data: Dict, documentos: List[Dict]) -> Dict[str, Any]:
    """seleccionar_documento fuera de AWAITING_SELECTION (raro, pero manejado)."""
    doc = intent_data.get("documento_seleccionado")
    if not doc:
        return _error("❌ No hay documentos disponibles. Realiza una nueva búsqueda.")
    formato = formatear_seguimiento(doc)
    return {
        "tipo":       formato.get("tipo", "detalle") if isinstance(formato, dict) else "detalle",
        "respuesta":  formato["contenido"] if isinstance(formato, dict) else formato,
        "intent":     "seleccionar_documento",
        "parameters": {},
        "resultados": [doc],
    }


def _handle_busqueda_algolia(
    parametro: Optional[str], intent_data: Dict,
    conversation_context: Dict, numero_telefono: str,
) -> Dict[str, Any]:
    if conversation_context.get("nivel_acceso") == "user":
        return _error("❌ Tu nivel de acceso no permite búsquedas avanzadas.")
    if not parametro:
        return _error("❌ Por favor, especifica tu búsqueda.")

    consulta = parametro
    if intent_data.get("is_follow_up") and conversation_context.get("recent_searches"):
        consulta = f"{parametro} {conversation_context['recent_searches'][0]}"
        print(f"🧠 Consulta enriquecida: {consulta}")

    respuesta = generar_respuesta_busqueda_algolia(consulta)
    return _mk("algolia", respuesta, "buscar_documentos", {"algolia_query": consulta})


def _handle_seguimiento(
    intent: str, parametro: Optional[str],
    documentos: List[Dict], should_filter: bool,
    conversation_context: Dict, numero_telefono: str,
) -> Dict[str, Any]:
    if not parametro:
        return _error("❌ Por favor, especifica el parámetro para consultar.")

    print(f"🔍 {intent} → '{parametro}'")

    _fn = {
        "seguimiento_por_numero_documento": consultar_por_numero_documento,
        "seguimiento_por_codigo":           consultar_por_codigo_sistema,
        "seguimiento_por_usuario":          consultar_documentos_por_usuario,
        "seguimiento_por_proyecto":         consultar_documentos_por_proyecto,
        "seguimiento_por_asunto":           consultar_documento_por_asunto,
        "seguimiento_por_consecutivo":      consultar_por_numero_consecutivo,
    }

    if should_filter:
        from services.search_service import buscar_en_documentos_guardados
        seguimientos = buscar_en_documentos_guardados(documentos, parametro, intent)
    else:
        seguimientos = _fn[intent](parametro)

    # Fallback cruzado
    if not seguimientos:
        if intent == "seguimiento_por_numero_documento":
            seguimientos = consultar_por_numero_consecutivo(parametro)
            intent = "seguimiento_por_consecutivo"
        elif intent == "seguimiento_por_consecutivo":
            seguimientos = consultar_por_numero_documento(parametro)
            intent = "seguimiento_por_numero_documento"
        elif intent == "seguimiento_por_asunto":
            seguimientos = consultar_documentos_por_proyecto(parametro)
            intent = "seguimiento_por_proyecto"

    if not seguimientos:
        msg = f"❌ No se encontró información para: *{parametro}*\n\n{SUGERENCIAS_BUSQUEDA}"
        if conversation_context.get("recent_documents"):
            msg += f"\n💡 *¿Quizás: {conversation_context['recent_documents'][0]}?*"
        return _mk("no_encontrado", msg, intent)

    formato   = formatear_seguimiento(seguimientos)
    respuesta = formato["contenido"]
    tipo      = formato["tipo"]

    params: Dict[str, Any] = {}
    is_list = isinstance(seguimientos, list)

    if not should_filter:
        conversation_memory.set_conversation_documents(
            numero_telefono, seguimientos if is_list else [seguimientos],
            source_intent=intent, source_query=parametro
        )

    if is_list and len(seguimientos) > 1:
        conversation_memory.set_conversation_state(
            numero_telefono, State.AWAITING_SELECTION,
            {"has_document_list": True, "last_search_results_count": len(seguimientos)}
        )
        params = {"results_count": len(seguimientos), "resultados": seguimientos}
    elif is_list and len(seguimientos) == 1:
        conversation_memory.set_conversation_state(numero_telefono, State.AWAITING_CONFIRMATION)
        params = {"resultados": seguimientos}
    else:
        conversation_memory.set_conversation_state(numero_telefono, State.AWAITING_CONFIRMATION)
        if isinstance(seguimientos, dict):
            params.update(seguimientos)

    return {
        "tipo":       tipo,
        "respuesta":  respuesta,
        "intent":     intent,
        "parameters": params,
        "resultados": params.get("resultados") if tipo == "lista" else None,
        "pregunta_seguimiento": (
            PREGUNTA_SELECCION if tipo == "lista" else PREGUNTA_CONFIRMACION
        ),
    }


def _handle_fallback(
    mensaje: str, conversation_context: Dict, conversation_state: Dict
) -> Dict[str, Any]:
    tl = mensaje.lower().strip()
    if any(p in tl for p in ["ayuda", "cómo buscar", "como buscar", "necesito ayuda"]):
        resp = f"ℹ️ Parece que necesitas ayuda.\n\n{SUGERENCIAS_BUSQUEDA}"
        if conversation_context.get("recent_documents"):
            resp += f"\n\n📋 *Consultados: {', '.join(conversation_context['recent_documents'][:3])}*"
        return _mk("ayuda", resp, "ayuda")

    try:
        from services.ia_service import consultar_ia_con_memoria
        consulta_e = _enriquecer_consulta(mensaje, conversation_context)
        respuesta  = consultar_ia_con_memoria(consulta_e, conversation_context, conversation_state)
        if respuesta:
            return _mk("ia",
                       f"🤖 {respuesta}\n\n💡 *Reinicia escribiendo 'hola'*",
                       "ia")
    except Exception as e:
        print(f"⚠️  Error IA fallback: {e}")

    return _mk("error", f"❌ No entendí tu consulta.\n\n{SUGERENCIAS_BUSQUEDA}", "error")


# ── RECUPERAR DOCUMENTOS ──────────────────────────────────────────────────────

def _recuperar_documentos(numero_telefono: str, conversation_state: Dict) -> List[Dict]:
    """
    Intenta obtener docs de conversation_memory.
    Si están vacíos y hay notificación pendiente, los recupera de notification_manager.
    """
    docs = conversation_memory.get_conversation_documents(numero_telefono)
    if docs:
        return docs

    raw   = conversation_memory._get_or_create_state(numero_telefono)
    tipo  = raw.get("pending_notification_tipo", "inactivos")
    notif = notification_manager.get_all_documents_by_type(numero_telefono, tipo)

    if notif:
        conversation_memory.set_conversation_documents(
            numero_telefono, notif,
            source_intent=f"notificacion_{tipo}",
            source_query="Recuperado de notification_manager"
        )
        docs = conversation_memory.get_conversation_documents(numero_telefono)
        print(f"📚 {len(docs)} docs recuperados de notification_manager [{tipo}]")

    return docs


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _mk(tipo: str, respuesta: str, intent: str,
        parameters: Dict = None, resultados: List = None) -> Dict[str, Any]:
    return {
        "tipo":       tipo,
        "respuesta":  respuesta,
        "intent":     intent,
        "parameters": parameters or {},
        "resultados": resultados,
    }


def _error(msg: str) -> Dict[str, Any]:
    return _mk("error", msg, "error")


def _respuesta_saludo() -> str:
    return (
        "👋 *¡Hola!* Soy tu asistente de *ProRequest*.\n\n"
        "Puedo ayudarte a:\n"
        "• 🔍 Buscar documentos por código, asunto o proyecto\n"
        "• 📋 Ver tus notificaciones pendientes\n"
        "• 📞 Contactar encargados\n\n"
        "¿En qué te puedo ayudar?"
    )


def _respuesta_saludo_contextual(context: Dict) -> str:
    if context.get("is_follow_up") and context.get("recent_documents"):
        docs = ", ".join(context["recent_documents"][:3])
        return (
            f"👋 ¡Hola de nuevo! Anteriormente consultaste: *{docs}*.\n"
            "¿Quieres continuar con eso o necesitas algo nuevo?"
        )
    return _respuesta_saludo()


def _enriquecer_consulta(mensaje: str, context: Dict) -> str:
    partes = []
    if context.get("recent_documents"):
        partes.append(f"Documentos: {', '.join(context['recent_documents'][:2])}")
    if context.get("recent_searches"):
        partes.append(f"Búsquedas: {', '.join(context['recent_searches'][:2])}")
    if partes:
        return f"Contexto: {'. '.join(partes)}\nConsulta: {mensaje}"
    return mensaje


def generar_mensaje_whatsapp(payload, tipo_contacto="encargado"):
    """Genera mensaje para WhatsApp - VERSIÓN MEJORADA CON SOPORTE PARA ENCARGADO Y RESPONSABLE"""
    print(f"Información del documento (tipo_contacto: {tipo_contacto}):", payload)
    
    # Inicializar variables
    celular = None
    nombre = None
    etiqueta_contacto = "encargado" if tipo_contacto == "encargado" else "responsable"
    
    # Para documentos de prueba del JSON
    try:
        if tipo_contacto == "responsable":
            # Buscar en responsables
            responsables = None
            
            # Intentar diferentes estructuras
            if 'documento' in payload:
                if 'notification' in payload['documento'] and 'payload' in payload['documento']['notification']:
                    responsables = payload['documento']['notification']['payload'].get('responsables')
                elif 'responsables' in payload['documento']:
                    responsables = payload['documento']['responsables']
            elif 'responsables' in payload:
                responsables = payload['responsables']
            
            if responsables and len(responsables) > 0:
                celular = responsables[0].get('celular', None)
                nombre = f"{responsables[0].get('nombre', '')} {responsables[0].get('apellido_paterno', '')}".strip()
                print(f"✅ Responsable encontrado: {nombre}, {celular}")
            else:
                raise KeyError("No hay responsables en la lista")
                
        else:
            # Buscar en encargados (comportamiento original)
            encargados = None
            
            # Intentar diferentes estructuras
            if 'documento' in payload:
                if 'notification' in payload['documento'] and 'payload' in payload['documento']['notification']:
                    encargados = payload['documento']['notification']['payload'].get('encargados')
                elif 'encargados' in payload['documento']:
                    encargados = payload['documento']['encargados']
            elif 'encargados' in payload:
                encargados = payload['encargados']
            
            if encargados and len(encargados) > 0:
                celular = encargados[0].get('celular', None)
                nombre = f"{encargados[0].get('nombres', '')} {encargados[0].get('apellido_paterno', '')}".strip()
                print(f"✅ Encargado encontrado: {nombre}, {celular}")
            else:
                raise KeyError("No hay encargados en la lista")

    except Exception as e:
        celular = "+51972453786"
        nombre = "Usuario de Prueba"
    
    try:
        documento_info = payload['documento']['documento']
    except Exception as e:
        print("❌ Error leyendo documento:", e)
        documento_info = {}

    numero_doc = documento_info.get('numero_documento', 'DOC-001')
    asunto = documento_info.get('asunto', 'Asunto no disponible')[:100]

    # ============================
    # 2. Extraer encargado
    # ============================
    try:
        encargado = payload['documento']['encargados'][0]
        nombre = f"{encargado.get('nombres','')} {encargado.get('apellido_paterno','')}".strip()
        celular = encargado.get('celular', None)
    except Exception as e:
        print("❌ Error leyendo encargado:", e)
        nombre = "Usuario"
        celular = None

    # ============================
    # 3. Construir mensaje
    # ============================
    mensaje = (
        f"Hola {nombre.split()[0]}, te contacto respecto al documento:"
        f"\n📄 {numero_doc}"
        f"\n📝 {asunto}..."
        f"\n\n¿Podrías brindarme una actualización? ¡Gracias!"
    )

    
    # Limpiar y formatear número
    celular_limpio = re.sub(r"[^0-9]", "", celular)
    if not celular_limpio.startswith('51'):
        celular_limpio = '51' + celular_limpio.lstrip('0')
    
    url_whatsapp = f"https://wa.me/{celular_limpio}?text={requests.utils.quote(mensaje)}"
    
    # Retornar diccionario con ambas claves para compatibilidad
    return {
        'mensaje': mensaje,
        'url_whatsapp': url_whatsapp,
        'encargado': nombre,  
        'responsable': nombre,  
        'celular': celular
    }

def manejar_contacto_encargado(numero_telefono, conv_context, tipo_contacto="encargado"):
    """Maneja el contacto con el encargado o responsable"""
    try:
        print(f"🔍 Buscando información de contacto ({tipo_contacto}) para {numero_telefono}")

        alert_payload = None
        documento_info = None

        # 1. BUSCAR EN TURNOS RECIENTES
        if hasattr(conversation_memory, 'conversations') and numero_telefono in conversation_memory.conversations:
            ultimos = conversation_memory.conversations[numero_telefono][-5:]
            for i, turno in enumerate(reversed(ultimos)):  # más reciente primero
                ctx = turno.context if isinstance(turno.context, dict) else {}
                print(f"  Turno -{i+1}: intent={turno.intent} | alert_active={ctx.get('alert_active')} | tiene_payload={bool(ctx.get('alert_payload'))}")

                # Alerta activa con payload
                if ctx.get('alert_active') and ctx.get('alert_payload'):
                    alert_payload = ctx.get('alert_payload')
                    print(f"✅ alert_payload encontrado en turno -{i+1}")
                    break

                # Turno de notificación seleccionada
                if turno.intent == 'notification_selected':
                    params = turno.parameters if isinstance(turno.parameters, dict) else {}
                    notification = params.get('selected_notification', {})
                    if notification:
                        alert_payload = notification.get('payload', {})
                        print(f"✅ payload extraído de notification_selected en turno -{i+1}")
                        break

                # Turno de seguimiento con info de documento
                if turno.intent in ['seleccionar_notificacion', 'seguimiento_por_codigo', 'seguimiento_por_numero_documento']:
                    params = turno.parameters if isinstance(turno.parameters, dict) else {}
                    if params:
                        documento_info = params
                        print(f"📄 documento_info encontrado en turno -{i+1}: {turno.intent}")
                        break

        # 2. BUSCAR EN DOCUMENTOS GUARDADOS
        if not alert_payload and not documento_info:
            print("🔍 Buscando en documentos guardados...")
            documentos_guardados = conversation_memory.get_conversation_documents(numero_telefono, limit=5)

            if documentos_guardados:
                for doc in documentos_guardados:
                    encargados = doc.get('encargados', [])
                    responsables = doc.get('responsables', [])
                    if encargados or responsables or doc.get('usuario_asignado'):
                        documento_info = doc
                        print(f"📚 Documento con contacto encontrado: {doc.get('codigo_sistema', 'N/A')}")
                        break

        # PROCESAR
        if alert_payload:
            print("✅ Procesando alert_payload")
            return procesar_alert_payload(alert_payload, numero_telefono, tipo_contacto)

        elif documento_info:
            print("✅ Procesando documento_info")
            return procesar_documento_info(documento_info, numero_telefono, tipo_contacto)

        else:
            print("❌ No se encontró información de contacto")
            return generar_respuesta_sin_info_contacto(conv_context, tipo_contacto)

    except Exception as e:
        print(f"❌ Error manejando contacto: {e}")
        import traceback
        traceback.print_exc()
        return "❌ Error interno al generar el contacto. Por favor, inténtalo de nuevo."

def procesar_documento_info(documento_info, numero_telefono, tipo_contacto="encargado"):
    """Procesa información de documento para generar contacto con formato WhatsApp"""
    try:
        print(f"📄 Iniciando procesamiento de documento_info (tipo: {tipo_contacto})...")
        print("🔍 documento_info recibido:", documento_info)

        # Inicializar variables
        contacto_nombre = None
        celular = None
        documento_id = None
        
        # Etiquetas según tipo de contacto
        etiqueta_contacto = "encargado" if tipo_contacto == "encargado" else "responsable"
        etiqueta_mayus = "Encargado" if tipo_contacto == "encargado" else "Responsable"

        if isinstance(documento_info, dict):
            print(f"✅ documento_info es un diccionario, buscando {etiqueta_contacto}...")
            
            # Buscar contacto según tipo
            try:
                if tipo_contacto == "responsable":
                    # Buscar responsable
                    if documento_info.get("responsables"):
                        resp = documento_info["responsables"]
                        print("👥 Lista de responsables:", resp)
                        if isinstance(resp, list) and len(resp) > 0:
                            print("➡️ Primer responsable dict:", resp[0])
                            contacto_nombre = f"{resp[0].get('nombre', '')} {resp[0].get('apellido_paterno', '')}".strip()
                            celular = resp[0].get("celular")
                            print("👤 Responsable detectado:", contacto_nombre)
                            print("📱 Celular detectado:", celular)
                    elif documento_info.get("responsable"):
                        contacto_nombre = documento_info["responsable"]
                        print("👤 Responsable encontrado:", contacto_nombre)
                else:
                    # Buscar encargado (comportamiento original)
                    if documento_info.get("usuario_asignado"):
                        contacto_nombre = documento_info["usuario_asignado"]
                        print("👤 Encontrado usuario_asignado:", contacto_nombre)
                    elif documento_info.get("encargados"):
                        enc = documento_info["encargados"]
                        print("👥 Lista de encargados:", enc)
                        if isinstance(enc, list) and len(enc) > 0:
                            print("➡️ Primer encargado dict:", enc[0])
                            contacto_nombre = f"{enc[0].get('nombres', '')} {enc[0].get('apellido_paterno', '')}".strip()
                            celular = enc[0].get("celular")
                            print("👤 Encargado detectado:", contacto_nombre)
                            print("📱 Celular detectado:", celular)
                    elif documento_info.get("encargado"):
                        contacto_nombre = documento_info["encargado"]
                        print("👤 Encargado encontrado:", contacto_nombre)
            except Exception as e:
                print(f"❌ Error buscando {etiqueta_contacto}:", e)

            # Buscar celular si aún no lo tienes
            try:
                if not celular:
                    celular = (
                        documento_info.get('celular') or 
                        documento_info.get('telefono') or
                        documento_info.get('phone')
                    )
                print("📱 Celular final:", celular)
            except Exception as e:
                print("❌ Error buscando celular:", e)

            # Buscar ID de documento
            try:
                documento_id = (
                    documento_info.get('codigo_sistema') or
                    documento_info.get('numero_documento') or
                    documento_info.get('document_id')
                )
                print("🆔 Documento ID detectado:", documento_id)
            except Exception as e:
                print("❌ Error buscando documento_id:", e)

            # ✅ Usar la función generar_mensaje_whatsapp para armar respuesta final
            try:
                # Empaquetar en payload con estructura mínima para generar mensaje
                payload = {"documento": documento_info}
                if tipo_contacto == "responsable" and documento_info.get("responsables"):
                    payload["responsables"] = documento_info["responsables"]
                elif documento_info.get("encargados"):
                    payload["encargados"] = documento_info["encargados"]

                info_whatsapp = generar_mensaje_whatsapp(payload, tipo_contacto)

                respuesta = f"""
✅ ¡Perfecto! Te ayudo a contactar al {etiqueta_contacto}.

👤 *{etiqueta_mayus}: {info_whatsapp[etiqueta_contacto]}*
📱 {info_whatsapp['celular']}

🔗 *Link directo de WhatsApp:*
{info_whatsapp['url_whatsapp']}

📝 *Mensaje sugerido ya incluido:*
"{info_whatsapp['mensaje']}"

💡 Solo haz clic en el link y se abrirá WhatsApp con el mensaje listo para enviar.
"""
                print("🤖 Respuesta generada:\n", respuesta)

                # Registrar en la memoria de conversación
                try:
                    context_info = {
                        "contact_generated": True,
                        "contact_type": tipo_contacto,
                        "contact_sent_to": info_whatsapp[etiqueta_contacto],
                        "contact_phone": info_whatsapp['celular'],
                        "document_id": documento_id
                    }
                    print("📝 Context info a registrar:", context_info)

                    conversation_memory.add_turn(
                        phone_number=numero_telefono,
                        user_message=f"[CONTACTO_INFO_DOCUMENTO_{tipo_contacto.upper()}]",
                        bot_response=respuesta,
                        intent=f"contactar_{etiqueta_contacto}",
                        parameters={etiqueta_contacto: info_whatsapp[etiqueta_contacto], "document_id": documento_id},
                        context=context_info,
                        flow="contacto"
                    )
                    print("💾 Turno registrado en conversation_memory")
                except Exception as e:
                    print("❌ Error registrando en conversation_memory:", e)

                return respuesta

            except Exception as e:
                print("❌ Error generando mensaje WhatsApp:", e)
                return f"❌ No pude generar el mensaje de WhatsApp para el {etiqueta_contacto}."

        else:
            print("❌ documento_info no es un diccionario")
            return f"❌ No encontré información del {etiqueta_contacto} en este documento."

    except Exception as e:
        print(f"❌ Error procesando documento_info (nivel general): {e}")
        return "❌ Error procesando información del documento."


def procesar_alert_payload(alert_payload, numero_telefono, tipo_contacto="encargado"):
    """Procesa alert_payload para generar contacto"""
    try:
        # Convertir de string a dict si es necesario
        if isinstance(alert_payload, str):
            try:
                alert_payload = json.loads(alert_payload)
            except Exception as e:
                print("❌ Error convirtiendo alert_payload:", e)
                return "❌ El formato de la alerta no es válido."

        # Etiquetas según tipo de contacto
        etiqueta_contacto = "encargado" if tipo_contacto == "encargado" else "responsable"
        etiqueta_mayus = "Encargado" if tipo_contacto == "encargado" else "Responsable"

        # Generar mensaje de WhatsApp
        info_whatsapp = generar_mensaje_whatsapp(alert_payload, tipo_contacto)
                
        if info_whatsapp:
            respuesta = f"""
✅ ¡Perfecto! Te ayudo a contactar al {etiqueta_contacto}.

👤 *{etiqueta_mayus}: {info_whatsapp[etiqueta_contacto]}*
📱 {info_whatsapp['celular']}

🔗 *Link directo de WhatsApp:*
{info_whatsapp['url_whatsapp']}

📝 *Mensaje sugerido ya incluido:*
"{info_whatsapp['mensaje']}"

💡 Solo haz clic en el link y se abrirá WhatsApp con el mensaje listo para enviar.
"""
            
            # Registrar el contacto generado
            context_info = {
                "contact_generated": True,
                "contact_type": tipo_contacto,
                "contact_sent_to": info_whatsapp[etiqueta_contacto],
                "contact_phone": info_whatsapp['celular']
            }
            
            conversation_memory.add_turn(
                phone_number=numero_telefono,
                user_message=f"[CONTACTO_SOLICITADO_{tipo_contacto.upper()}]",
                bot_response=respuesta,
                intent=f"contactar_{etiqueta_contacto}",
                parameters={etiqueta_contacto: info_whatsapp[etiqueta_contacto]},
                context=context_info,
                flow="contacto"
            )
            
            return respuesta
        else:
            return f"❌ No pude generar la información de contacto del {etiqueta_contacto}. Inténtalo nuevamente."
    
    except Exception as e:
        print(f"❌ Error procesando alert_payload: {e}")
        return "❌ Error procesando información de contacto."


def generar_respuesta_sin_info_contacto(conv_context, tipo_contacto="encargado"):
    """Genera respuesta cuando no hay información de contacto disponible"""
    etiqueta_contacto = "encargado" if tipo_contacto == "encargado" else "responsable"
    
    return f"""
❌ No encontré información del {etiqueta_contacto} para este documento.

💡 *Opciones:*
- Realiza primero una búsqueda del documento
- Selecciona un documento de tus notificaciones
- Proporciona el código del documento

Luego podrás solicitar el contacto del {etiqueta_contacto}.
"""



def respuesta_saludo_contextual(conversation_context):
    """Genera saludo personalizado basado en contexto"""
    if conversation_context.get("session_length", 0) > 0:
        if conversation_context.get("recent_documents"):
            return (
                f"👋 ¡Hola de nuevo! Veo que consultaste recientemente: "
                f"*{', '.join(conversation_context['recent_documents'][:2])}*\n\n"
                f"¿En qué más puedo ayudarte?\n\n{SUGERENCIAS_BUSQUEDA}"
            )
        elif conversation_context.get("recent_projects"):
            return (
                f"👋 ¡Hola de nuevo! Consultaste sobre el proyecto: "
                f"*{conversation_context['recent_projects'][0]}*\n\n"
                f"¿Necesitas algo más?\n\n{SUGERENCIAS_BUSQUEDA}"
            )
        else:
            return f"👋 ¡Hola de nuevo! ¿En qué más puedo ayudarte?\n\n{SUGERENCIAS_BUSQUEDA}"
    else:
        return respuesta_saludo()


def buscar_en_documentos_guardados(documentos_guardados, parametro, intent_type):
    """Busca en documentos previamente guardados según el intent"""
    resultados = []
    parametro_lower = parametro.lower()
    
    for doc in documentos_guardados:
        match = False
        
        # Buscar según tipo de intent
        if intent_type == "seguimiento_por_numero_documento":
            if parametro_lower in doc.get("numero_documento", "").lower():
                match = True
        elif intent_type == "seguimiento_por_codigo":
            if parametro_lower in doc.get("codigo_sistema", "").lower():
                match = True
        elif intent_type == "seguimiento_por_proyecto":
            if parametro_lower in doc.get("proyecto_nombre", "").lower():
                match = True
        elif intent_type == "seguimiento_por_asunto":
            if parametro_lower in doc.get("asunto", "").lower():
                match = True
        elif intent_type == "seguimiento_por_usuario":
            encargados = doc.get("encargados", "")
            responsable = doc.get("responsable_proyecto", "")
            if parametro_lower in encargados.lower() or parametro_lower in responsable.lower():
                match = True
        elif intent_type == "seguimiento_por_consecutivo":
            if parametro_lower in doc.get("numero_consecutivo", "").lower():
                match = True
        
        if match:
            resultados.append(doc)
    
    return resultados if resultados else None


def formatear_documento_detalle(documento):
    """Formatea un documento individual con todos sus detalles"""
    return f"""📄 **Documento Encontrado:**

• **Código:** {documento.get('codigo_sistema', 'N/A')}
• **Tipo:** {documento.get('tipo', 'N/A')}
• **Número:** {documento.get('numero_documento', 'N/A')}
• **Asunto:** {documento.get('asunto', 'N/A')}
• **Estado:** {documento.get('estado_flujo', 'N/A')}
• **Prioridad:** {documento.get('prioridad_nombre', 'N/A')}
• **Proyecto:** {documento.get('proyecto_nombre', 'N/A')}
• **Responsable:** {documento.get('responsable_proyecto', 'No asignado')}
• **Encargados:** {documento.get('encargados', 'No asignado')}
• **Fecha ingreso:** {documento.get('fecha_ingreso', 'No definida')}
• **Fecha límite:** {documento.get('fecha_limite', 'No definida')}"""


def formatear_lista_documentos(seguimientos):
    """
    Formatea lista DETALLADA de documentos para notificaciones de WhatsApp
    Muestra: número, código, tipo, asunto, proyecto, encargado, fecha
    Estilo similar al formato consolidado de email
    """
    if not seguimientos:
        return "❌ No se encontraron documentos."
    
    if not isinstance(seguimientos, list):
        return "⚠️ Error: formato de datos inválido."
    
    cantidad = len(seguimientos)
    mensaje = ""
    
    # Limitar a 10 documentos para legibilidad en WhatsApp
    documentos_a_mostrar = seguimientos[:100]
    
    for idx, seg in enumerate(documentos_a_mostrar, 1):
        # Extraer documento según estructura
        if isinstance(seg, dict):
            doc = seg.get('documento', seg)
            proyecto_data = seg.get('proyecto', {})
            encargados = seg.get('encargados', [])
            
            # Extraer campos del documento
            codigo = doc.get('codigo_sistema', 'N/A')
            tipo = doc.get('tipo', 'N/A')
            numero_doc = doc.get('numero_documento', 'N/A')
            asunto = doc.get('asunto', 'Sin asunto')
            dias_inactivo = doc.get('dias_inactivo')
            fecha_ingreso = doc.get('fecha_ingreso', '')
            estado = doc.get('estado', '')

            
            # Extraer nombre del proyecto
            if isinstance(proyecto_data, dict):
                proyecto = proyecto_data.get('nombre', 'N/A')
            elif isinstance(proyecto_data, str):
                proyecto = proyecto_data
            else:
                proyecto = 'N/A'
            
            # Obtener nombre del encargado
            encargado_nombre = 'Sin asignar'
            if encargados and len(encargados) > 0:
                enc = encargados[0]
                encargado_nombre = f"{enc.get('nombres', '')} {enc.get('apellido_paterno', '')}".strip()
            
            # Formatear fecha de ingreso
            if fecha_ingreso:
                try:
                    from datetime import datetime
                    fecha_obj = datetime.strptime(fecha_ingreso[:10], '%Y-%m-%d')
                    fecha_ingreso = fecha_obj.strftime('%d/%m/%Y')
                except:
                    fecha_ingreso = fecha_ingreso[:10] if len(fecha_ingreso) >= 10 else fecha_ingreso
            
            # Truncar asunto si es muy largo
            if len(asunto) > 70:
                asunto = asunto[:67] + "..."
            
            # Formato detallado
            mensaje += f"*{idx}. {numero_doc}*\n"
            
            if asunto and asunto != 'Sin asunto':
                mensaje += f"   📄 {asunto}\n"
            
            if proyecto and proyecto != 'N/A':
                mensaje += f"   🏗️ {proyecto}\n"
            
            mensaje += f"   👤 En atención de: {encargado_nombre}\n"
            
            if fecha_ingreso:
                mensaje += f"   📅 Ingreso: {fecha_ingreso}\n"
            
            if estado:
                mensaje += f"   📌 Estado: {estado}\n"

            # Agregar días de inactividad si existe
            if dias_inactivo is not None:
                mensaje += f"   ⏱️ Inactivo: {dias_inactivo} días\n"
            
            mensaje += "\n"
    
    # Indicar si hay más documentos
    if cantidad > 10:
        mensaje += f"_... y {cantidad - 10} documento(s) más_\n\n"
    
    mensaje += f"_Total: {cantidad} documento{'s' if cantidad != 1 else ''}_"
    
    return mensaje


