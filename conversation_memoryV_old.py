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
    awaiting_confirmation: bool = False
    confirmation_type: str = None  # "detalle", "lista", None
    search_results: List[Dict] = None  # Resultados pendientes
    
    def to_dict(self):
        """Convierte a diccionario para debugging"""
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S"),
            "user_message": self.user_message[:50] + "..." if len(self.user_message) > 50 else self.user_message,
            "intent": self.intent,
            "parameters": self.parameters,
            "awaiting_confirmation": self.awaiting_confirmation,
            "confirmation_type": self.confirmation_type
        }

class ConversationMemory:
    """Maneja la memoria conversacional con flujo de confirmación"""
    
    def __init__(self, max_turns=10, session_timeout_minutes=30):
        self.conversations: Dict[str, List[ConversationTurn]] = {}
        self.max_turns = max_turns
        self.session_timeout = session_timeout_minutes * 60
        self.document_cache: Dict[str, List[Dict]] = {}
        self.max_documents_cache = 50  # Máximo documentos en cache por usuario
        self.fases: Dict[str, str] = {}  # ahora es por usuario
        
        
    def add_turn(self, phone_number: str, user_message: str, bot_response: str, 
                 intent: str, parameters: Dict = None, context: Dict = None,
                 awaiting_confirmation: bool = False, confirmation_type: str = None,
                 search_results: List[Dict] = None):
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
                awaiting_confirmation=awaiting_confirmation,
                confirmation_type=confirmation_type,
                search_results=search_results or []
            )
            
            self.conversations[phone_number].append(turn)
            self._cleanup_old_turns(phone_number)
            
            if len(self.conversations[phone_number]) > self.max_turns:
                self.conversations[phone_number] = self.conversations[phone_number][-self.max_turns:]
            
            print(f"🧠 Memoria actualizada - Esperando confirmación: {awaiting_confirmation}")
            
        except Exception as e:
            print(f"❌ Error guardando en memoria: {type(e).__name__} - {e}")
    
    def is_awaiting_confirmation(self, phone_number: str) -> Dict[str, Any]:
        """Verifica si está esperando confirmación del usuario"""
        if phone_number not in self.conversations:
            return {"awaiting": False}
            
        history = self.get_conversation_history(phone_number, 1)
        if not history:
            return {"awaiting": False}
            
        last_turn = history[-1]
        if last_turn.awaiting_confirmation:
            return {
                "awaiting": True,
                "type": last_turn.confirmation_type,
                "search_results": last_turn.search_results,
                "last_intent": last_turn.intent,
                "last_parameters": last_turn.parameters
            }
            
        return {"awaiting": False}
    
    def clear_confirmation_state(self, phone_number: str):
        """Limpia el estado de confirmación"""
        if phone_number in self.conversations and self.conversations[phone_number]:
            last_turn = self.conversations[phone_number][-1]
            last_turn.awaiting_confirmation = False
            last_turn.confirmation_type = None
            last_turn.search_results = None
            print(f"🧠 Estado de confirmación limpiado para {phone_number}")
    
    def get_conversation_history(self, phone_number: str, last_n_turns: int = 5) -> List[ConversationTurn]:
        """Obtiene el historial de conversación reciente"""
        if phone_number not in self.conversations:
            return []
            
        self._cleanup_old_turns(phone_number)
        history = self.conversations[phone_number]
        return history[-last_n_turns:] if history else []
        
    @staticmethod
    def dedup_list(lista, limit=None):
        """Elimina duplicados de una lista que puede contener dicts, str, int..."""
        seen = []
        result = []
        for item in lista:
            if isinstance(item, dict):
                # lo convertimos en JSON ordenado para comparar
                marker = json.dumps(item, sort_keys=True)
            else:
                marker = item

            if marker not in seen:
                seen.append(marker)
                result.append(item)

        return result[:limit] if limit else result


    def get_conversation_context(self, phone_number: str) -> Dict[str, Any]:
        """Extrae contexto relevante de la conversación"""
        try:
            history = self.get_conversation_history(phone_number, 5)
            
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
                # NUEVO: Estado de confirmación
                "awaiting_confirmation": False,
                "confirmation_type": None,
                "pending_results": [],
                "search_results": None
            }

            if not history:
                return context

            # Último intent y parámetros
            last_turn = history[-1]
            context["last_intent"] = last_turn.intent
            context["last_parameters"] = last_turn.parameters
            
            # NUEVO: Verificar estado de confirmación
            context["awaiting_confirmation"] = last_turn.awaiting_confirmation
            context["confirmation_type"] = last_turn.confirmation_type
            
            context["pending_results"] = last_turn.search_results

            # Analizar turnos recientes para extraer contexto
            for i, turn in enumerate(history):
                context["conversation_flow"].append({
                    "intent": turn.intent,
                    "timestamp": turn.timestamp,
                    "position": i
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
            context["recent_documents"] = self.dedup_list(context["recent_documents"], 5)
            context["recent_projects"] = self.dedup_list(context["recent_projects"], 3)
            context["recent_users"] = self.dedup_list(context["recent_users"], 3)
            context["recent_searches"] = self.dedup_list(context["recent_searches"], 3)


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

    def set_conversation_documents(self, phone_number: str, documents: List[Dict], 
                                 source_intent: str = None, source_query: str = None):
        """
        Almacena documentos encontrados en la conversación actual
        
        Args:
            phone_number: Número de teléfono del usuario
            documents: Lista de documentos encontrados
            source_intent: Intent que generó estos documentos
            source_query: Query original que generó estos documentos
        """
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
            
            # Actualizar contexto conversacional con info de documentos
            self._update_context_with_documents(phone_number, enriched_documents, source_intent, source_query)
            
            return True
            
        except Exception as e:
            print(f"❌ Error almacenando documentos: {e}")
            return False
        
        
    def get_conversation_documents(self, phone_number: str, limit: int = None, 
                                 filter_by: Dict[str, Any] = None) -> List[Dict]:
        """
        Obtiene documentos almacenados en la conversación
        
        Args:
            phone_number: Número de teléfono del usuario
            limit: Límite de documentos a retornar
            filter_by: Filtros para aplicar (ej: {"source_intent": "seguimiento_por_proyecto"})
        """
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
    
    def search_in_conversation_documents(self, phone_number: str, query: str, 
                                       search_fields: List[str] = None) -> List[Dict]:
        """
        Realiza búsqueda dentro de los documentos almacenados en la conversación
        
        Args:
            phone_number: Número de teléfono del usuario
            query: Término de búsqueda
            search_fields: Campos donde buscar (por defecto: todos los campos de texto)
        """
        try:
            if not query or not query.strip():
                return []
                
            documents = self.get_conversation_documents(phone_number)
            if not documents:
                print("📚 No hay documentos en cache para buscar")
                return []
                
            query_lower = query.lower().strip()
            search_results = []
            
            # Campos por defecto donde buscar
            if not search_fields:
                search_fields = [
                    "numero_documento", "asunto", "proyecto", "codigo_sistema",
                    "tipo", "usuario_asignado", "estado", "descripcion"
                ]
            
            print(f"🔍 Buscando '{query}' en {len(documents)} documentos almacenados")
            
            for doc in documents:
                match_score = 0
                match_details = []
                
                # Buscar en cada campo especificado
                for field in search_fields:
                    if field in doc and doc[field]:
                        field_value = str(doc[field]).lower()
                        
                        # Búsqueda exacta (mayor score)
                        if query_lower in field_value:
                            match_score += 10
                            match_details.append(f"{field}:{doc[field][:50]}")
                        
                        # Búsqueda por palabras individuales
                        query_words = query_lower.split()
                        for word in query_words:
                            if len(word) > 2 and word in field_value:
                                match_score += 2
                
                # Si hay coincidencias, agregar al resultado
                if match_score > 0:
                    result_doc = doc.copy()
                    result_doc["_match_score"] = match_score
                    result_doc["_match_details"] = match_details
                    search_results.append(result_doc)
            
            # Ordenar por score de coincidencia (mayor score primero)
            search_results.sort(key=lambda x: x["_match_score"], reverse=True)
            
            print(f"✅ Encontrados {len(search_results)} documentos con coincidencias")
            
            return search_results
            
        except Exception as e:
            print(f"❌ Error en búsqueda de documentos: {e}")
            return []
    
    def clear_conversation_documents(self, phone_number: str, older_than_hours: int = None):
        """
        Limpia documentos almacenados en la conversación
        
        Args:
            phone_number: Número de teléfono del usuario
            older_than_hours: Solo limpiar documentos más antiguos que X horas (opcional)
        """
        try:
            if phone_number not in self.document_cache:
                return
                
            if older_than_hours:
                # Limpiar solo documentos antiguos
                current_time = time.time()
                cutoff_time = current_time - (older_than_hours * 3600)
                
                old_count = len(self.document_cache[phone_number])
                self.document_cache[phone_number] = [
                    doc for doc in self.document_cache[phone_number]
                    if doc.get("cache_timestamp", 0) > cutoff_time
                ]
                new_count = len(self.document_cache[phone_number])
                print(f"🧹 Limpiados {old_count - new_count} documentos antiguos para {phone_number}")
            else:
                # Limpiar todos los documentos
                doc_count = len(self.document_cache[phone_number])
                del self.document_cache[phone_number]
                print(f"🗑️ Eliminados {doc_count} documentos para {phone_number}")
                
        except Exception as e:
            print(f"❌ Error limpiando documentos: {e}")
    
    def get_document_cache_stats(self, phone_number: str = None) -> Dict[str, Any]:
        """Obtiene estadísticas del cache de documentos"""
        try:
            if phone_number:
                # Stats para un usuario específico
                if phone_number not in self.document_cache:
                    return {"total_documents": 0, "cache_size_mb": 0}
                
                docs = self.document_cache[phone_number]
                return {
                    "total_documents": len(docs),
                    "recent_documents": len([d for d in docs if time.time() - d.get("cache_timestamp", 0) < 3600]),
                    "oldest_document": min([d.get("cache_timestamp", time.time()) for d in docs]) if docs else None,
                    "newest_document": max([d.get("cache_timestamp", time.time()) for d in docs]) if docs else None,
                    "source_intents": list(set([d.get("source_intent") for d in docs if d.get("source_intent")])),
                }
            else:
                # Stats globales
                total_users = len(self.document_cache)
                total_docs = sum(len(docs) for docs in self.document_cache.values())
                
                return {
                    "total_users_with_cache": total_users,
                    "total_cached_documents": total_docs,
                    "average_docs_per_user": total_docs / total_users if total_users > 0 else 0,
                    "cache_users": list(self.document_cache.keys())
                }
                
        except Exception as e:
            print(f"❌ Error obteniendo stats: {e}")
            return {}
    
    def _update_context_with_documents(self, phone_number: str, documents: List[Dict], 
                                     source_intent: str, source_query: str):
        """Actualiza el contexto conversacional con información de documentos"""
        try:
            # Extraer información relevante de los documentos
            projects = set()
            users = set()
            doc_codes = set()
            
            for doc in documents:
                if doc.get("proyecto"):
                    projects.add(doc["proyecto"])
                if doc.get("usuario_asignado"):
                    users.add(doc["usuario_asignado"])
                if doc.get("codigo_sistema"):
                    doc_codes.add(doc["codigo_sistema"])
                elif doc.get("numero_documento"):
                    doc_codes.add(doc["numero_documento"])
            
            # Agregar turn especial para contexto de documentos
            self.add_turn(
                phone_number=phone_number,
                user_message=f"[system] documents_cached: {len(documents)} docs",
                bot_response=f"Cached {len(documents)} documents from {source_intent}",
                intent="system_cache_documents",
                parameters={
                    "cached_document_count": len(documents),
                    "source_intent": source_intent,
                    "source_query": source_query,
                    "cached_projects": list(projects)[:5],
                    "cached_users": list(users)[:5],
                    "cached_doc_codes": list(doc_codes)[:10]
                },
                context={
                    "has_cached_documents": True,
                    "cached_document_count": len(documents),
                    "can_search_in_cache": True
                }
            )
            
        except Exception as e:
            print(f"❌ Error actualizando contexto con documentos: {e}")

    
    def set_fase(self, phone_number: str, fase: str):
        """Establece la fase actual de la conversación"""
        self.fases[phone_number] = fase
        print(f"🔄 Fase actualizada para {phone_number}: {fase}")

    def get_fase(self, phone_number: str) -> str:
        """Obtiene la fase actual de la conversación"""
        return self.fases.get(phone_number, "consulta")  # default: consulta

    def clear_fase(self, phone_number: str):
        """Elimina la fase de un usuario"""
        if phone_number in self.fases:
            del self.fases[phone_number]
            print(f"🗑️ Fase eliminada para {phone_number}")

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
    
    def clear_conversation(self, phone_number: str):
        """Limpia toda la conversación de un usuario"""
        if phone_number in self.conversations:
            del self.conversations[phone_number]
            print(f"🗑️ Conversación eliminada para {phone_number}")

# Instancia global de memoria
conversation_memory = ConversationMemory()

def detectar_intencion_con_contexto(texto_usuario: str, phone_number: str) -> Dict[str, Any]:
    """
    Versión mejorada de detectar_intencion que considera el contexto conversacional
    """
    # Obtener contexto de la conversación
    context = conversation_memory.get_conversation_context(phone_number)
    documentos = conversation_memory.get_conversation_documents(phone_number)
    fase = conversation_memory.get_fase(phone_number)
    # Debug logging
    print(f"🔍 Analizando mensaje con contexto:")
    print(f"   Usuario: {texto_usuario[:50]}...")
    print(f"   Contexto: {context['session_length']} turnos, último intent: {context.get('last_intent', 'None')}")
    
    # Detección básica de follow-ups
    texto_lower = texto_usuario.lower().strip()
    
    # MEJORA: Follow-ups más específicos
    if context["is_follow_up"]:
        # Referencias directas a elementos del contexto
        if any(word in texto_lower for word in [
            "y", "también", "además", "otro", "otra", "más", "siguiente", 
            "ahora", "luego", "después", "ese", "esa", "esto", "eso",
            "el anterior", "la anterior", "este", "esta"
        ]):
            result = manejar_follow_up_mejorado(texto_usuario, context)
            if result:
                print(f"✅ Follow-up detectado: {result['intent']}")
                return result
        
        # Preguntas de ampliación
        if any(phrase in texto_lower for phrase in [
            "más información", "más detalles", "amplía", "explica más",
            "qué más", "algo más", "otros datos"
        ]):
            result = manejar_ampliacion_info(texto_usuario, context)
            if result:
                print(f"✅ Ampliación detectada: {result['intent']}")
                return result
    
    # Usar Gemini con contexto si está disponible
    intent_data = None
    try:
        from chatbot_system import detectar_intencion_con_contexto, seleccionar_respuesta
#        if documentos and fase != 'verificacion':
        if documentos and fase != 'verificacion':
            print("SELECCION DE RESPUESTA ----------------------------------------")
            print("CONTEXTO SERIO:", context)
            result = seleccionar_respuesta(texto_usuario, context, documentos)
            return {"estado": "seleccion", "resultado": result}
        else:
            print("DETECTAR INTENCION CONTEXTO --------------------------------------------")
            intent_data = detectar_intencion_con_contexto(texto_usuario, context)
            if intent_data:
                # Convertir formato
                result = convertir_formato_gemini(intent_data)
                print(f"✅ Gemini con contexto: {result['intent']}")
                return result
    except Exception as e:
        print(f"⚠️ Error con Gemini contextual: {e}")
    
    # Fallback: detección normal
    from chatbot_system import detectar_intencion_optimizado
    result = detectar_intencion_optimizado(texto_usuario)
    print(f"✅ Detección normal: {result.get('intent', 'unknown')}")
    
    return result

def convertir_formato_gemini(gemini_result):
    """Convierte el formato de Gemini al formato esperado"""
    intent = gemini_result.get("intent")
    parameters = gemini_result.get("parameters", {})
    
    # Determinar el parámetro principal
    parametro = None
    if intent in ["seguimiento_por_codigo", "seguimiento_por_numero_documento", "seguimiento_por_consecutivo"]:
        parametro = parameters.get("document_id")
    elif intent == "seguimiento_por_usuario":
        parametro = parameters.get("usuario")
    elif intent == "seguimiento_por_proyecto":
        parametro = parameters.get("proyecto")
    elif intent in ["buscar_documentos", "seguimiento_por_asunto", "conversacion_general"]:
        parametro = parameters.get("consulta")
    
    result = {"intent": intent}
    if parametro:
        result["parametro"] = parametro
    
    # Mantener flags de contexto
    if parameters.get("is_follow_up"):
        result["is_follow_up"] = True
    if parameters.get("context_reference"):
        result["is_contextual_reference"] = True
    
    return result

def manejar_follow_up_mejorado(texto_usuario: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Maneja follow-ups basados en el contexto - VERSIÓN MEJORADA"""
    last_intent = context.get("last_intent")
    last_params = context.get("last_parameters", {})
    texto_lower = texto_usuario.lower()
    
    print(f"🔄 Procesando follow-up: '{texto_usuario}' | Último intent: {last_intent}")
    
    # Referencias específicas a documentos previos
    if any(word in texto_lower for word in ["este", "ese", "el documento", "ese documento"]):
        if context["recent_documents"]:
            return {
                "intent": "seguimiento_por_numero_documento",
                "parametro": context["recent_documents"][0],  # El más reciente
                "is_follow_up": True,
                "follow_up_type": "document_reference"
            }
    
    # Referencias a proyectos previos
    if any(word in texto_lower for word in ["este proyecto", "ese proyecto", "el proyecto"]):
        if context["recent_projects"]:
            return {
                "intent": "seguimiento_por_proyecto",
                "parametro": context["recent_projects"][0],
                "is_follow_up": True,
                "follow_up_type": "project_reference"
            }
    
    # Conectores simples que mantienen contexto
    if texto_lower.strip() in ["y", "también", "además", "otro", "otra", "más"]:
        if last_intent and last_params.get("parametro"):
            return {
                "intent": last_intent,
                "parametro": last_params.get("parametro"),
                "is_follow_up": True,
                "follow_up_type": "continuation"
            }
    
    # Búsquedas relacionadas
    if any(word in texto_lower for word in ["relacionado", "similar", "parecido"]):
        if context["recent_documents"]:
            return {
                "intent": "buscar_documentos", 
                "parametro": f"relacionado con {context['recent_documents'][0]}",
                "is_follow_up": True,
                "follow_up_type": "related_search"
            }
    
    # Ampliación de información
    if "más información" in texto_lower or "detalles" in texto_lower:
        return manejar_ampliacion_info(texto_usuario, context)
    
    return None

def manejar_ampliacion_info(texto_usuario: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Maneja solicitudes de más información"""
    last_intent = context.get("last_intent")
    last_params = context.get("last_parameters", {})
    
    # Si la última búsqueda fue exitosa, ampliarla
    if context.get("last_successful_search"):
        search_info = context["last_successful_search"]
        
        if search_info["intent"] in ["seguimiento_por_numero_documento", "seguimiento_por_codigo"]:
            # Cambiar a búsqueda general para más detalles
            return {
                "intent": "buscar_documentos",
                "parametro": search_info["parameter"],
                "is_follow_up": True,
                "follow_up_type": "detailed_search"
            }
    
    # Fallback: mantener último contexto
    if last_intent and last_params.get("parametro"):
        return {
            "intent": "buscar_documentos",
            "parametro": last_params["parametro"],
            "is_follow_up": True,
            "follow_up_type": "more_info"
        }
    
    return None

def generar_respuesta_contextual(respuesta_base: str, context: Dict[str, Any], intent: str) -> str:
    """Enriquece la respuesta con contexto conversacional - VERSIÓN MEJORADA"""
    
    # Indicar follow-ups
    if context.get("is_follow_up") and intent != "saludo":
        respuesta_base = "🔄 " + respuesta_base
    
    # Sugerencias contextuales inteligentes
    sugerencias_contextuales = []
    
    # Si hay documentos recientes, sugerir búsquedas relacionadas
    if context.get("recent_documents") and intent != "buscar_documentos":
        if len(context["recent_documents"]) == 1:
            sugerencias_contextuales.append(
                f""
            )
        elif len(context["recent_documents"]) > 1:
            sugerencias_contextuales.append(
                f"💡 *También puedes buscar detalles de: {', '.join(context['recent_documents'][:2])}*"
            )
    
    # Si hay proyectos recientes
    if context.get("recent_projects") and intent not in ["seguimiento_por_proyecto", "buscar_documentos"]:
        sugerencias_contextuales.append(
            f"💡 *Proyecto consultado recientemente: {context['recent_projects'][0]}*"
        )
    
    # Si la sesión es larga, ofrecer resumen
    if context.get("session_length", 0) > 5:
        sugerencias_contextuales.append(
            "📝 *Tip: Si necesitas un resumen de lo consultado, solo pregúntame*"
        )
    
    # Agregar sugerencias contextuales
    if sugerencias_contextuales and not any(word in respuesta_base.lower() for word in ["error", "no se encontró"]):
        respuesta_base += "\n\n" + "\n".join(sugerencias_contextuales[:2])  # Máximo 2 sugerencias
    
    return respuesta_base

