"""
core/conversation_memory.py
────────────────────────────
Memoria conversacional con backend intercambiable (LocalBackend / RedisBackend).

Producción → Redis:
    import redis
    from core.conversation_memory import ConversationMemory, RedisBackend
    r = redis.from_url(os.getenv("REDIS_URL"))
    conversation_memory = ConversationMemory(backend=RedisBackend(client=r))
"""

import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

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
        "pending_notification_tipo": None,   
        "is_notification_flow":      False,  
    }


# ── BACKENDS ──────────────────────────────────────────────────────────────────

class LocalBackend:
    """In-memory. Solo para desarrollo — se pierde al reiniciar."""

    def __init__(self):
        self._turns:  Dict[str, List[dict]] = {}
        self._states: Dict[str, dict]       = {}
        self._docs:   Dict[str, List[dict]] = {}

    def get_turns(self, p: str) -> List[dict]: return self._turns.get(p, [])
    def set_turns(self, p: str, v: List[dict]): self._turns[p] = v
    def delete_turns(self, p: str): self._turns.pop(p, None)

    def get_state(self, p: str) -> Optional[dict]: return self._states.get(p)
    def set_state(self, p: str, v: dict): self._states[p] = v
    def delete_state(self, p: str): self._states.pop(p, None)

    def get_docs(self, p: str) -> List[dict]: return self._docs.get(p, [])
    def set_docs(self, p: str, v: List[dict]): self._docs[p] = v
    def delete_docs(self, p: str): self._docs.pop(p, None)

    def iter_states(self):
        """Usado por cleanup(). Redis no necesita esto (TTL automático)."""
        return list(self._states.items())


class RedisBackend:
    """
    Backend Redis con TTL automático.
    Requiere: pip install redis

    Ejemplo:
        import redis, os
        client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        backend = RedisBackend(client=client)
        conversation_memory = ConversationMemory(backend=backend)
    """

    def __init__(self, client, ttl: int = 3600, prefix: str = "chatbot"):
        self._r      = client
        self._ttl    = ttl
        self._prefix = prefix

    def _k(self, phone: str, kind: str) -> str:
        return f"{self._prefix}:{kind}:{phone}"

    def _get(self, key: str):
        raw = self._r.get(key)
        return json.loads(raw) if raw else None

    def _set(self, key: str, value):
        self._r.setex(key, self._ttl, json.dumps(value, default=str))

    def get_turns(self, p: str) -> List[dict]: return self._get(self._k(p, "turns")) or []
    def set_turns(self, p: str, v: List[dict]): self._set(self._k(p, "turns"), v)
    def delete_turns(self, p: str): self._r.delete(self._k(p, "turns"))

    def get_state(self, p: str) -> Optional[dict]: return self._get(self._k(p, "state"))
    def set_state(self, p: str, v: dict): self._set(self._k(p, "state"), v)
    def delete_state(self, p: str): self._r.delete(self._k(p, "state"))

    def get_docs(self, p: str) -> List[dict]: return self._get(self._k(p, "docs")) or []
    def set_docs(self, p: str, v: List[dict]): self._set(self._k(p, "docs"), v)
    def delete_docs(self, p: str): self._r.delete(self._k(p, "docs"))

    def iter_states(self): return [] 



