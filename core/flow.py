# core/flow.py

import json
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from core.conversationMemory import ConversationMemory
from services.notificacion_services import notification_manager
# Instancia global de memoria
conversation_memory = ConversationMemory()

def detectar_intencion_con_contexto(texto_usuario: str, phone_number: str, conversation_context=None, conversation_state=None) -> Dict[str, Any]:
    """
    Sistema principal de detección de intención con estados de conversación
    Compatible con llamadas desde procesar_mensaje con parámetros adicionales
    """
    # Si no se proporcionan, obtener estado y contexto de la conversación
    if conversation_state is None:
        conversation_state = conversation_memory.get_conversation_state(phone_number)
    if conversation_context is None:
        conversation_context = conversation_memory.get_conversation_context(phone_number)
    
    # Obtener documentos guardados
    documentos_guardados = conversation_memory.get_conversation_documents(phone_number)
    
    print(f"🔍 Analizando mensaje con contexto completo:")
    print(f"   Usuario: {texto_usuario[:50]}...")
    print(f"   Estado: {conversation_state['state']}")
    print(f"   Contexto: {conversation_context['session_length']} turnos")
    print(f"   Último intent: {conversation_context.get('last_intent', 'None')}")
    print(f"   Documentos guardados: {len(documentos_guardados)}")
    print(f"   Buscar BD completa: {conversation_state['should_search_full_db']}")
    
    # 🔄 RESET MANUAL - Verificar "hola"
    if texto_usuario.lower().strip() in ["hola", "hello", "hi"]:
        print("🔄 Reset manual detectado en flow.py")
        conversation_memory._reset_conversation_state(phone_number)
        return {
            "intent": "saludo",
            "parametro": None,
            "reset_triggered": True,
            "estado": "normal"
        }
    
    # 🎯 DETECCIÓN SEGÚN ESTADO DE CONVERSACIÓN
    if conversation_state['state'] == "awaiting_notification_choice":
        print("🔍 Procesando en modo awaiting_notification_choice")
        
        # Usar IA mejorada
        from services.ia_service import detectar_intencion_con_contexto
        
        intent_data = detectar_intencion_con_contexto(
            texto_usuario,
            phone_number,
            conversation_context,
            conversation_state
        )
        
        if intent_data and intent_data.get("intent") == "seleccionar_notificacion":
            notification_index = intent_data.get("parameters", {}).get("notification_index")
            
            if notification_index:
                # Obtener la notificación seleccionada
                notification = notification_manager.get_notification_by_index(phone_number, notification_index)
                
                if notification:
                    return {
                        "intent": "seleccionar_notificacion",
                        "parametro": notification_index,
                        "notification_data": notification,
                        "estado": "normal"
                    }
                else:
                    return {
                        "intent": "error_seleccion_notificacion",
                        "parametro": notification_index,
                        "error": "No encontré esa notificación. Intenta con otro número o código.",
                        "estado": "normal"
                    }
        
        # Si no es selección de notificación, procesar como intent normal
        elif intent_data:
            result = convertir_formato_gemini(intent_data)
            result["estado"] = "normal"
            return result
        
        # Fallback manual
        return procesar_awaiting_notification_choice_fallback(texto_usuario, phone_number)
    # 1. ESTADO: awaiting_choice (esperando elección de lista)
    if conversation_state['state'] == "awaiting_choice":
        print("🔍 Procesando en modo awaiting_choice")
        return procesar_awaiting_choice(texto_usuario, conversation_context, documentos_guardados, phone_number)
    
    # 2. ESTADO: awaiting_verification (esperando confirmación)
    elif conversation_state['state'] == "awaiting_verification":
        print("🔍 Procesando en modo awaiting_verification")
        return procesar_awaiting_verification(texto_usuario, conversation_context)
    
    # 3. ESTADO: filtered_search (búsqueda en lista guardada)
    elif conversation_state['state'] == "filtered_search":
        print("🔍 Procesando en modo filtered_search")
        return procesar_filtered_search(texto_usuario, conversation_context, documentos_guardados)
    
    # 4. ESTADO: initial (estado normal)
    else:
        print("🔍 Procesando en modo initial")
        return procesar_initial_state(texto_usuario, conversation_context)


