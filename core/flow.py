"""
core/flow.py
────────────
FSM de conversación. Responsabilidades:
  1. Dado estado + mensaje → devuelve intent_data estandarizado
  2. En AWAITING_SELECTION: resuelve selección con Python puro → Gemini como fallback
  3. En INITIAL/SEARCHING: delega al router Gemini (ia/router.py)
  4. Detecta patrones numéricos obvios sin LLM

NO formatea respuestas, NO accede a DB, NO envía mensajes.
"""

import re
from typing import Any, Dict, List, Optional

from core.conversationMemory import conversation_memory
from core.states import State

_POSITIVAS = {"si", "sí", "yes", "correcto", "exacto", "ese", "perfecto", "está bien", "ok", "dale"}
_NEGATIVAS = {"no", "nope", "incorrecto", "otro", "diferente", "no es", "nop"}

# Intents del router que mapean directamente a búsqueda en DB
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

    # Reset manual siempre tiene prioridad
    if texto.lower() in {"hola", "hello", "hi"}:
        conversation_memory._reset(phone_number)
        return _intent("saludo", reset_triggered=True)

    if estado == State.AWAITING_SELECTION:
        return _handle_awaiting_selection(texto, phone_number, conversation_context)

    if estado == State.AWAITING_CONFIRMATION:
        return _handle_awaiting_confirmation(texto, phone_number)

    # INITIAL y SEARCHING → router (con cache-first en SEARCHING)
    return _handle_free(texto, conversation_context, conversation_state, phone_number)


# ── HANDLERS POR ESTADO ───────────────────────────────────────────────────────

def _handle_awaiting_selection(
    texto: str,
    phone_number: str,
    context: Dict,
) -> Dict[str, Any]:
    """
    Usuario eligiendo de una lista.
    Prioridad: Python puro → sublista si ambiguo → Gemini → error.
    No sale de AWAITING_SELECTION salvo reset.
    """
    documentos = conversation_memory.get_conversation_documents(phone_number)

    if not documentos:
        print("⚠️  AWAITING_SELECTION sin docs → delegando a free handler")
        return _handle_free(texto, context, {"state": State.INITIAL}, phone_number)

    # 1. Match Python
    resultado = _resolver_seleccion(texto, documentos)

    # 1a. Match único → seleccionar
    if resultado is not None and not isinstance(resultado, dict) or (
        isinstance(resultado, dict) and not resultado.get("_ambiguo")
    ):
        if resultado is not None:
            return _intent("seleccionar_documento",
                           documento_seleccionado=resultado, resultados=[resultado])

    # 1b. Múltiples matches → mostrar sublista filtrada
    if isinstance(resultado, dict) and resultado.get("_ambiguo"):
        sub = resultado["_matches"]
        print(f"📋 Sublista ambigua: {len(sub)} docs para '{texto}'")
        # Actualizar cache con la sublista para que siguiente selección sea más precisa
        conversation_memory.set_conversation_documents(
            phone_number, sub,
            source_intent="sublista_filtrada", source_query=texto
        )
        return _intent(
            "sublista_filtrada",
            resultados=sub,
            query=texto,
            total=len(sub),
        )

    # 2. Fallback Gemini (solo si Python no encontró nada)
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
    # No es sí/no → nueva consulta
    return _handle_free(texto, {}, {"state": State.INITIAL})


