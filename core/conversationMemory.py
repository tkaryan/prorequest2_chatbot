"""
core/conversation_memory.py
────────────────────────────
Memoria conversacional con backend intercambiable (local → Redis).

Migración a Redis:
  from backends.redis_backend import RedisBackend
  conversation_memory = ConversationMemory(backend=RedisBackend(url=REDIS_URL))
"""

import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

from core.states import State


@dataclass
class ConversationTurn:
    timestamp:    float
    user_message: str
    bot_response: str
    intent:       str
    parameters:   Dict[str, Any]
    context:      Dict[str, Any]
    message_type: Optional[str] = None
    flow:         Optional[str] = None


def _default_state() -> Dict[str, Any]:
    return {
        "state":                     State.INITIAL,
        "state_timestamp":           time.time(),
        "has_document_list":         False,
        "last_search_results_count": 0,
        "current_flow":              None,
        "flow_history":              [],
        "nivel_acceso":              None,
        "pending_notification_tipo": None,   # tipo_interno de la última notificación recibida
    }


# ── BACKENDS ──────────────────────────────────────────────────────────────────

class LocalBackend:
    def __init__(self):
        self._turns:  Dict[str, List[dict]] = {}
        self._states: Dict[str, Dict]       = {}
        self._docs:   Dict[str, List[dict]] = {}

    def get_turns(self, phone: str) -> List[dict]:       return self._turns.get(phone, [])
    def set_turns(self, phone: str, v: List[dict]):      self._turns[phone] = v
    def delete_turns(self, phone: str):                  self._turns.pop(phone, None)

    def get_state(self, phone: str) -> Optional[Dict]:   return self._states.get(phone)
    def set_state(self, phone: str, v: Dict):            self._states[phone] = v
    def delete_state(self, phone: str):                  self._states.pop(phone, None)

    def get_docs(self, phone: str) -> List[dict]:        return self._docs.get(phone, [])
    def set_docs(self, phone: str, v: List[dict]):       self._docs[phone] = v
    def delete_docs(self, phone: str):                   self._docs.pop(phone, None)


# ── MEMORIA ───────────────────────────────────────────────────────────────────