def procesar_awaiting_choice(texto_usuario: str, context: Dict[str, Any], documentos: List[Dict], phone_number: str) -> Dict[str, Any]:
    """Procesa mensajes cuando se espera elección de lista"""
    try:
        from services.ia_service import seleccionar_respuesta
        
        # Llamar a función de selección mejorada
        result = seleccionar_respuesta(
            texto_usuario, 
            context, 
            documentos,
            conversation_state={"state": "awaiting_choice"}
        )
        if result:
            intent = result.get("intent", "select_document")
            parameters = result.get("parameters", {})
            
            # Determinar si es confirmación o selección
            if intent == "confirmar_seleccion":
                return {
                    "intent": "confirmar_seleccion",
                    "parametro": None,
                    "confirmacion_positiva": parameters.get("confirmacion_positiva", False),
                    "estado": "normal"
                }
            
            # Selección de documento específico
            elif intent == "select_document":
                docs_encontrados = result.get("documentos_encontrados")
                
                if docs_encontrados:
                    return {
                        "intent": "select_document", 
                        "parametro": docs_encontrados[0].get("codigo_sistema"),
                        "documento_seleccionado": parameters,
                        "multiple_results": len(docs_encontrados) > 1,
                        "resultados": docs_encontrados,
                        "estado": "normal"
                    }
                else:
                    return {
                        "intent": "error_seleccion",
                        "parametro": None,
                        "error": "No se encontró el documento especificado",
                        "estado": "normal"
                    }
                
            # Nueva consulta mientras está en selección
            elif parameters.get("nueva_consulta"):
                return procesar_nueva_consulta_en_seleccion(texto_usuario, context)
        
        # Fallback si no se pudo procesar la selección
        return {
            "intent": "error_seleccion",
            "parametro": None,
            "error": "No pude entender tu selección. Intenta con un número (1, 2, 3...) o el código del documento.",
            "estado": "normal"
        }
        
    except Exception as e:
        print(f"❌ Error en procesar_awaiting_choice: {e}")
        return {
            "intent": "error",
            "parametro": None,
            "error": str(e),
            "estado": "normal"
        }