def _handle_free(
    texto: str,
    context: Dict,
    conversation_state: Dict,
    phone_number: str = None,
) -> Dict[str, Any]:
    """
    Estado INITIAL o SEARCHING.
    En SEARCHING con lista activa: intenta match en cache antes de ir a DB.
    Orden: cache-first → patrón numérico → follow-up local → router Gemini → fallback.
    """
    estado     = conversation_state.get("state", State.INITIAL)
    tiene_lista = conversation_state.get("has_document_list", False)

    # 0-pre. SEARCHING + lista activa → intentar match en cache primero
    if estado == State.SEARCHING and tiene_lista and phone_number:
        documentos = conversation_memory.get_conversation_documents(phone_number)
        if documentos:
            print(f"📚 Modo filtrado: {len(documentos)} docs")
            doc = _resolver_seleccion(texto, documentos)
            if doc is not None:
                print(f"✅ Campo único: '{texto}'")
                return _intent("seleccionar_documento", documento_seleccionado=doc, resultados=[doc])

            # Múltiples matches → sublista (no ir a DB todavía)
            tl     = texto.lower()
            tokens = [tok for tok in re.findall(r'[\w-]+', texto, re.IGNORECASE) if len(tok) >= 2]
            if tokens:
                sub = [
                    doc for doc in documentos
                    if any(
                        tok.lower() in " ".join([
                            _extraer_campos_doc(doc)["codigo_sistema"],
                            _extraer_campos_doc(doc)["numero_documento"],
                            _extraer_campos_doc(doc)["asunto"],
                            _extraer_campos_doc(doc)["encargado"],
                        ]).lower()
                        for tok in tokens
                    )
                ]
                if sub:
                    print(f"📋 Sublista: {len(sub)} docs filtrados por '{texto}'")
                    return _intent(
                        "buscar_en_lista",
                        parametro=texto,
                        resultados=sub,
                        total=len(sub),
                    )

            # Sin match en cache → caer a búsqueda global
            print(f"🔍 Sin match en cache, pasando a búsqueda global...")

    # 0. Patrones numéricos obvios — sin LLM, sin ambigüedad
    patron = _detectar_patron_numerico(texto)
    if patron:
        print(f"✅ Patrón numérico sin LLM: {patron['intent']} → '{patron['parametro']}'")
        return patron

    # 1. Follow-up contextual sin LLM
    follow_up = _resolver_follow_up(texto, context)
    if follow_up:
        print(f"✅ Follow-up local: {follow_up['intent']}")
        return follow_up

    # 2. Router principal (ia/router.py → Gemini)
    try:
        from ia.router import router
        result = router(texto, context, conversation_state)
        if result:
            return _normalizar_resultado_router(result)
    except Exception as e:
        print(f"⚠️  Error router Gemini: {e}")

    # 3. Fallback básico
    try:
        from services.ia_service import detectar_intencion_optimizado
        return detectar_intencion_optimizado(texto)
    except Exception as e:
        print(f"❌ Error fallback: {e}")

    return _intent("error", error="No pude procesar tu mensaje")


# ── DETECCIÓN DE PATRONES NUMÉRICOS (sin LLM) ────────────────────────────────

def _detectar_patron_numerico(texto: str) -> Optional[Dict[str, Any]]:
    """
    Detecta formatos de código/número que no necesitan LLM.
    Evita que Gemini invente respuestas para códigos obvios.
    """
    t = texto.strip()

    # NNN-YYYY  (ej: 191-2025, 1912-2025)
    if re.match(r'^\d{2,6}-20\d{2}$', t):
        return _intent("seguimiento_por_consecutivo", parametro=t)

    # PR-NNNNNN  (código sistema)
    if re.match(r'^PR-\d+$', t, re.IGNORECASE):
        return _intent("seguimiento_por_codigo", parametro=t.upper())

    # Número largo solo  (5+ dígitos → probablemente consecutivo)
    if re.match(r'^\d{5,}$', t):
        return _intent("seguimiento_por_consecutivo", parametro=t)

    # Código con guiones (ej: 10922-MEP-CMA-PR-114-2025)
    if re.match(r'^[\w]+-[\w]+-[\w-]+$', t) and len(t) > 8:
        return _intent("seguimiento_por_numero_documento", parametro=t)

    return None


