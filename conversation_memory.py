import json
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

@dataclass
class ConversationTurn:
    """Representa un turno de conversación con estados adicionales"""
    timestamp: float
    user_message: str
    bot_response: str
    intent: str
    parameters: Dict[str, Any]
    context: Dict[str, Any]
    message_type: str = None  # "verificacion", "eleccion", "consulta"
    
    def to_dict(self):
        """Convierte a diccionario para debugging"""
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S"),
            "user_message": self.user_message[:50] + "..." if len(self.user_message) > 50 else self.user_message,
            "bot_response": self.bot_response[:50] + "..." if len(self.bot_response) > 50 else self.bot_response,
            "intent": self.intent,
            "parameters": self.parameters,
            "message_type": self.message_type
        }

class ConversationMemory:
    """Maneja la memoria conversacional con flujo de confirmación"""
    def __init__(self, max_turns=10, session_timeout_minutes=60, max_documents_cache=50):
        self.conversations: Dict[str, List[ConversationTurn]] = {}
        self.max_turns = max_turns
        self.session_timeout = session_timeout_minutes * 60
        self.document_cache: Dict[str, List[Dict]] = {}
        self.max_documents_cache = max_documents_cache
        
        # NUEVO: Estados de conversación
        self.conversation_states: Dict[str, Dict[str, Any]] = {}
        
    def add_turn(self, phone_number: str, user_message: str, bot_response: str, 
                 intent: str, parameters: Dict = None, context: Dict = None,
                 message_type: str = None):
        """Añade un turno con información de confirmación"""
        try:
            if phone_number not in self.conversations:
                self.conversations[phone_number] = []
                
            turn = ConversationTurn(
                timestamp=time.time(),
                user_message=user_message,
                bot_response=bot_response,
                intent=intent,
                parameters=parameters or {},
                context=context or {},
                message_type=message_type,
            )
            
            self.conversations[phone_number].append(turn)
            self._cleanup_old_turns(phone_number)
            
            if len(self.conversations[phone_number]) > self.max_turns:
                self.conversations[phone_number] = self.conversations[phone_number][-self.max_turns:]
            
            # NUEVO: Actualizar estado según message_type y resultados
            self._update_conversation_state(phone_number, message_type, parameters)
            
        except Exception as e:
            print(f"❌ Error guardando en memoria: {type(e).__name__} - {e}")

    def _update_conversation_state(self, phone_number: str, message_type: str, parameters: Dict = None):
        """Actualiza el estado de la conversación basado en el flujo"""
        if phone_number not in self.conversation_states:
            self.conversation_states[phone_number] = {
                "state": "initial",  # initial, awaiting_choice, awaiting_verification, filtered_search
                "state_timestamp": time.time(),
                "has_document_list": False,
                "last_search_results_count": 0
            }
        
        state_info = self.conversation_states[phone_number]
        current_time = time.time()
        
        # Verificar si debe resetear por timeout (1 hora = 3600 segundos)
        if current_time - state_info["state_timestamp"] >= 3600:
            self._reset_conversation_state(phone_number)
            return
        
        # Actualizar estado según message_type
        if message_type == "consulta":
            # Se hizo una consulta inicial
            state_info["state"] = "initial"
            state_info["state_timestamp"] = current_time
            
        elif message_type == "eleccion":
            # Se devolvió una lista de documentos para elegir
            state_info["state"] = "awaiting_choice"
            state_info["has_document_list"] = True
            state_info["state_timestamp"] = current_time
            if parameters:
                state_info["last_search_results_count"] = parameters.get("results_count", 0)
            
        elif message_type == "verificacion":
            # Se devolvió un documento específico para verificar
            state_info["state"] = "awaiting_verification"
            state_info["state_timestamp"] = current_time
            
        # Actualizar timestamp en cualquier caso
        state_info["state_timestamp"] = current_time

    def _reset_conversation_state(self, phone_number: str):
        """Resetea el estado de conversación y limpia documentos"""
        print(f"🔄 Reseteando estado de conversación para {phone_number}")
        
        # Resetear estado
        self.conversation_states[phone_number] = {
            "state": "initial",
            "state_timestamp": time.time(),
            "has_document_list": False,
            "last_search_results_count": 0
        }
        
        # Limpiar cache de documentos
        if phone_number in self.document_cache:
            del self.document_cache[phone_number]

    def should_search_full_database(self, phone_number: str, user_message: str = None) -> bool:
        """
        Determina si debe buscar en toda la base de datos o en la lista filtrada
        
        Returns:
            True: Buscar en base de datos completa
            False: Buscar en lista filtrada actual
        """
        # Verificar si el usuario escribió "hola" (reset manual)
        if user_message and user_message.lower().strip() in ["hola", "hello", "hi"]:
            self._reset_conversation_state(phone_number)
            return True
        
        # Si no existe estado, buscar en base completa
        if phone_number not in self.conversation_states:
            return True
            
        state_info = self.conversation_states[phone_number]
        current_time = time.time()
        
        # Verificar timeout de 1 hora
        if current_time - state_info["state_timestamp"] >= 3600:
            self._reset_conversation_state(phone_number)
            return True
        
        # Si está en estado inicial o no tiene lista de documentos, buscar en base completa
        if state_info["state"] == "initial" or not state_info["has_document_list"]:
            return True
            
        # Si está esperando elección o verificación, o en búsqueda filtrada, usar lista
        if state_info["state"] in ["awaiting_choice", "awaiting_verification", "filtered_search"]:
            return False
            
        return True

    def set_filtered_search_mode(self, phone_number: str):
        """Activa el modo de búsqueda filtrada después de una confirmación positiva"""
        if phone_number not in self.conversation_states:
            self.conversation_states[phone_number] = {
                "state": "filtered_search",
                "state_timestamp": time.time(),
                "has_document_list": True,
                "last_search_results_count": 0
            }
        else:
            self.conversation_states[phone_number]["state"] = "filtered_search"
            self.conversation_states[phone_number]["state_timestamp"] = time.time()
        
        print(f"🔍 Modo búsqueda filtrada activado para {phone_number}")

    def set_awaiting_choice_search_mode(self, phone_number: str):
        """Activa el modo de búsqueda filtrada después de una confirmación positiva"""
        if phone_number not in self.conversation_states:
            self.conversation_states[phone_number] = {
                "state": "awaiting_choice",
                "state_timestamp": time.time(),
                "has_document_list": True,
                "last_search_results_count": 0
            }
        else:
            self.conversation_states[phone_number]["state"] = "awaiting_choice"
            self.conversation_states[phone_number]["state_timestamp"] = time.time()
        
        print(f"🔍 Modo búsqueda filtrada activado para {phone_number}")

    def get_conversation_state(self, phone_number: str) -> Dict[str, Any]:
        """Obtiene el estado actual de la conversación"""
        if phone_number not in self.conversation_states:
            return {
                "state": "initial",
                "has_document_list": False,
                "should_search_full_db": True,
                "last_search_results_count": 0,
                "time_since_last_activity": 0
            }
        
        state_info = self.conversation_states[phone_number]
        current_time = time.time()
        time_since_activity = current_time - state_info["state_timestamp"]
        
        return {
            "state": state_info["state"],
            "has_document_list": state_info["has_document_list"],
            "should_search_full_db": self.should_search_full_database(phone_number),
            "last_search_results_count": state_info["last_search_results_count"],
            "time_since_last_activity": time_since_activity,
            "will_timeout_soon": time_since_activity > 3300  # Aviso a los 55 minutos
        }

    def get_conversation_history(self, phone_number: str, last_n_turns: int = 5) -> List[ConversationTurn]:
        """Obtiene el historial de conversación reciente"""
        if phone_number not in self.conversations:
            return []
            
        self._cleanup_old_turns(phone_number)
        history = self.conversations[phone_number]
        return history[-last_n_turns:] if history else []
    
    def get_conversation_context(self, phone_number: str) -> Dict[str, Any]:
        """Extrae contexto relevante de la conversación"""
        try:
            history = self.get_conversation_history(phone_number, 5)
            # Obtener estado de conversación
            conversation_state = self.get_conversation_state(phone_number)
            
            context = {
                "last_intent": None,
                "last_parameters": {},
                "recent_documents": [],
                "recent_projects": [],
                "recent_users": [],
                "recent_searches": [],
                "conversation_flow": [],
                "is_follow_up": len(history) > 0,
                "session_length": len(history),
                "last_successful_search": None,
                "nivel_acceso": None,
                # Estados de conversación integrados
                "conversation_state": conversation_state["state"],
                "has_document_list": conversation_state["has_document_list"],
                "should_search_full_db": conversation_state["should_search_full_db"],
                "awaiting_confirmation": conversation_state["state"] in ["awaiting_choice", "awaiting_verification"],
                "confirmation_type": "choice" if conversation_state["state"] == "awaiting_choice" else "verification" if conversation_state["state"] == "awaiting_verification" else None,
                "pending_results": []
            }

            if not history:
                return context

            # Último intent y parámetros
            last_turn = history[-1]
            context["last_intent"] = last_turn.intent
            context["last_parameters"] = last_turn.parameters

            # Analizar turnos recientes para extraer contexto
            for i, turn in enumerate(history):
                context["conversation_flow"].append({
                    "intent": turn.intent,
                    "timestamp": turn.timestamp,
                    "position": i,
                    "message_type": turn.message_type
                })

                params = turn.parameters or {}

                # Documentos mencionados
                if params.get("document_id"):
                    context["recent_documents"].append(params["document_id"])
                if params.get("parametro") and turn.intent.startswith("seguimiento_por"):
                    context["recent_documents"].append(params["parametro"])

                # Proyectos, usuarios, búsquedas...
                if params.get("proyecto"):
                    context["recent_projects"].append(params["proyecto"])
                if params.get("usuario"):
                    context["recent_users"].append(params["usuario"])
                if params.get("consulta") or turn.intent == "buscar_documentos":
                    search_term = params.get("consulta") or params.get("parametro")
                    if search_term:
                        context["recent_searches"].append(search_term)

                # Obtener nivel de acceso de turnos del sistema
                if turn.intent == "system_set_role":
                    context["nivel_acceso"] = params.get("nivel_acceso")

            # Eliminar duplicados
            context["recent_documents"] = list(dict.fromkeys(context["recent_documents"]))[:5]
            context["recent_projects"] = list(dict.fromkeys(context["recent_projects"]))[:3]
            context["recent_users"] = list(dict.fromkeys(context["recent_users"]))[:3]
            context["recent_searches"] = list(dict.fromkeys(context["recent_searches"]))[:3]

            return context

        except Exception as e:
            print(f"❌ ERROR en get_conversation_context: {e}")
            return {
                "last_intent": None,
                "last_parameters": {},
                "recent_documents": [],
                "recent_projects": [],
                "recent_users": [],
                "recent_searches": [],
                "conversation_flow": [],
                "is_follow_up": False,
                "session_length": 0,
                "conversation_state": "initial",
                "has_document_list": False,
                "should_search_full_db": True,
                "awaiting_confirmation": False,
                "confirmation_type": None,
                "pending_results": [],
                "error": str(e)
            }
    
    def set_user_role(self, phone_number: str, nivel_acceso: str):
        """Establece el rol del usuario"""
        if phone_number not in self.conversations:
            self.conversations[phone_number] = []
        
        self.add_turn(
            phone_number,
            user_message="[system] set_role",
            bot_response=f"Rol asignado: {nivel_acceso}",
            intent="system_set_role",
            parameters={"nivel_acceso": nivel_acceso},
            context={"nivel_acceso": nivel_acceso}
        )

    def _cleanup_old_turns(self, phone_number: str):
        """Limpia turnos antiguos basado en timeout de sesión"""
        if phone_number not in self.conversations:
            return
            
        current_time = time.time()
        old_count = len(self.conversations[phone_number])
        
        self.conversations[phone_number] = [
            turn for turn in self.conversations[phone_number]
            if current_time - turn.timestamp < self.session_timeout
        ]
        
        new_count = len(self.conversations[phone_number])
        if old_count != new_count:
            print(f"🧹 Limpieza: {old_count - new_count} turnos antiguos eliminados")
        
        if not self.conversations[phone_number]:
            del self.conversations[phone_number]
            # También limpiar estado si no hay conversación
            if phone_number in self.conversation_states:
                del self.conversation_states[phone_number]
    
    def clear_conversation(self, phone_number: str):
        """Limpia toda la conversación de un usuario"""
        if phone_number in self.conversations:
            del self.conversations[phone_number]
        if phone_number in self.conversation_states:
            del self.conversation_states[phone_number]
        if phone_number in self.document_cache:
            del self.document_cache[phone_number]
        print(f"🗑️ Conversación y estados eliminados para {phone_number}")

    def set_conversation_documents(self, phone_number: str, documents: List[Dict], 
                                 source_intent: str = None, source_query: str = None):
        """Almacena documentos encontrados en la conversación actual"""
        try:
            if not documents or not isinstance(documents, list):
                print("⚠️ No hay documentos válidos para almacenar")
                return False
                
            # Inicializar cache si no existe
            if phone_number not in self.document_cache:
                self.document_cache[phone_number] = []
                
            # Agregar metadatos a cada documento
            enriched_documents = []
            for doc in documents:
                if isinstance(doc, dict):
                    enriched_doc = doc.copy()
                    enriched_doc.update({
                        "cache_timestamp": time.time(),
                        "source_intent": source_intent,
                        "source_query": source_query,
                        "cache_id": f"{phone_number}_{int(time.time())}_{len(enriched_documents)}"
                    })
                    enriched_documents.append(enriched_doc)
            
            # Agregar documentos al cache (al inicio para mantener los más recientes)
            self.document_cache[phone_number] = enriched_documents + self.document_cache[phone_number]
            
            # Limitar tamaño del cache
            if len(self.document_cache[phone_number]) > self.max_documents_cache:
                self.document_cache[phone_number] = self.document_cache[phone_number][:self.max_documents_cache]
            
            print(f"📚 Documentos almacenados: {len(enriched_documents)} documentos para {phone_number}")
            print(f"📊 Total en cache: {len(self.document_cache[phone_number])} documentos")
            
            return True
            
        except Exception as e:
            print(f"❌ Error almacenando documentos: {e}")
            return False
        
    def get_conversation_documents(self, phone_number: str, limit: int = None, 
                                 filter_by: Dict[str, Any] = None) -> List[Dict]:
        """Obtiene documentos almacenados en la conversación"""
        try:
            if phone_number not in self.document_cache:
                return []
                
            documents = self.document_cache[phone_number].copy()
            
            # Aplicar filtros si se especifican
            if filter_by:
                filtered_docs = []
                for doc in documents:
                    match = True
                    for key, value in filter_by.items():
                        if key not in doc or doc[key] != value:
                            match = False
                            break
                    if match:
                        filtered_docs.append(doc)
                documents = filtered_docs
            
            # Aplicar límite
            if limit and limit > 0:
                documents = documents[:limit]
                
            print(f"📖 Recuperados {len(documents)} documentos para {phone_number}")
            return documents
            
        except Exception as e:
            print(f"❌ Error obteniendo documentos: {e}")
            return []