class ConversationMemory:

    SESSION_TIMEOUT  = 3600
    WARN_TIMEOUT     = 3300
    MAX_TURNS        = 10
    MAX_DOCS_CACHE   = 200
    MAX_FLOW_HISTORY = 5

    def __init__(self, backend=None):
        self._b = backend or LocalBackend()


    def _get_or_create_state(self, phone: str) -> dict:
        s = self._b.get_state(phone)
        if s is None:
            s = _default_state()
            self._b.set_state(phone, s)
        return s

    def _save_state(self, phone: str, s: dict) -> None:
        s["state_timestamp"] = time.time()
        self._b.set_state(phone, s)

    def _is_expired(self, s: dict) -> bool:
        return time.time() - s.get("state_timestamp", 0) >= self.SESSION_TIMEOUT

    def _reset(self, phone: str) -> None:
        print(f"🔄 Reset: {phone}")
        self._b.set_state(phone, _default_state())
        self._b.delete_docs(phone)

    _reset_conversation_state = _reset 

    def set_conversation_state(self, phone: str, state: str,
                                additional_info: dict = None) -> None:
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
        return {
            "state":                     s["state"],
            "has_document_list":         s["has_document_list"],
            "should_search_full_db":     self._should_search_full_db(s),
            "last_search_results_count": s["last_search_results_count"],
            "time_since_last_activity":  elapsed,
            "will_timeout_soon":         elapsed > self.WARN_TIMEOUT,
            "current_flow":              s.get("current_flow"),
            "flow_history":              s.get("flow_history", []),
            "pending_notification_tipo": s.get("pending_notification_tipo"),
            "is_notification_flow":      s.get("is_notification_flow", False),
        }

    def _should_search_full_db(self, s: dict) -> bool:
        state = s["state"]
        if state == State.INITIAL:
            return True
        if state == State.SEARCHING:
            return not s.get("has_document_list", False)
        if state in (State.AWAITING_SELECTION, State.AWAITING_CONFIRMATION):
            return False
        return True

    def set_user_role(self, phone: str, nivel_acceso: str) -> None:
        s = self._get_or_create_state(phone)
        s["nivel_acceso"] = nivel_acceso
        self._b.set_state(phone, s)
        print(f"👤 Rol '{nivel_acceso}' → {phone}")


    def add_turn(self, phone: str, user_message: str, bot_response: str,
                 intent: str, parameters: dict = None, context: dict = None,
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
            print(f"🧹 {len(turns) - len(fresh)} turnos expirados")
        return fresh

    def get_conversation_history(self, phone: str, last_n: int = 5) -> List[dict]:
        return self._purge_old_turns(self._b.get_turns(phone))[-last_n:]


    def get_conversation_context(self, phone: str) -> Dict[str, Any]:
        try:
            history    = self.get_conversation_history(phone, 5)
            conv_state = self.get_conversation_state(phone)
            raw_state  = self._get_or_create_state(phone)

            ctx: Dict[str, Any] = {
                "conversation_state":    conv_state["state"],
                "has_document_list":     conv_state["has_document_list"],
                "should_search_full_db": conv_state["should_search_full_db"],
                "current_flow":          conv_state["current_flow"],
                "is_notification_flow":  conv_state["is_notification_flow"],
                "awaiting_confirmation": conv_state["state"] in (
                    State.AWAITING_SELECTION, State.AWAITING_CONFIRMATION),
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
                return ctx

            last = history[-1]
            ctx["last_intent"]     = last["intent"]
            ctx["last_parameters"] = last["parameters"]

            for i, turn in enumerate(history):
                params = turn.get("parameters") or {}
                ctx["conversation_flow"].append({
                    "intent":       turn["intent"],
                    "timestamp":    turn["timestamp"],
                    "position":     i,
                    "message_type": turn.get("message_type"),
                    "flow":         turn.get("flow"),
                })
                if params.get("document_id"):
                    ctx["recent_documents"].append(params["document_id"])
                if params.get("parametro") and turn["intent"].startswith("seguimiento_por"):
                    ctx["recent_documents"].append(params["parametro"])
                if params.get("proyecto"):
                    ctx["recent_projects"].append(params["proyecto"])
                if params.get("usuario"):
                    ctx["recent_users"].append(params["usuario"])
                st = params.get("consulta") or (
                    params.get("parametro") if turn["intent"] == "buscar_documentos" else None)
                if st:
                    ctx["recent_searches"].append(st)

            for key, limit in [("recent_documents", 5), ("recent_projects", 3),
                                ("recent_users", 3),    ("recent_searches", 3)]:
                ctx[key] = list(dict.fromkeys(ctx[key]))[:limit]

            return ctx
        except Exception as e:
            print(f"❌ Error en get_conversation_context: {e}")
            return self._empty_context()

    def _empty_context(self) -> Dict[str, Any]:
        return {
            "conversation_state": State.INITIAL, "has_document_list": False,
            "should_search_full_db": True, "current_flow": None,
            "is_notification_flow": False, "awaiting_confirmation": False,
            "is_follow_up": False, "session_length": 0,
            "last_intent": None, "last_parameters": {}, "nivel_acceso": None,
            "recent_documents": [], "recent_projects": [],
            "recent_users": [], "recent_searches": [], "conversation_flow": [],
        }


    def set_conversation_documents(self, phone: str, documents: List[dict],
                                   source_intent: str = None,
                                   source_query: str = None) -> bool:
        try:
            if not documents or not isinstance(documents, list):
                return False

            existing     = self._b.get_docs(phone)
            existing_ids = set()
            for d in existing:
                inner = d.get("documento", d)
                k = inner.get("numero_documento") or inner.get("codigo_sistema")
                if k:
                    existing_ids.add(k)

            ts, enriched = time.time(), []
            for i, doc in enumerate(documents):
                if not isinstance(doc, dict):
                    continue
                inner = doc.get("documento", doc)
                k = inner.get("numero_documento") or inner.get("codigo_sistema")
                if k and k in existing_ids:
                    continue
                enriched.append({
                    **doc,
                    "source_intent": source_intent,
                    "source_query":  source_query,
                    "cached_at":     ts,
                    "cache_id":      f"{phone}_{int(ts)}_{i}",
                })
                if k:
                    existing_ids.add(k)

            merged = (enriched + existing)[:self.MAX_DOCS_CACHE]
            self._b.set_docs(phone, merged)
            print(f"📚 +{len(enriched)} docs [{source_intent}] total={len(merged)}")
            return True
        except Exception as e:
            print(f"❌ Error guardando docs: {e}")
            return False

    def get_conversation_documents(self, phone: str,
                                   limit: int = None,
                                   filter_by: Dict[str, Any] = None) -> List[dict]:
        try:
            docs = self._b.get_docs(phone)
            if filter_by:
                docs = [d for d in docs if all(d.get(k) == v for k, v in filter_by.items())]
            if limit and limit > 0:
                docs = docs[:limit]
            print(f"📖 {len(docs)} docs [{phone}]")
            return docs
        except Exception as e:
            print(f"❌ Error obteniendo docs: {e}")
            return []


    def cleanup(self) -> None:
        """Llamar desde scheduler. Redis gestiona TTL automáticamente."""
        now     = time.time()
        expired = [p for p, s in self._b.iter_states()
                   if now - s.get("state_timestamp", 0) > self.SESSION_TIMEOUT]
        for p in expired:
            self._b.delete_state(p)
            self._b.delete_turns(p)
            self._b.delete_docs(p)
        if expired:
            print(f"🧹 {len(expired)} sesiones expiradas eliminadas")


# ── Instancia global ──────────────────────────────────────────────────────────
# Desarrollo: LocalBackend (in-memory)
conversation_memory = ConversationMemory()

# Producción (descomentar y configurar REDIS_URL):
# import os, redis
# conversation_memory = ConversationMemory(
#     backend=RedisBackend(client=redis.from_url(os.getenv("REDIS_URL")))
# )