# ── RESOLUCIÓN DE SELECCIÓN (Python puro) ─────────────────────────────────────

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
    """
    Match sin IA. Prioridad: posición → ordinal → campos.
    Retorna:
      - dict  → match único
      - None  → sin match o ambiguo (→ Gemini o sublista)
    """
    t  = texto.strip()
    tl = t.lower()

    # 1. Número exacto → posición
    if re.match(r'^\d+$', t):
        idx = int(t) - 1
        if 0 <= idx < len(documentos):
            print(f"✅ Posición {idx + 1}")
            return documentos[idx]
        return None

    # 2. Ordinal textual
    ordinales = {"primero": 0, "primera": 0, "segundo": 1, "segunda": 1,
                 "tercero": 2, "tercera": 2, "cuarto": 3, "cuarta": 3,
                 "quinto": 4, "quinta": 4}
    for palabra, idx in ordinales.items():
        if palabra in tl and idx < len(documentos):
            print(f"✅ Ordinal '{palabra}'")
            return documentos[idx]

    # 3. Búsqueda por campos — tokens separados por guión o espacio
    #    "10922-mep" → tokens ["10922", "mep"]  (para buscar substring independiente)
    tokens_split = [tok for tok in re.split(r'[-_\s]+', t) if len(tok) >= 2]
    tokens_full  = [t]  # también buscar el texto completo como substring

    def _campos_str(doc: Dict) -> str:
        c = _extraer_campos_doc(doc)
        return " ".join([
            c["codigo_sistema"],
            c["numero_documento"],
            c["asunto"],
            c["encargado"],
        ]).lower()

    # Primero: todos los tokens fragmentados deben aparecer (más tolerante)
    if tokens_split:
        matches_split = [d for d in documentos
                         if all(tok.lower() in _campos_str(d) for tok in tokens_split)]
        if len(matches_split) == 1:
            print(f"✅ Campo único (split): '{t}'")
            return matches_split[0]
        if len(matches_split) > 1:
            # Intentar exacto primero
            exactos = [d for d in matches_split
                       if tl == _extraer_campos_doc(d)["numero_documento"].lower()
                       or tl == _extraer_campos_doc(d)["codigo_sistema"].lower()]
            if len(exactos) == 1:
                print(f"✅ Exacto: '{t}'")
                return exactos[0]
            print(f"⚠️  Ambiguo '{t}': {len(matches_split)} matches")
            return {"_ambiguo": True, "_matches": matches_split}   # ← sublista

    # Luego: texto completo como substring
    matches_full = [d for d in documentos if t.lower() in _campos_str(d)]
    if len(matches_full) == 1:
        print(f"✅ Campo substring: '{t}'")
        return matches_full[0]
    if len(matches_full) > 1:
        print(f"⚠️  Ambiguo full '{t}': {len(matches_full)} matches")
        return {"_ambiguo": True, "_matches": matches_full}

    return None


def _resolver_seleccion_con_ia(texto: str, documentos: List[Dict]) -> Optional[Dict]:
    """Fallback Gemini para selecciones que Python no resolvió."""
    try:
        from ia.seleccion import seleccionar_respuesta

        print(f"🤖 Gemini selección: {len(documentos[:20])} docs")
        resultado = seleccionar_respuesta(texto, documentos=documentos[:20])

        if not resultado:
            return None

        params = resultado.get("parameters", {})

        # 1. Por posición_lista
        pos = params.get("posicion_lista")
        if pos is not None:
            idx = int(pos) - 1
            if 0 <= idx < len(documentos):
                print(f"✅ Gemini: posición {idx + 1}")
                return documentos[idx]

        # 2. Por codigo_sistema
        codigo = params.get("codigo_sistema")
        if codigo:
            for doc in documentos:
                if _extraer_campos_doc(doc)["codigo_sistema"].lower() == str(codigo).lower():
                    print(f"✅ Gemini: código {codigo}")
                    return doc

        # 3. Por numero_documento
        numero = params.get("numero_documento")
        if numero:
            for doc in documentos:
                if _extraer_campos_doc(doc)["numero_documento"].lower() == str(numero).lower():
                    print(f"✅ Gemini: número {numero}")
                    return doc

        # 4. Por document_id / cache_id
        doc_id = params.get("document_id")
        if doc_id:
            for doc in documentos:
                inner = doc.get("documento", doc)
                if str(inner.get("id", "")) == str(doc_id):
                    print(f"✅ Gemini: id {doc_id}")
                    return doc

        print(f"⚠️  Gemini no pudo resolver '{texto}'")
    except Exception as e:
        print(f"⚠️  Error Gemini selección: {e}")
    return None


# ── FOLLOW-UP CONTEXTUAL (sin LLM) ────────────────────────────────────────────

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


# ── NORMALIZACIÓN RESULTADO ROUTER ────────────────────────────────────────────

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


# ── HELPER ────────────────────────────────────────────────────────────────────

def _intent(intent: str, **kwargs) -> Dict[str, Any]:
    return {"intent": intent, "parametro": kwargs.pop("parametro", None), **kwargs}