"""
core/flow.py
"""

import re
from typing import Any, Dict, List, Optional

from core.conversationMemory import conversation_memory
from core.states import State
from services.ia_service import seleccionar_respuesta
_POSITIVAS = {"si", "sí", "yes", "correcto", "exacto", "ese", "perfecto", "está bien", "ok", "dale"}
_NEGATIVAS = {"no", "nope", "incorrecto", "otro", "diferente", "no es", "nop"}

_INTENTS_BUSQUEDA = {
    "seguimiento_por_numero_documento",
    "seguimiento_por_codigo",
    "seguimiento_por_usuario",
    "seguimiento_por_proyecto",
    "seguimiento_por_asunto",
    "seguimiento_por_consecutivo",
    "buscar_documentos",
}


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def detectar_intencion_con_contexto(
    texto_usuario: str,
    phone_number:  str,
    conversation_context: Dict = None,
    conversation_state:   Dict = None,
) -> Dict[str, Any]:

    if conversation_state is None:
        conversation_state = conversation_memory.get_conversation_state(phone_number)
    if conversation_context is None:
        conversation_context = conversation_memory.get_conversation_context(phone_number)

    estado = conversation_state.get("state", State.INITIAL)
    texto  = texto_usuario.strip()

    print(f"🔀 FSM estado={estado} | msg='{texto[:50]}'")

    if texto.lower() in {"hola", "hello", "hi"}:
        conversation_memory._reset(phone_number)
        return _intent("saludo", reset_triggered=True)

    if estado == State.AWAITING_SELECTION:
        return _handle_awaiting_selection(texto, phone_number, conversation_context)

    if estado == State.AWAITING_CONFIRMATION:
        return _handle_awaiting_confirmation(texto, phone_number)

    return _handle_free(texto, conversation_context, conversation_state, phone_number)


def _handle_awaiting_selection(
    texto: str,
    phone_number: str,
    context: Dict,
) -> Dict[str, Any]:

    documentos = conversation_memory.get_conversation_documents(phone_number)

    if not documentos:
        print("⚠️  AWAITING_SELECTION sin docs → delegando a free handler")
        return _handle_free(texto, context, {"state": State.INITIAL})

    doc = _resolver_seleccion(texto, documentos)
    if doc is not None:
        return _intent("seleccionar_documento", documento_seleccionado=doc, resultados=[doc])

    doc_ia = _resolver_seleccion_con_ia(texto, documentos)
    if doc_ia is not None:
        return _intent("seleccionar_documento", documento_seleccionado=doc_ia, resultados=[doc_ia])

    # 3. No encontrado
    print(f"⚠️  No se encontró '{texto}' en {len(documentos)} docs")
    return _intent(
        "error_seleccion_lista",
        error=(
            f"No encontré *'{texto}'* en la lista.\n\n"
            "Intenta con:\n"
            "• El *número* de posición: 1, 2, 3...\n"
            "• El *código*: ej. PR-001540\n"
            "• Parte del *asunto*\n"
            "• Nombre del *encargado*\n\n"
            "Si quieres iniciar una nueva búsqueda, escribe *'Hola'*"
        )
    )


def _handle_awaiting_confirmation(texto: str, phone_number: str) -> Dict[str, Any]:
    texto_lower = texto.lower().strip()
    if any(p in texto_lower for p in _POSITIVAS):
        return _intent("confirmar_seleccion", confirmacion_positiva=True)
    if any(n in texto_lower for n in _NEGATIVAS):
        return _intent("confirmar_seleccion", confirmacion_positiva=False)
    return _handle_free(texto, {}, {"state": State.INITIAL})

