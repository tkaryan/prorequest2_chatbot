import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ConversationTurn:
    timestamp:    float
    user_message: str
    bot_response: str
    intent:       str
    parameters:   Dict[str, Any]


class ConversationMemory:

    VALID_STATES = {"INITIAL", "AWAITING_SELECTION", "AWAITING_CONFIRMATION", "AWAITING_POST_DETAIL"}

    def __init__(self, max_turns: int = 10, session_timeout: int = 3600):
        self.conversations: Dict[str, List[ConversationTurn]] = {}
        self.states:        Dict[str, Dict]                   = {}
        self.documents:     Dict[str, List[Dict]]             = {}
        self.max_turns       = max_turns
        self.session_timeout = session_timeout


    def get_state(self, phone: str) -> Dict:
        """Retorna estado actual. Expira sesión si superó timeout (lazy expiry)."""
        if phone not in self.states:
            self.states[phone] = self._default_state()

        state = self.states[phone]

        if time.time() - state["updated_at"] > self.session_timeout:
            print(f"⏰ Sesión expirada para {phone}, reseteando")
            self._reset(phone)

        return self.states[phone]

    def set_state(self, phone: str, state: str, extra: Dict = None) -> None:
        if state not in self.VALID_STATES:
            print(f"⚠️ Estado inválido: {state}")

        if phone not in self.states:
            self.states[phone] = self._default_state()

        self.states[phone]["state"]      = state
        self.states[phone]["updated_at"] = time.time()

        if extra:
            self.states[phone].update(extra)

        print(f"🔄 Estado → {state} [{phone}]")

    def set_user_role(self, phone: str, nivel_acceso: str) -> None:
        """Guarda el rol en el estado, sin crear turnos de sistema."""
        if phone not in self.states:
            self.states[phone] = self._default_state()
        self.states[phone]["nivel_acceso"] = nivel_acceso

    def _default_state(self) -> Dict:
        return {
            "state":        "INITIAL",
            "updated_at":   time.time(),
            "nivel_acceso": None,
        }

    def _reset(self, phone: str) -> None:
        self.states[phone]   = self._default_state()
        self.documents.pop(phone, None)


    def set_documents(self, phone: str, documents: List[Dict],
                      source_intent: str = None, source_query: str = None) -> None:
        """
        Guarda documentos enriquecidos con source_intent/source_query.
        procesar_mensaje los usa para saber si viene de notificación o búsqueda.
        """
        if not documents or not isinstance(documents, list):
            print("⚠️ No hay documentos válidos para guardar")
            return

        ts = time.time()
        enriched = [
            {**doc, "source_intent": source_intent,
                    "source_query":  source_query,
                    "cached_at":     ts}
            for doc in documents if isinstance(doc, dict)
        ]

        self.documents[phone] = enriched[:50]
        print(f"📚 Guardados {len(enriched)} docs [{source_intent}]")

    def get_documents(self, phone: str) -> List[Dict]:
        return self.documents.get(phone, [])


    def add_turn(self, phone: str, user: str, bot: str,
                 intent: str, parameters: Dict = None) -> None:
        if phone not in self.conversations:
            self.conversations[phone] = []

        self.conversations[phone].append(ConversationTurn(
            timestamp=time.time(),
            user_message=user,
            bot_response=bot,
            intent=intent,
            parameters=parameters or {},
        ))

        self.conversations[phone] = self.conversations[phone][-self.max_turns:]


    def get_context(self, phone: str) -> Dict[str, Any]:
        """
        Contexto que recibe el router y procesar_mensaje.
        Incluye nivel_acceso y should_search_full_db.
        """
        history = self.conversations.get(phone, [])
        state   = self.get_state(phone)

        recent_docs:    List[str] = []
        recent_searches: List[str] = []

        for turn in history:
            params = turn.parameters
            if params.get("document_id"):
                recent_docs.append(params["document_id"])
            if params.get("query"):
                recent_searches.append(params["query"])

        return {
            "last_intent":          history[-1].intent if history else None,
            "recent_documents":     list(dict.fromkeys(recent_docs))[:3],
            "recent_searches":      list(dict.fromkeys(recent_searches))[:3],
            "is_follow_up":         len(history) > 0,
            "session_length":       len(history),
            "nivel_acceso":         state.get("nivel_acceso"),
            "should_search_full_db": state["state"] == "INITIAL",
            "conversation_state":   state["state"],
        }


    def cleanup(self) -> None:
        """Limpieza periódica. Llama esto desde un scheduler (APScheduler, etc.)"""
        now     = time.time()
        expired = [
            phone for phone, state in self.states.items()
            if now - state["updated_at"] > self.session_timeout
        ]

        for phone in expired:
            print(f"🧹 Limpiando sesión expirada: {phone}")
            self.states.pop(phone, None)
            self.conversations.pop(phone, None)
            self.documents.pop(phone, None)

        if expired:
            print(f"🧹 {len(expired)} sesiones eliminadas")


conversation_memory = ConversationMemory()