def procesar_awaiting_verification(texto_usuario: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Procesa mensajes cuando se espera verificación de documento"""
    texto_lower = texto_usuario.lower().strip()
    
    # Respuestas positivas
    if any(word in texto_lower for word in ["si", "sí", "yes", "correcto", "exacto", "ese", "perfecto", "está bien"]):
        return {
            "intent": "confirmar_seleccion",
            "parametro": None,
            "confirmacion_positiva": True,
            "estado": "normal"
        }
    
    # Respuestas negativas
    elif any(word in texto_lower for word in ["no", "nope", "incorrecto", "otro", "diferente", "no es"]):
        return {
            "intent": "confirmar_seleccion",
            "parametro": None,
            "confirmacion_positiva": False,
            "estado": "normal"
        }
        
    # Si no es confirmación, procesar como nueva consulta
    else:
        print("🔄 No es confirmación, procesando como nueva consulta")
        return procesar_initial_state(texto_usuario, context)


def procesar_filtered_search(texto_usuario: str, context: Dict[str, Any], documentos: List[Dict]) -> Dict[str, Any]:
    """Procesa búsquedas cuando está en modo filtrado"""
    # Detectar intent con marcador de búsqueda filtrada
    result = procesar_initial_state(texto_usuario, context)
    
    # Marcar que debe buscar en documentos guardados
    if result.get("intent") in [
        "seguimiento_por_numero_documento", "seguimiento_por_codigo", 
        "seguimiento_por_usuario", "seguimiento_por_proyecto", 
        "seguimiento_por_asunto", "seguimiento_por_consecutivo"
    ]:
        result["search_in_filtered"] = True
        result["documentos_disponibles"] = documentos
        print(f"🔍 Búsqueda filtrada marcada para intent: {result['intent']}")
    
    return result


def procesar_initial_state(texto_usuario: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Procesa mensajes en estado normal/inicial"""
    # Manejar follow-ups mejorados si es necesario
    if context.get("is_follow_up"):
        follow_up_result = manejar_follow_up_mejorado(texto_usuario, context)
        if follow_up_result:
            print(f"✅ Follow-up procesado: {follow_up_result['intent']}")
            follow_up_result["estado"] = "normal"
            return follow_up_result
    
    # Usar detección con contexto avanzado
    try:
        from services.ia_service import detectar_intencion_con_contexto
        
        # Obtener estado de conversación para pasar a Gemini
        conversation_state = conversation_memory.get_conversation_state(context.get("phone_number", ""))
        
        intent_data = detectar_intencion_con_contexto(
            texto_usuario, 
            context,
            conversation_state
        )
        
        if intent_data:
            result = convertir_formato_gemini(intent_data)
            result["estado"] = "normal"
            print(f"✅ Gemini con contexto: {result['intent']}")
            return result
            
    except Exception as e:
        print(f"⚠️ Error con Gemini contextual: {e}")
    
    # Fallback: detección básica
    try:
        from services.ia_service import detectar_intencion_optimizado
        result = detectar_intencion_optimizado(texto_usuario)
        result["estado"] = "normal"
        print(f"✅ Detección básica: {result.get('intent', 'unknown')}")
        return result
        
    except Exception as e:
        print(f"❌ Error en detección básica: {e}")
        return {
            "intent": "error",
            "parametro": None,
            "error": "No pude procesar tu mensaje",
            "estado": "normal"
        }


def procesar_nueva_consulta_en_seleccion(texto_usuario: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Maneja nuevas consultas mientras se está en proceso de selección"""
    print("🔄 Nueva consulta detectada durante selección")
    
    # Procesar como consulta normal pero marcar contexto
    result = procesar_initial_state(texto_usuario, context)
    result["interrumpir_seleccion"] = True
    result["nueva_consulta_durante_seleccion"] = True
    
    return result



def convertir_formato_gemini(gemini_result: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte el formato de Gemini al formato esperado del sistema - VERSIÓN CORREGIDA"""
    intent = gemini_result.get("intent")
    parameters = gemini_result.get("parameters", {})
    
    # Determinar el parámetro principal según el intent
    parametro = None
    if intent in ["seguimiento_por_codigo", "seguimiento_por_numero_documento", "seguimiento_por_consecutivo"]:
        parametro = parameters.get("document_id")
    elif intent == "seguimiento_por_usuario":
        parametro = parameters.get("usuario")
    elif intent == "seguimiento_por_proyecto":
        parametro = parameters.get("proyecto")
    elif intent in ["buscar_documentos", "seguimiento_por_asunto", "conversacion_general"]:
        parametro = parameters.get("consulta")
    elif intent == "select_document":
        parametro = parameters.get("document_id")
    elif intent == "confirmar_seleccion":
        parametro = None
    # 🆕 NUEVO: Manejar selección de notificaciones
    elif intent == "seleccionar_notificacion":
        parametro = parameters.get("notification_index")  # ¡ESTO ESTABA FALTANDO!
    elif intent == "error_seleccion_notificacion":
        parametro = parameters.get("notification_index")
    
    # Construir resultado
    result = {
        "intent": intent,
        "parametro": parametro
    }
    
    # Mantener información de contexto
    if parameters.get("is_follow_up"):
        result["is_follow_up"] = True
    if parameters.get("context_reference"):
        result["is_contextual_reference"] = True
    if parameters.get("search_in_filtered"):
        result["search_in_filtered"] = True
    if parameters.get("confirmacion_positiva") is not None:
        result["confirmacion_positiva"] = parameters["confirmacion_positiva"]
    if parameters.get("posicion_lista"):
        result["posicion_lista"] = parameters["posicion_lista"]
    
    # 🆕 NUEVO: Mantener parámetros específicos de notificaciones
    if parameters.get("notification_index"):
        result["notification_index"] = parameters["notification_index"]
    
    # Mantener parámetros adicionales relevantes
    additional_params = ["wants_contact", "nuevo_query", "results_count"]
    for param in additional_params:
        if param in parameters:
            result[param] = parameters[param]
    
    return result


def manejar_follow_up_mejorado(texto_usuario: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Maneja follow-ups basados en contexto conversacional"""
    last_intent = context.get("last_intent")
    last_params = context.get("last_parameters", {})
    texto_lower = texto_usuario.lower().strip()
    
    print(f"🔄 Procesando follow-up: '{texto_usuario}' | Último intent: {last_intent}")
    
    # Referencias directas a documentos previos
    if any(word in texto_lower for word in ["este", "ese", "el documento", "ese documento", "el anterior"]):
        if context.get("recent_documents"):
            return {
                "intent": "seguimiento_por_numero_documento",
                "parametro": context["recent_documents"][0],
                "is_follow_up": True,
                "follow_up_type": "document_reference"
            }
    
    # Referencias a proyectos previos  
    if any(word in texto_lower for word in ["este proyecto", "ese proyecto", "el proyecto"]):
        if context.get("recent_projects"):
            return {
                "intent": "seguimiento_por_proyecto",
                "parametro": context["recent_projects"][0],
                "is_follow_up": True,
                "follow_up_type": "project_reference"
            }
    
    # Conectores que mantienen contexto
    if texto_lower in ["y", "también", "además", "otro", "otra", "más"]:
        if last_intent and last_params.get("parametro"):
            return {
                "intent": last_intent,
                "parametro": last_params.get("parametro"),
                "is_follow_up": True,
                "follow_up_type": "continuation"
            }
    
    # Búsquedas relacionadas
    if any(word in texto_lower for word in ["relacionado", "similar", "parecido"]):
        if context.get("recent_documents"):
            return {
                "intent": "buscar_documentos",
                "parametro": f"relacionado con {context['recent_documents'][0]}",
                "is_follow_up": True,
                "follow_up_type": "related_search"
            }
    
    # Solicitudes de más información
    if any(phrase in texto_lower for phrase in ["más información", "más detalles", "amplía", "explica más"]):
        if last_intent and last_params.get("parametro"):
            return {
                "intent": "buscar_documentos",
                "parametro": last_params.get("parametro"),
                "is_follow_up": True,
                "follow_up_type": "more_info"
            }
    
    return None



def procesar_awaiting_notification_choice_fallback(texto_usuario: str, phone_number: str) -> Dict[str, Any]:
    """Fallback manual para selección de notificación"""
    import re
    
    # Extraer número o código
    numeros = re.findall(r'\d+', texto_usuario)
    codigos = re.findall(r'PR[-]?\d+', texto_usuario, re.IGNORECASE)
    
    notification_index = None
    
    if codigos:
        notification_index = codigos[0]
    elif numeros:
        notification_index = int(numeros[0])
    
    if notification_index:
        from services.notificacion_services import notification_manager
        notification = notification_manager.get_notification_by_index(phone_number, notification_index)
        
        if notification:
            return {
                "intent": "seleccionar_notificacion",
                "parametro": notification_index,
                "notification_data": notification,
                "estado": "normal"
            }
    
    return {
        "intent": "error_seleccion_notificacion",
        "parametro": notification_index,
        "error": "No encontré esa notificación. Usa el número (1, 2, 3...) o el código del documento.",
        "estado": "normal"
    }