def _handle_free( texto: str, context: Dict, conversation_state: Dict,phone_number:str = None) -> Dict[str, Any]:
    """
    Estado INITIAL o SEARCHING.
    """
    estado = conversation_state.get("state", State.INITIAL)
    tiene_lista = conversation_state.get("has_document_list", False)

    if estado == State.SEARCHING and tiene_lista and phone_number: 
        documentos = conversation_memory.get_conversation_documents(phone_number)
        if documentos:
            print(f"📚 Modo filtrado: {len(documentos)} docs")
            doc = _resolver_seleccion(texto, documentos)
            if doc is not None:
                print(f"✅ Campo único: '{texto}'")
                return _intent("seleccionar_documento", documento_seleccionado=doc, resultados=[doc])
            tl     = texto.lower()
            tokens = [tok for tok in re.findall(r'[\w-]+', texto, re.IGNORECASE) if len(tok) >= 2]
            if tokens:
                sub = [doc for doc in documentos if any (
                    tok.lower() in " ".join([
                        _extraer_campos_doc(doc)["codigo_sistema"],
                        _extraer_campos_doc(doc)["numero_documento"],
                        _extraer_campos_doc(doc)["asunto"],
                        _extraer_campos_doc(doc)["encargado"],
                    ]).lower()
                    for tok in tokens
                )]
            if sub:
                    print(f"📋 Sublista: {len(sub)} docs filtrados por '{texto}'")
                    return _intent(
                        "buscar_en_lista",
                        parametro=texto,
                        resultados=sub,
                        total=len(sub),
                    )
            print(f"🔍 Sin match en cache, pasando a búsqueda global...")

    patron = _detectar_patron_numerico(texto)
    if patron:
        print(f"✅ Patrón numérico sin LLM: {patron['intent']} → '{patron['parametro']}'")
        return patron

    # 1. Follow-up contextual sin LLM
    follow_up = _resolver_follow_up(texto, context)
    if follow_up:
        print(f"✅ Follow-up local: {follow_up['intent']}")
        return follow_up

    try:
        from ia.router import router
        result = router(texto, context, conversation_state)
        if result:
            return _normalizar_resultado_router(result)
    except Exception as e:
        print(f"⚠️  Error router Gemini: {e}")

    try:
        from services.ia_service import detectar_intencion_optimizado
        return detectar_intencion_optimizado(texto)
    except Exception as e:
        print(f"❌ Error fallback: {e}")

    return _intent("error", error="No pude procesar tu mensaje")



def _detectar_patron_numerico(texto: str) -> Optional[Dict[str, Any]]:
    """
    Detecta formatos de código/número que no necesitan LLM.
    Evita que Gemini invente respuestas para códigos obvios.
    """
    t = texto.strip()

    if re.match(r'^\d{2,6}-20\d{2}$', t):
        return _intent("seguimiento_por_consecutivo", parametro=t)

    if re.match(r'^PR-\d+$', t, re.IGNORECASE):
        return _intent("seguimiento_por_codigo", parametro=t.upper())

    if re.match(r'^\d{5,}$', t):
        return _intent("seguimiento_por_consecutivo", parametro=t)

    if re.match(r'^[\w]+-[\w]+-[\w-]+$', t) and len(t) > 8:
        return _intent("seguimiento_por_numero_documento", parametro=t)

    return None



def _extraer_campos_doc(doc: Dict) -> Dict:
    """Normaliza doc independientemente de si los campos están en top-level o anidados."""
    inner = doc.get("documento", doc)
    encargado = ""
    encargados = doc.get("encargados") or inner.get("encargados") or []
    if encargados and isinstance(encargados, list):
        first = encargados[0]
        encargado = (
            f"{first.get('nombres','')} {first.get('apellido_paterno','')}".strip()
            if isinstance(first, dict) else str(first)
        )
    return {
        "codigo_sistema":   inner.get("codigo_sistema", ""),
        "numero_documento": inner.get("numero_documento", ""),
        "asunto":           inner.get("asunto", ""),
        "encargado":        encargado,
    }


def _resolver_seleccion(texto: str, documentos: List[Dict]) -> Optional[Dict]:
    t = texto.strip()
    tl = t.lower()

    if re.match(r'^\d+$', t):
        idx = int(t) - 1
        if 0 <= idx < len(documentos):
            print(f"✅ Posición {idx + 1}")
            return documentos[idx]
        return None

    ordinales = {"primero": 0, "primera": 0, "segundo": 1, "segunda": 1,
                 "tercero": 2, "tercera": 2, "cuarto": 3, "cuarta": 3,
                 "quinto": 4, "quinta": 4}
    for palabra, idx in ordinales.items():
        if palabra in tl and idx < len(documentos):
            print(f"✅ Ordinal '{palabra}'")
            return documentos[idx]

    tokens = [tok for tok in re.findall(r'[\w-]+', t, re.IGNORECASE) if len(tok) >= 2]
    if not tokens:
        return None

    matches = [
    doc for doc in documentos
    if all(
        tok.lower() in " ".join([
            str(_extraer_campos_doc(doc).get("codigo_sistema") or ""),
            str(_extraer_campos_doc(doc).get("numero_documento") or ""),
            str(_extraer_campos_doc(doc).get("asunto") or ""),
            str(_extraer_campos_doc(doc).get("encargado") or ""),
        ]).lower()
        for tok in tokens
    )
]

    if len(matches) == 1:
        print(f"✅ Campo único: '{t}'")
        return matches[0]

    if len(matches) > 1:
        # Intentar match exacto
        exactos = [
            d for d in matches
            if tl == _extraer_campos_doc(d)["numero_documento"].lower()
            or tl == _extraer_campos_doc(d)["codigo_sistema"].lower()
        ]
        if len(exactos) == 1:
            print(f"✅ Exacto: '{t}'")
            return exactos[0]
        print(f"⚠️  Ambiguo '{t}': {len(matches)} matches → Gemini")
        return None

    return None


