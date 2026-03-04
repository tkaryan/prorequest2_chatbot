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
    flow: str = None
    


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
                 message_type: str = None, flow: str = None):
        """Añade un turno con información de confirmación y flow"""
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
                flow=flow  # 🆕 NUEVO
            )
            
            self.conversations[phone_number].append(turn)
            self._cleanup_old_turns(phone_number)
            
            if len(self.conversations[phone_number]) > self.max_turns:
                self.conversations[phone_number] = self.conversations[phone_number][-self.max_turns:]
            
            # Actualizar estado según message_type, flow y resultados
            self._update_conversation_state(phone_number, message_type, parameters, flow)
            
        except Exception as e:
            print(f"❌ Error guardando en memoria: {type(e).__name__} - {e}")

    def _update_conversation_state(self, phone_number: str, message_type: str, 
                                 parameters: Dict = None, flow: str = None):
        """Actualiza el estado de la conversación basado en el flujo mejorado"""
        if phone_number not in self.conversation_states:
            self.conversation_states[phone_number] = {
                "state": "initial",  # initial, awaiting_choice, awaiting_verification, filtered_search
                "state_timestamp": time.time(),
                "has_document_list": False,
                "last_search_results_count": 0,
                "current_flow": None,  #  Rastrea el flow actual
                "flow_history": []     # Historial de flows recientes
            }
        
        state_info = self.conversation_states[phone_number]
        current_time = time.time()
        
        # Verificar si debe resetear por timeout (1 hora = 3600 segundos)
        if current_time - state_info["state_timestamp"] >= 3600:
            self._reset_conversation_state(phone_number)
            return
        
        # ACTUALIZAR FLOW ACTUAL Y HISTORIAL
        if flow:
            state_info["current_flow"] = flow
            
            # Añadir al historial de flows
            flow_history = state_info.get("flow_history", [])
            flow_history.append({
                "flow": flow,
                "timestamp": current_time,
                "message_type": message_type
            })
            
            # Mantener solo los últimos 5 flows
            if len(flow_history) > 5:
                flow_history = flow_history[-5:]
            
            state_info["flow_history"] = flow_history
            
            print(f"🔄 Flow actualizado a: {flow} para {phone_number}")
        
        # Actualizar estado según message_type y flow
        if message_type == "consulta":
            state_info["state"] = "initial"
            state_info["state_timestamp"] = current_time
            
        elif message_type == "eleccion" or flow == "lista":
            # Se devolvió una lista de documentos para elegir
            state_info["state"] = "awaiting_choice"
            state_info["has_document_list"] = True
            state_info["state_timestamp"] = current_time
            state_info["current_flow"] = "lista"
            if parameters:
                state_info["last_search_results_count"] = parameters.get("results_count", 0)
            print(f"🔄 Estado: awaiting_choice (lista) para {phone_number}")
            
        elif message_type == "verificacion" or flow == "detalle":
            # Se devolvió un documento específico para verificar
            state_info["state"] = "awaiting_verification"
            state_info["state_timestamp"] = current_time
            
            print(f"🔄 Estado: awaiting_verification (detalle) para {phone_number}")
        
        elif flow == "confirmacion":
            # Usuario está respondiendo una confirmación
            state_info["current_flow"] = "confirmacion"
            # El estado específico depende de lo que esté confirmando
            
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
            "last_search_results_count": 0,
            "current_flow": None,
            "flow_history": []
        }
        
        # Limpiar cache de documentos
        if phone_number in self.document_cache:
            del self.document_cache[phone_number]

    def should_search_full_database(self, phone_number: str, user_message: str = None) -> bool:
        """
        Determina si debe buscar en toda la base de datos o en la lista filtrada
        Ahora considera el flow actual
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
        
        # 🆕 LÓGICA MEJORADA CON FLOW
        current_flow = state_info.get("current_flow")
        
        # Si está en flow de lista, usar documentos guardados
        if current_flow == "lista" and state_info.get("has_document_list", False):
            return False
            
        # Si está en flow de detalle después de una lista, mantener filtrado
        if current_flow == "detalle" and self.was_last_flow(phone_number, "lista"):
            return False
        
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
                "last_search_results_count": 0,
                "current_flow": "filtered_search",
                "flow_history": []
            }
        else:
            self.conversation_states[phone_number]["state"] = "filtered_search"
            self.conversation_states[phone_number]["current_flow"] = "filtered_search"
            self.conversation_states[phone_number]["state_timestamp"] = time.time()
        

    def set_awaiting_choice_search_mode(self, phone_number: str):
        """Activa el modo de elección después de verificación"""
        if phone_number not in self.conversation_states:
            self.conversation_states[phone_number] = {
                "state": "awaiting_choice",
                "state_timestamp": time.time(),
                "has_document_list": True,
                "last_search_results_count": 0,
                "current_flow": "lista",
                "flow_history": []
            }
        else:
            self.conversation_states[phone_number]["state"] = "awaiting_choice"
            self.conversation_states[phone_number]["current_flow"] = "lista"
            self.conversation_states[phone_number]["state_timestamp"] = time.time()
        
        print(f"🔍 Modo awaiting_choice activado para {phone_number}")



    def get_current_flow(self, phone_number: str) -> str:
        """Obtiene el flow actual de la conversación"""
        if phone_number not in self.conversation_states:
            return None
        return self.conversation_states[phone_number].get("current_flow")
    
    def get_flow_history(self, phone_number: str, limit: int = 3) -> List[Dict]:
        """Obtiene el historial reciente de flows"""
        if phone_number not in self.conversation_states:
            return []
        
        flow_history = self.conversation_states[phone_number].get("flow_history", [])
        return flow_history[-limit:] if flow_history else []
    
    def is_in_flow(self, phone_number: str, flow_type: str) -> bool:
        """Verifica si está en un flow específico"""
        current_flow = self.get_current_flow(phone_number)
        return current_flow == flow_type
    
    def was_last_flow(self, phone_number: str, flow_type: str) -> bool:
        """Verifica si el último flow fue de un tipo específico"""
        flow_history = self.get_flow_history(phone_number, 1)
        if not flow_history:
            return False
        return flow_history[-1]["flow"] == flow_type

    def get_conversation_state(self, phone_number: str) -> Dict[str, Any]:
        """Obtiene el estado actual de la conversación con información de flow"""
        if phone_number not in self.conversation_states:
            return {
                "state": "initial",
                "has_document_list": False,
                "should_search_full_db": True,
                "last_search_results_count": 0,
                "time_since_last_activity": 0,
                "current_flow": None,
                "flow_history": []
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
            "will_timeout_soon": time_since_activity > 3300,  # Aviso a los 55 minutos
            "current_flow": state_info.get("current_flow"),    
            "flow_history": state_info.get("flow_history", [])  
        }

    def get_conversation_history(self, phone_number: str, last_n_turns: int = 5) -> List[ConversationTurn]:
        """Obtiene el historial de conversación reciente"""
        if phone_number not in self.conversations:
            return []
            
        self._cleanup_old_turns(phone_number)
        history = self.conversations[phone_number]
        return history[-last_n_turns:] if history else []
    
    def get_conversation_context(self, phone_number: str) -> Dict[str, Any]:
        """Extrae contexto relevante de la conversación con información de flow"""
        try:
            history = self.get_conversation_history(phone_number, 5)
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
                "pending_results": [],
                #Información de flow
                "current_flow": conversation_state["current_flow"],
                "flow_history": conversation_state["flow_history"],
                "is_in_lista_flow": conversation_state["current_flow"] == "lista",
                "is_in_detalle_flow": conversation_state["current_flow"] == "detalle",
                "last_flow_was_lista": self.was_last_flow(phone_number, "lista"),
                "last_flow_was_detalle": self.was_last_flow(phone_number, "detalle")
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
                    "message_type": turn.message_type,
                    "flow": turn.flow  # 🆕 NUEVO
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
                "current_flow": None,
                "flow_history": [],
                "is_in_lista_flow": False,
                "is_in_detalle_flow": False,
                "last_flow_was_lista": False,
                "last_flow_was_detalle": False,
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

    # Agregar método a ConversationMemory para manejar estados de notificaciones
    def set_conversation_state(self, phone_number: str, state: str, additional_info: dict = None):
        """Establece el estado de conversación"""
        if phone_number not in self.conversation_states:
            self.conversation_states[phone_number] = {
                "state": "initial",
                "state_timestamp": time.time(),
                "has_document_list": False,
                "last_search_results_count": 0,
                "current_flow": None,
                "flow_history": []
            }
        
        self.conversation_states[phone_number]["state"] = state
        self.conversation_states[phone_number]["state_timestamp"] = time.time()
        
        if additional_info:
            self.conversation_states[phone_number].update(additional_info)
        
        print(f"🔄 Estado cambiado a: {state} para {phone_number}")

    
