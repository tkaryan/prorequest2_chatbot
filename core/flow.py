"""
core/flow.py
────────────
Enrutador FSM — responsabilidad única:
  Dado el estado actual + mensaje → retorna intent_data estandarizado.

No detecta intenciones (eso es ia/router.py via Gemini).
No formatea respuestas (formatter).
No ejecuta acciones de DB (procesar_mensaje).

Estados válidos (core/states.py):
  INITIAL             → consulta libre
  SEARCHING           → tiene resultados en memoria, puede refinar
  AWAITING_SELECTION  → usuario debe elegir de una lista
  AWAITING_CONFIRMATION → usuario debe confirmar sí/no
"""

import re
from typing import Any, Dict, List, Optional

from core.conversationMemory import conversation_memory
from core.states import State

_POSITIVAS = {"si", "sí", "yes", "correcto", "exacto", "ese", "perfecto", "está bien", "ok", "dale"}
_NEGATIVAS = {"no", "nope", "incorrecto", "otro", "diferente", "no es", "nop"}


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def detectar_intencion_con_contexto(
    texto_usuario: str,
    phone_number: str,
    conversation_context: Dict = None,
    conversation_state: Dict = None,
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

    # INITIAL y SEARCHING van al router de Gemini
    return _handle_free(texto, conversation_context, conversation_state)


# ── HANDLERS POR ESTADO ───────────────────────────────────────────────────────

def _handle_awaiting_selection(
    texto: str,
    phone_number: str,
    context: Dict,
) -> Dict[str, Any]:
    """
    El usuario está eligiendo de una lista.
    Intenta match puro Python primero; si falla, usa Gemini.
    No sale de este estado salvo reset manual ('Hola').
    """
    documentos = conversation_memory.get_conversation_documents(phone_number)

    if not documentos:
        # Sin lista en memoria → tratar como consulta nueva
        print("⚠️  AWAITING_SELECTION sin docs en memoria, delegando a free handler")
        return _handle_free(texto, context, {"state": State.INITIAL})

    # 1. Match puro Python
    doc = _resolver_seleccion(texto, documentos)
    if doc is not None:
        return _intent("seleccionar_documento", documento_seleccionado=doc, resultados=[doc])

    # 2. Fallback Gemini (solo si Python no encontró nada)
    doc_ia = _resolver_seleccion_con_ia(texto, documentos)
    if doc_ia is not None:
        return _intent("seleccionar_documento", documento_seleccionado=doc_ia, resultados=[doc_ia])

    # 3. No encontrado → mantener en AWAITING_SELECTION, pedir más detalle
    print(f"⚠️  No se encontró '{texto}' en los {len(documentos)} docs")
    return _intent(
        "error_seleccion_lista",
        error=(
            f"No encontré *'{texto}'* en la lista.\n\n"
            f"Puedes intentar con:\n"
            f"• El *número* de posición: 1, 2, 3...\n"
            f"• El *código*: ej. PR-001540\n"
            f"• Parte del *asunto*\n"
            f"• Nombre del *encargado*\n\n"
            f"Si quieres iniciar una nueva búsqueda, escribe *'Hola'*"
        )
    )


def _handle_awaiting_confirmation(texto: str, phone_number: str) -> Dict[str, Any]:
    """Sí/No tras ver el detalle de un documento."""
    texto_lower = texto.lower().strip()

    if any(p in texto_lower for p in _POSITIVAS):
        return _intent("confirmar_seleccion", confirmacion_positiva=True)

    if any(n in texto_lower for n in _NEGATIVAS):
        return _intent("confirmar_seleccion", confirmacion_positiva=False)

    # No es confirmación → tratar como consulta nueva
    print("⚠️  AWAITING_CONFIRMATION recibió texto inesperado, procesando como consulta")
    return _handle_free(texto, {}, {"state": State.INITIAL})


def _handle_free(
    texto: str,
    context: Dict,
    conversation_state: Dict,
) -> Dict[str, Any]:
    """
    Estado INITIAL o SEARCHING: detección libre via router Gemini.
    Primero intenta follow-up local (rápido, sin LLM).
    """
    # Follow-up contextual sin LLM
    follow_up = _resolver_follow_up(texto, context)
    if follow_up:
        print(f"✅ Follow-up local: {follow_up['intent']}")
        return follow_up

    # Router principal (ia/router.py → Gemini)
    try:
        from ia import router
        result = router(texto, context, conversation_state)
        if result:
            return _normalizar_resultado_router(result)
    except Exception as e:
        print(f"⚠️  Error en router Gemini: {e}")

    # Fallback básico
    try:
        from services.ia_service import detectar_intencion_optimizado
        return detectar_intencion_optimizado(texto)
    except Exception as e:
        print(f"❌ Error en detección básica: {e}")

    return _intent("error", error="No pude procesar tu mensaje")


# ── RESOLUCIÓN DE SELECCIÓN (Python puro) ─────────────────────────────────────

def _extraer_campos_doc(doc: Dict) -> Dict:
    """
    Normaliza un doc independientemente de si los campos están
    en top-level o anidados dentro de doc['documento'].
    """
    inner = doc.get("documento", doc)
    encargado = ""
    encargados = doc.get("encargados") or inner.get("encargados") or []
    if encargados and isinstance(encargados, list):
        first = encargados[0]
        if isinstance(first, dict):
            encargado = f"{first.get('nombres', '')} {first.get('apellido_paterno', '')}".strip()
        else:
            encargado = str(first)

    return {
        "codigo_sistema":   inner.get("codigo_sistema", ""),
        "numero_documento": inner.get("numero_documento", ""),
        "asunto":           inner.get("asunto", ""),
        "estado":           inner.get("estado", ""),
        "encargado":        encargado,
    }


def _resolver_seleccion(texto: str, documentos: List[Dict]) -> Optional[Dict]:
    """
    Match directo sin IA.
    Prioridad: posición numérica → ordinal → búsqueda por campos.
    """
    texto_strip = texto.strip()
    texto_lower = texto_strip.lower()

    # 1. Número exacto → posición en lista
    if re.match(r'^\d+$', texto_strip):
        idx = int(texto_strip) - 1
        if 0 <= idx < len(documentos):
            print(f"✅ Selección por posición {idx + 1}")
            return documentos[idx]
        return None  # número fuera de rango, no seguir buscando

    # 2. Ordinal textual
    ordinales = {
        "primero": 0, "primera": 0,
        "segundo": 1, "segunda": 1,
        "tercero": 2, "tercera": 2,
        "cuarto":  3, "cuarta":  3,
        "quinto":  4, "quinta":  4,
    }
    for palabra, idx in ordinales.items():
        if palabra in texto_lower and idx < len(documentos):
            print(f"✅ Selección por ordinal '{palabra}'")
            return documentos[idx]

    # 3. Búsqueda por campos normalizados
    tokens = [t for t in re.findall(r'[\w-]+', texto_strip, re.IGNORECASE) if len(t) >= 2]
    if not tokens:
        return None

    matches = []
    for doc in documentos:
        campos = _extraer_campos_doc(doc)
        haystack = " ".join(
            str(v or "")
            for v in [
                campos.get("codigo_sistema"),
                campos.get("numero_documento"),
                campos.get("asunto"),
                campos.get("encargado"),
            ]
        ).lower()

        if all(token.lower() in haystack for token in tokens):
            matches.append(doc)

    if len(matches) == 1:
        print(f"✅ Selección por campo único: '{texto}'")
        return matches[0]

    if len(matches) > 1:
        # Intentar match más exacto en número_documento o codigo_sistema
        exactos = [
            d for d in matches
            if texto_lower == _extraer_campos_doc(d)["numero_documento"].lower()
            or texto_lower == _extraer_campos_doc(d)["codigo_sistema"].lower()
        ]
        if len(exactos) == 1:
            print(f"✅ Selección exacta: '{texto}'")
            return exactos[0]
        # Ambiguo → pasa a Gemini
        print(f"⚠️  '{texto}' ambiguo: {len(matches)} matches → pasando a IA")
        return None

    return None


def _resolver_seleccion_con_ia(texto: str, documentos: List[Dict]) -> Optional[Dict]:
    """
    Fallback Gemini para selecciones que Python no pudo resolver.
    Envía un resumen compacto (máx 20 docs) con campos normalizados.
    """
    try:
        from services.ia_service import seleccionar_de_lista

        resumen = [
            {
                "idx":     i + 1,
                **{k: v for k, v in _extraer_campos_doc(doc).items()
                   if k in ("codigo_sistema", "numero_documento", "encargado")},
                "asunto":  _extraer_campos_doc(doc)["asunto"][:80],
            }
            for i, doc in enumerate(documentos[:20])
        ]

        print(f"🤖 Enviando a Gemini {len(resumen)} docs normalizados para selección")
        resultado = seleccionar_de_lista(texto, resumen)

        if resultado and resultado.get("idx") is not None:
            idx = int(resultado["idx"]) - 1
            if 0 <= idx < len(documentos):
                print(f"✅ Selección por Gemini: posición {idx + 1}")
                return documentos[idx]

    except Exception as e:
        print(f"⚠️  Error en selección Gemini: {e}")

    return None


# ── FOLLOW-UP CONTEXTUAL (sin LLM) ────────────────────────────────────────────

def _resolver_follow_up(texto: str, context: Dict) -> Optional[Dict[str, Any]]:
    if not context.get("is_follow_up"):
        return None

    texto_lower = texto.lower().strip()

    if any(w in texto_lower for w in ["este", "ese", "el documento", "el anterior"]):
        if context.get("recent_documents"):
            return _intent("seguimiento_por_numero_documento",
                           parametro=context["recent_documents"][0],
                           is_follow_up=True)

    if any(w in texto_lower for w in ["este proyecto", "ese proyecto", "el proyecto"]):
        if context.get("recent_projects"):
            return _intent("seguimiento_por_proyecto",
                           parametro=context["recent_projects"][0],
                           is_follow_up=True)

    return None


# ── NORMALIZACIÓN RESULTADO ROUTER ────────────────────────────────────────────

def _normalizar_resultado_router(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convierte la salida del router Gemini (ia/router.py) al formato
    estándar que espera procesar_mensaje.
    """
    intent     = result.get("intent", "unknown")
    parameters = result.get("parameters", {})

    # Mapeo intent → campo del parámetro principal
    PARAM_MAP = {
        "seguimiento_por_codigo":           "document_id",
        "seguimiento_por_numero_documento": "document_id",
        "seguimiento_por_consecutivo":      "document_id",
        "seguimiento_por_usuario":          "usuario",
        "seguimiento_por_proyecto":         "proyecto",
        "seguimiento_por_asunto":           "consulta",
        "buscar_documentos":                "consulta",
        "seleccionar_opcion":               "posicion_lista",
    }

    parametro = parameters.get(PARAM_MAP.get(intent, ""), None)

    normalized: Dict[str, Any] = {"intent": intent, "parametro": parametro}

    # Propagar campos opcionales relevantes
    for campo in (
        "confirmacion_positiva", "posicion_lista", "is_follow_up",
        "search_in_filtered", "notification_index", "post_detail_action",
        "next_state",
    ):
        if campo in parameters:
            normalized[campo] = parameters[campo]

    return normalized


# ── HELPER ────────────────────────────────────────────────────────────────────

def _intent(intent: str, **kwargs) -> Dict[str, Any]:
    return {"intent": intent, "parametro": kwargs.pop("parametro", None), **kwargs}