class ConversationMemory:

    SESSION_TIMEOUT  = 3600   # 1 hora
    WARN_TIMEOUT     = 3300   # 55 min
    MAX_TURNS        = 10
    MAX_DOCS_CACHE   = 200    # suficiente para notificaciones masivas
    MAX_FLOW_HISTORY = 5

    def __init__(self, backend=None):
        self._b = backend or LocalBackend()

    # ── Estado FSM ────────────────────────────────────────────────────────────

    def _get_or_create_state(self, phone: str) -> Dict:
        s = self._b.get_state(phone)
        if s is None:
            s = _default_state()
            self._b.set_state(phone, s)
        return s

    def _save_state(self, phone: str, s: Dict) -> None:
        s["state_timestamp"] = time.time()
        self._b.set_state(phone, s)

    def _is_expired(self, s: Dict) -> bool:
        return time.time() - s["state_timestamp"] >= self.SESSION_TIMEOUT

    def _reset(self, phone: str) -> None:
        print(f"🔄 Reset conversación: {phone}")
        self._b.set_state(phone, _default_state())
        self._b.delete_docs(phone)

    # Alias para compatibilidad
    _reset_conversation_state = _reset

    def set_conversation_state(self, phone: str, state: str,
                                additional_info: Dict = None) -> None:
        s = self._get_or_create_state(phone)
        s["state"] = state
        if additional_info:
            s.update(additional_info)
        self._save_state(phone, s)
        print(f"🔄 Estado → {state} [{phone}]")

    def get_conversation_state(self, phone: str) -> Dict[str, Any]:
        s = self._get_or_create_state(phone)
        if self._is_expired(s):
            self._reset(phone)
            s = self._get_or_create_state(phone)

        elapsed = time.time() - s["state_timestamp"]
        state   = s["state"]

        return {
            "state":                     state,
            "has_document_list":         s["has_document_list"],
            "should_search_full_db":     self._should_search_full_db(s),
            "last_search_results_count": s["last_search_results_count"],
            "time_since_last_activity":  elapsed,
            "will_timeout_soon":         elapsed > self.WARN_TIMEOUT,
            "current_flow":              s.get("current_flow"),
            "flow_history":              s.get("flow_history", []),
            "pending_notification_tipo": s.get("pending_notification_tipo"),
        }

    def _should_search_full_db(self, s: Dict) -> bool:
        """
        True  → buscar en toda la base de datos.
        False → el usuario está navegando una lista ya cargada.
        """
        state = s["state"]
        if state in (State.INITIAL,):
            return True
        if state == State.SEARCHING:
            # Tiene resultados en memoria pero puede hacer búsqueda nueva
            return not s["has_document_list"]
        if state in (State.AWAITING_SELECTION, State.AWAITING_CONFIRMATION):
            return False
        return True

    def set_user_role(self, phone: str, nivel_acceso: str) -> None:
        s = self._get_or_create_state(phone)
        s["nivel_acceso"] = nivel_acceso
        self._b.set_state(phone, s)
        print(f"👤 Rol '{nivel_acceso}' → {phone}")

    # ── Turnos ────────────────────────────────────────────────────────────────

    def add_turn(self, phone: str, user_message: str, bot_response: str,
                 intent: str, parameters: Dict = None, context: Dict = None,
                 message_type: str = None, flow: str = None) -> None:
        try:
            turn = asdict(ConversationTurn(
                timestamp=time.time(),
                user_message=user_message,
                bot_response=bot_response,
                intent=intent,
                parameters=parameters or {},
                context=context or {},
                message_type=message_type,
                flow=flow,
            ))
            turns = self._purge_old_turns(self._b.get_turns(phone))
            turns.append(turn)
            self._b.set_turns(phone, turns[-self.MAX_TURNS:])
        except Exception as e:
            print(f"❌ Error en add_turn: {e}")

    def _purge_old_turns(self, turns: List[dict]) -> List[dict]:
        cutoff = time.time() - self.SESSION_TIMEOUT
        fresh  = [t for t in turns if t["timestamp"] >= cutoff]
        if len(fresh) < len(turns):
            print(f"🧹 {len(turns) - len(fresh)} turnos expirados eliminados")
        return fresh

    def get_conversation_history(self, phone: str, last_n: int = 5) -> List[dict]:
        turns = self._purge_old_turns(self._b.get_turns(phone))
        return turns[-last_n:]

    # ── Contexto ──────────────────────────────────────────────────────────────

    def get_conversation_context(self, phone: str) -> Dict[str, Any]:
        try:
            history    = self.get_conversation_history(phone, 5)
            conv_state = self.get_conversation_state(phone)
            raw_state  = self._get_or_create_state(phone)

            context: Dict[str, Any] = {
                "conversation_state":    conv_state["state"],
                "has_document_list":     conv_state["has_document_list"],
                "should_search_full_db": conv_state["should_search_full_db"],
                "current_flow":          conv_state["current_flow"],
                "awaiting_confirmation": conv_state["state"] in (
                    State.AWAITING_SELECTION, State.AWAITING_CONFIRMATION
                ),
                "is_follow_up":          len(history) > 0,
                "session_length":        len(history),
                "last_intent":           None,
                "last_parameters":       {},
                "nivel_acceso":          raw_state.get("nivel_acceso"),
                "recent_documents":      [],
                "recent_projects":       [],
                "recent_users":          [],
                "recent_searches":       [],
                "conversation_flow":     [],
            }

            if not history:
                return context

            last = history[-1]
            context["last_intent"]     = last["intent"]
            context["last_parameters"] = last["parameters"]

            for i, turn in enumerate(history):
                params = turn.get("parameters") or {}
                context["conversation_flow"].append({
                    "intent":       turn["intent"],
                    "timestamp":    turn["timestamp"],
                    "position":     i,
                    "message_type": turn.get("message_type"),
                })

                if params.get("document_id"):
                    context["recent_documents"].append(params["document_id"])
                if params.get("parametro") and turn["intent"].startswith("seguimiento_por"):
                    context["recent_documents"].append(params["parametro"])
                if params.get("proyecto"):
                    context["recent_projects"].append(params["proyecto"])
                if params.get("usuario"):
                    context["recent_users"].append(params["usuario"])

                search_term = params.get("consulta") or (
                    params.get("parametro") if turn["intent"] == "buscar_documentos" else None
                )
                if search_term:
                    context["recent_searches"].append(search_term)

            for key, limit in [("recent_documents", 5), ("recent_projects", 3),
                                ("recent_users", 3),    ("recent_searches", 3)]:
                context[key] = list(dict.fromkeys(context[key]))[:limit]

            return context

        except Exception as e:
            print(f"❌ Error en get_conversation_context: {e}")
            return self._empty_context()

    def _empty_context(self) -> Dict[str, Any]:
        return {
            "conversation_state": State.INITIAL, "has_document_list": False,
            "should_search_full_db": True, "current_flow": None,
            "awaiting_confirmation": False, "is_follow_up": False,
            "session_length": 0, "last_intent": None, "last_parameters": {},
            "nivel_acceso": None, "recent_documents": [], "recent_projects": [],
            "recent_users": [], "recent_searches": [], "conversation_flow": [],
        }

    # ── Documentos ────────────────────────────────────────────────────────────

    def set_conversation_documents(self, phone_number: str, documents: List[Dict],
                                   source_intent: str = None,
                                   source_query: str = None) -> bool:
        try:
            if not documents or not isinstance(documents, list):
                print("⚠️ No hay documentos válidos para guardar")
                return False

            ts = time.time()
            enriched = [
                {**doc,
                 "source_intent": source_intent,
                 "source_query":  source_query,
                 "cached_at":     ts,
                 "cache_id":      f"{phone_number}_{int(ts)}_{i}"}
                for i, doc in enumerate(documents) if isinstance(doc, dict)
            ]
            # Documentos nuevos al frente, respetar MAX_DOCS_CACHE
            merged = (enriched + self._b.get_docs(phone_number))[:self.MAX_DOCS_CACHE]
            self._b.set_docs(phone_number, merged)
            print(f"📚 {len(enriched)} docs guardados [{source_intent}] total={len(merged)}")
            return True
        except Exception as e:
            print(f"❌ Error guardando docs: {e}")
            return False

    def get_conversation_documents(self, phone_number: str,
                                   limit: int = None,
                                   filter_by: Dict[str, Any] = None) -> List[Dict]:
        try:
            docs = self._b.get_docs(phone_number)
            if filter_by:
                docs = [d for d in docs if all(d.get(k) == v for k, v in filter_by.items())]
            if limit and limit > 0:
                docs = docs[:limit]
            print(f"📖 {len(docs)} docs recuperados [{phone_number}]")
            return docs
        except Exception as e:
            print(f"❌ Error obteniendo docs: {e}")
            return []

    # ── Limpieza periódica ────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Llamar desde un scheduler cada 30 min."""
        now     = time.time()
        backend = self._b
        if not hasattr(backend, '_states'):
            return  # Redis maneja su propio TTL

        expired = [
            phone for phone, s in backend._states.items()
            if now - s["state_timestamp"] > self.SESSION_TIMEOUT
        ]
        for phone in expired:
            print(f"🧹 Sesión expirada: {phone}")
            backend.delete_state(phone)
            backend.delete_turns(phone)
            backend.delete_docs(phone)
        if expired:
            print(f"🧹 {len(expired)} sesiones eliminadas")


conversation_memory = ConversationMemory()