def _resolver_seleccion_con_ia(texto: str, documentos: List[Dict]) -> Optional[Dict]:
    try:

        resultado = seleccionar_respuesta(texto, documentos=documentos[:20])

        if not resultado:
            return None

        params = resultado.get("parameters", {})
    
        pos = params.get("posicion_lista")
        if pos is not None:
            idx = int(pos) - 1
            if 0 <= idx < len(documentos):
                print(f"✅ Gemini: posición {idx + 1}")
                return documentos[idx]
            
        codigo = params.get("codigo_sistema")
        if codigo:
            for doc in documentos:
                if _extraer_campos_doc(doc)["codigo_sistema"].lower() == str(codigo).lower():
                    print(f"✅ Gemini: código {codigo}")
                    return doc

        numero = params.get("numero_documento")
        if numero:
            for doc in documentos:
                if _extraer_campos_doc(doc)["numero_documento"].lower() == str(numero).lower():
                    print(f"✅ Gemini: número {numero}")
                    return doc
                
        doc_id = params.get("document_id")
        if doc_id:
            for doc in documentos:
                inner = doc.get("documento", doc)
                if str(inner.get("id", "")) == str(doc_id):
                    print(f"✅ Gemini: id {doc_id}")
                    return doc


    except Exception as e:
        print(f"⚠️  Error Gemini selección: {e}")
    return None



def _resolver_follow_up(texto: str, context: Dict) -> Optional[Dict[str, Any]]:
    if not context.get("is_follow_up"):
        return None
    tl = texto.lower().strip()

    if any(w in tl for w in ["este", "ese", "el documento", "el anterior"]):
        if context.get("recent_documents"):
            return _intent("seguimiento_por_numero_documento",
                           parametro=context["recent_documents"][0], is_follow_up=True)

    if any(w in tl for w in ["este proyecto", "ese proyecto", "el proyecto"]):
        if context.get("recent_projects"):
            return _intent("seguimiento_por_proyecto",
                           parametro=context["recent_projects"][0], is_follow_up=True)
    return None



def _normalizar_resultado_router(result: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte salida de ia/router.py al formato estándar de procesar_mensaje."""
    intent     = result.get("intent", "unknown")
    parameters = result.get("parameters", {})

    PARAM_MAP = {
        "seguimiento_por_codigo":           "documento_id",
        "seguimiento_por_numero_documento": "numero_documento",
        "seguimiento_por_consecutivo":      "numero_documento",
        "seguimiento_por_usuario":          "usuario",
        "seguimiento_por_proyecto":         "proyecto",
        "seguimiento_por_asunto":           "consulta",
        "buscar_documentos":                "consulta",
        "seleccionar_opcion":               "posicion_lista",
    }

    # El router usa "numero_documento" o "codigo_sistema" como campo del parámetro
    param_key = PARAM_MAP.get(intent, "")
    parametro = (
        parameters.get(param_key)
        or parameters.get("numero_documento")
        or parameters.get("codigo_sistema")
        or parameters.get("document_id")
        or parameters.get("consulta")
        or None
    )

    normalized: Dict[str, Any] = {"intent": intent, "parametro": parametro}

    for campo in ("confirmacion_positiva", "posicion_lista", "is_follow_up",
                  "notification_index", "post_detail_action", "next_state"):
        if campo in parameters:
            normalized[campo] = parameters[campo]

    return normalized



def _intent(intent: str, **kwargs) -> Dict[str, Any]:
    return {"intent": intent, "parametro": kwargs.pop("parametro", None), **kwargs}