
from flask import Flask, request, jsonify
import requests
from services.db_service import *
from config import *
from core.constants import *
from services.algolia_service import *
from core.flow import *
from utils.formatter import *
from services.ia_service import seleccionar_respuesta, consultar_ia_con_memoria
from services.notificacion_services import *
from datetime import datetime, timedelta

#app = Flask(__name__)

def procesar_mensaje(mensaje, numero_telefono, conversation_state=None, conversation_context=None, intent_forzado=None):
    """Procesa mensaje con estados de conversación integrados"""
    try:
        print(f"\n{'='*60}")
        print(f"📱 Procesando mensaje de {numero_telefono}")
        print(f"💬 Mensaje: {mensaje}")
        print(f"🔄 Estado actual: {conversation_state.get('state', 'initial') if conversation_state else 'initial'}")
        print(f"🔍 Buscar BD completa: {conversation_state.get('should_search_full_db', True) if conversation_state else True}")

        respuesta = ""
        tipo_resultado = "consulta"
        intent = "unknown"
        parameters = {}

        # VERIFICAR RESET MANUAL (palabra "hola")
        if mensaje.lower().strip() in ["hola", "hello", "hi"]:
            print("🔄 Reinicio manual detectado")
            conversation_memory._reset_conversation_state(numero_telefono)
            return {
                "tipo": "saludo",
                "respuesta": respuesta_saludo(),
                "intent": "saludo",
                "parameters": {"reset_triggered": True}
            }

        # Obtener contexto si no se proporcionó
        if conversation_context is None:
            conversation_context = conversation_memory.get_conversation_context(numero_telefono)

        # MANEJO ESPECIAL SEGÚN ESTADO
        documentos_guardados = None
        if conversation_state and not conversation_state.get('should_search_full_db', True):
            documentos_guardados = conversation_memory.get_conversation_documents(numero_telefono)
            
            print(f"📚 Documentos guardados disponibles: {len(documentos_guardados)}")

        # DETECCIÓN DE INTENCIÓN CON ESTADO
        intent_data = detectar_intencion_con_contexto(
            mensaje, 
            numero_telefono,
            conversation_context, 
            conversation_state
        )
        
        if not intent_data:
            return {
                "tipo": "error",
                "respuesta": "❌ No pude procesar tu mensaje. Intenta de nuevo.",
                "intent": "error",
                "parameters": {}
            }

        intent = intent_data.get("intent", "unknown")
        parametro = intent_data.get("parametro")
        
        #  Diferenciar entre selección de notificación y búsqueda normal
        if conversation_state.get('state') == 'awaiting_choice':
            source_intent = None
            if documentos_guardados:
                # Obtener source_intent del primer documento
                source_intent = documentos_guardados[0].get('source_intent')
            
            if source_intent == 'notificacion_plantilla':
                # Es selección de notificación - usar formato detallado
                resultado = procesar_notificacion_seleccionada(
                    mensaje, 
                    numero_telefono, 
                    intent_data, 
                    
                )
                
                if resultado:
                    return resultado
            #  VERIFICAR SI ESTAMOS EN FLUJO DE NOTIFICACIONES
            es_flujo_notificacion = conversation_state.get('is_notification_flow', False)
            
            if es_flujo_notificacion:
                return procesar_notificacion_seleccionada(mensaje, numero_telefono, intent_data)
            else:
                #  Usar formateo estándar
                lista_documentos = intent_data.get("resultados")
                documento_seleccionado = intent_data.get("documento_seleccionado")

                respuesta = formatear_seguimiento(documento_seleccionado)
            
                return {
                    "tipo": intent,
                    "respuesta": respuesta,
                    "intent": intent,
                    "parameters": None,
                    "resultados": lista_documentos
                }

        # PROCESAR SEGÚN INTENT Y ESTADO
        if intent == "saludo":
            respuesta = respuesta_saludo_contextual(conversation_context)
            tipo_resultado = "saludo"
            
        elif intent == "confirmar_seleccion":
            confirmacion_positiva = intent_data.get("confirmacion_positiva")
            
            if confirmacion_positiva:
                if conversation_state.get("state") == "awaiting_choice":
                    conversation_memory.set_filtered_search_mode(numero_telefono)
                    respuesta = "Perfecto! ¿En qué más puedo ayudarte? \n Si quieres iniciar una nueva búsqueda, escribe 'Hola'"
                elif conversation_state.get("state") == "awaiting_verification":
                    respuesta = "Perfecto! ¿En qué más puedo ayudarte? \n Si quieres iniciar una nueva búsqueda, escribe 'Hola'"
                tipo_resultado = "confirmacion_positiva"
            else:
                if conversation_state.get("state") == "awaiting_choice":
                    respuesta = "Entiendo. Realiza una búsqueda más específica basada en los resultados mostrados. \n Si quieres iniciar una nueva búsqueda, escribe 'Hola'."
                elif conversation_state.get("state") == "awaiting_verification":
                    respuesta = "Entiendo. ¿Podrías especificar mejor el documento que buscas? \n Si quieres iniciar una nueva búsqueda, escribe 'Hola'."
                tipo_resultado = "confirmacion_negativa"

        elif intent == "seleccionar_documento":
            # Usuario está seleccionando de una lista
            if documentos_guardados:
                #Verificar si viene de notificación
                source_intent = documentos_guardados[0].get('source_intent') if documentos_guardados else None
                print(f"🔍 Source intent detectado: {source_intent}")
                
                resultado_seleccion = seleccionar_respuesta(
                    mensaje, 
                    conversation_context, 
                    documentos_guardados,
                    conversation_state
                )
                
                if resultado_seleccion:
                    docs_encontrados = resultado_seleccion.get("documentos_encontrados", [])
                    
                    if docs_encontrados:
                        if len(docs_encontrados) == 1:
                            # Un documento específico encontrado
                            doc = docs_encontrados[0]
                            
                            # Usar formato DETALLADO
                            respuesta = formatear_documento_detalle_notificacion(doc)
                            
                            return {
                                "tipo": "detalle",
                                "respuesta": respuesta,
                                "intent": "seleccionar_documento",
                                "parameters": resultado_seleccion.get('parameters', {}),
                                "resultados": [doc]
                            }
                        
                        elif len(docs_encontrados) > 1:
                            # Múltiples documentos encontrados - mostrar lista simple
                            from utils.formatter import formatear_lista_documentos
                            respuesta = formatear_lista_documentos(docs_encontrados)
                            
                            return {
                                "tipo": "lista",
                                "respuesta": respuesta,
                                "intent": "seleccionar_documento",
                                "parameters": {"results_count": len(docs_encontrados)},
                                "resultados": docs_encontrados
                            }
                            
                        else:
                            # Múltiples documentos encontrados
                            print(f"📋 Múltiples documentos encontrados: {len(docs_encontrados)}")
                            respuesta = formatear_lista_documentos(docs_encontrados)
                            tipo_resultado = "lista"
                            parameters["results_count"] = len(docs_encontrados)
                    else:
                        respuesta = "❌ No encontré el documento que mencionas en los resultados anteriores. ¿Puedes ser más específico?"
                        tipo_resultado = "error"
                else:
                    respuesta = "❌ No pude procesar tu selección. Intenta de nuevo."
                    tipo_resultado = "error"
            else:
                respuesta = "❌ No hay documentos disponibles para seleccionar. Realiza una nueva búsqueda."
                tipo_resultado = "error"

        # Actualización en el manejo de intents
        elif intent == "contactar_encargado":
            print("Conversacion Context", conversation_context)
            respuesta = manejar_contacto_encargado(numero_telefono, conversation_context, tipo_contacto="encargado")
            tipo_resultado = "contacto"

     
        elif intent in ["listar_sin_respuesta", "listar_sin_firma", "listar_inactivos", "listar_stand_by"]:
            print(f"📋 Listando notificaciones de tipo: {intent}")
            
            # Mapear intent a tipo interno
            tipo_map = {
                "listar_sin_respuesta": "sin_respuesta",
                "listar_sin_firma": "sin_firma",
                "listar_inactivos": "inactivos",
                "listar_stand_by": "stand_by"
            }
            
            tipo_interno = tipo_map[intent]
            
            # Obtener y formatear notificaciones
            mensaje_formateado = notification_manager.format_notifications_by_type(
                numero_telefono, 
                tipo_interno
            )
            
            # Obtener notificaciones para guardar en memoria
            notifications = notification_manager.get_notifications_by_type(
                numero_telefono, 
                tipo_interno
            )
            
            if notifications and len(notifications) == 1:
                # Una sola notificación, guardar documentos
                documentos = notifications[0].get('documentos', [])
                
                conversation_memory.set_conversation_documents(
                    phone_number=numero_telefono,
                    documents=documentos,
                    source_intent=intent,
                    source_query=f"Notificaciones {tipo_interno}"
                )
                
                conversation_memory.set_conversation_state(
                    phone_number=numero_telefono,
                    state="awaiting_choice",
                    additional_info={
                        "has_document_list": True,
                        "notification_type": tipo_interno,
                        "current_flow": "lista"
                    }
                )
                
                return {
                    "respuesta": mensaje_formateado,
                    "tipo": "lista",
                    "intent": intent,
                    "resultados": documentos,
                    "notification_type": tipo_interno
                }
            
            return {
                "respuesta": mensaje_formateado,
                "tipo": "consulta",
                "intent": intent,
                "notification_type": tipo_interno
            }
            
        elif intent == "contactar_responsable":
            print("Conversacion Context", conversation_context)
            respuesta = manejar_contacto_encargado(numero_telefono, conversation_context, tipo_contacto="responsable")
            tipo_resultado = "contacto"

        elif intent == "buscar_documentos" or intent_forzado == 'buscar_documentos':
            nivel_acceso = conversation_context.get("nivel_acceso")
            
            if nivel_acceso == "user":
                respuesta = "❌ Tu nivel de acceso no permite realizar búsquedas avanzadas. Puedes consultar documentos por número, proyecto o asunto."
                tipo_resultado = "error"
            elif parametro:
                print(f"🔍 Realizando búsqueda en Algolia: {parametro}")
                
                consulta_final = parametro
                if parameters.get("is_follow_up") and conversation_context.get("recent_searches"):
                    consulta_final = f"{parametro} {conversation_context['recent_searches'][0]}"
                    print(f"🧠 Consulta enriquecida: {consulta_final}")
                
                documentos_algolia = generar_respuesta_busqueda_algolia(consulta_final)
                respuesta = documentos_algolia
                tipo_resultado = "algolia"
                parameters["algolia_query"] = consulta_final
            else:
                respuesta = "❌ Por favor, especifica tu búsqueda."
                tipo_resultado = "error"

        elif intent in ["seguimiento_por_numero_documento", "seguimiento_por_codigo", 
                       "seguimiento_por_usuario", "seguimiento_por_proyecto", 
                       "seguimiento_por_asunto", "seguimiento_por_consecutivo"] and intent_forzado != 'buscar_documentos':
            
            if parametro:
                print(f"🔍 Consultando {intent} para: {parametro}")
                
                if parameters.get("search_in_filtered") and documentos_guardados:
                    print(f"🔍 Búsqueda filtrada en {len(documentos_guardados)} documentos guardados")
                    seguimientos = buscar_en_documentos_guardados(documentos_guardados, parametro, intent)
                else:
                    print("🔍 Búsqueda en base de datos completa")
                    if intent == "seguimiento_por_numero_documento":
                        seguimientos = consultar_por_numero_documento(parametro)
                    elif intent == "seguimiento_por_codigo":
                        seguimientos = consultar_por_codigo_sistema(parametro)
                    elif intent == "seguimiento_por_usuario":
                        seguimientos = consultar_documentos_por_usuario(parametro)
                    elif intent == "seguimiento_por_proyecto":
                        seguimientos = consultar_documentos_por_proyecto(parametro)
                    elif intent == "seguimiento_por_asunto":
                        seguimientos = consultar_documento_por_asunto(parametro)
                    elif intent == "seguimiento_por_consecutivo":
                        seguimientos = consultar_por_numero_consecutivo(parametro)

                if not seguimientos:
                    if intent == "seguimiento_por_numero_documento":
                        print("⚠️ No se encontró por número de documento, probando con consecutivo...")
                        seguimientos = consultar_por_numero_consecutivo(parametro)
                        intent = "seguimiento_por_consecutivo"
                    elif intent == "seguimiento_por_consecutivo":
                        print("⚠️ No se encontró por consecutivo, probando con número de documento...")
                        seguimientos = consultar_por_numero_documento(parametro)
                        intent = "seguimiento_por_numero_documento"
                    elif intent == "seguimiento_por_asunto":
                        print("⚠️ No se encontró por asunto, probando con proyecto...")
                        seguimientos = consultar_documentos_por_proyecto(parametro)
                        intent = "seguimiento_por_proyecto"

                if seguimientos:
                    formato = formatear_seguimiento(seguimientos)
                    respuesta = formato["contenido"]
                    tipo_resultado = formato["tipo"]
                    
                    if not parameters.get("search_in_filtered"):
                        conversation_memory.set_conversation_documents(
                            numero_telefono, 
                            seguimientos,
                            source_intent=intent,
                            source_query=parametro
                        )
                    
                    if isinstance(seguimientos, list):
                        parameters["results_count"] = len(seguimientos)
                        parameters["resultados"] = seguimientos
                    else:
                        parameters.update(seguimientos)
                        
                    print(f"📊 Tipo de resultado: {tipo_resultado}")
                else:
                    respuesta = (
                        f"❌ No se encontró información para: *{parametro}*\n\n"
                        f"{SUGERENCIAS_BUSQUEDA}"
                    )
                    tipo_resultado = "no_encontrado"
                    
                    if conversation_context.get("recent_documents"):
                        respuesta += f"\n💡 *¿Quizás querías consultar: {conversation_context['recent_documents'][0]}?*"
            else:
                respuesta = "❌ Por favor, especifica el parámetro para consultar."
                tipo_resultado = "error"
        
        elif intent == "seleccionar_notificacion":
            #  SIEMPRE usar el handler específico de notificaciones
            return procesar_notificacion_seleccionada(mensaje, numero_telefono, intent_data)

        elif intent == "error_seleccion_notificacion":
            parametro = intent_data.get("parametro")
            error_msg = intent_data.get("error") or f"❌ No encontré '{parametro}' en la lista.\n\nIntenta con el número (1, 2, 3...) o el código del documento."
            return {
                "tipo": "error_notificacion",
                "respuesta": error_msg,
                "intent": intent,
                "parameters": {"parametro": parametro}
            }

        else:
            texto = mensaje.lower().strip()
            
            if any(palabra in texto for palabra in ["ayuda", "cómo buscar", "como buscar", "necesito ayuda", "no entiendo"]):
                respuesta = f"ℹ️ Parece que necesitas ayuda.\n\n{SUGERENCIAS_BUSQUEDA}"
                
                if conversation_context.get("recent_documents"):
                    respuesta += f"\n\n📋 *Documentos consultados: {', '.join(conversation_context['recent_documents'][:3])}*"
                
                tipo_resultado = "ayuda"
            else:
                consulta_enriquecida = mensaje
                if conversation_context.get("recent_documents") or conversation_context.get("recent_projects"):
                    contexto_adicional = "Contexto previo: "
                    if conversation_context.get("recent_documents"):
                        contexto_adicional += f"Documentos: {', '.join(conversation_context['recent_documents'][:2])}. "
                    if conversation_context.get("recent_projects"):
                        contexto_adicional += f"Proyectos: {', '.join(conversation_context['recent_projects'][:2])}. "
                    if conversation_context.get("recent_searches"):
                        contexto_adicional += f"Búsquedas: {', '.join(conversation_context['recent_searches'][:2])}. "
                    
                    consulta_enriquecida = f"{contexto_adicional}\nConsulta: {mensaje}"
                    print(f"🧠 Consulta enriquecida: {consulta_enriquecida[:100]}...")
                
                respuesta_ia = consultar_ia_con_memoria(consulta_enriquecida, conversation_context, conversation_state)
                if respuesta_ia:
                    respuesta = (
                        f"🤖 {respuesta_ia}\n\n"
                        f"💡 *Puedes reiniciar escribiendo 'hola' o se reiniciará automáticamente en 1 hora*"
                    )
                    tipo_resultado = "ia"
                else:
                    respuesta = (
                        f"❌ No entendí tu consulta. "
                        f"Puedes intentar con un formato específico.\n\n"
                        f"{SUGERENCIAS_BUSQUEDA}"
                    )
                    tipo_resultado = "error"

        print(f"✅ Respuesta generada: {len(respuesta)} caracteres")
        print(f"📊 Tipo resultado: {tipo_resultado}")
        print(f"🎯 Intent procesado: {intent}")
        print(f"{'='*60}\n")
        
        return {
            "tipo": tipo_resultado,
            "respuesta": respuesta,
            "intent": intent,
            "parameters": parameters,
            "resultados": parameters.get("resultados", []) if tipo_resultado == "lista" else None
        }

    except Exception as e:
        print(f"❌ Error procesando mensaje: {e}")
        import traceback
        traceback.print_exc()
        return {
            "tipo": "error",
            "respuesta": "❌ Disculpa, ocurrió un error interno. Por favor, inténtalo de nuevo.",
            "intent": "error",
            "parameters": {}
        }
    

def formatear_documento_detalle_notificacion(documento):
    """
    Formatea un documento individual con formato DETALLADO
    Usado cuando el usuario selecciona de la lista de notificaciones
    """
    # Extraer datos del documento
    doc_data = documento.get('documento', documento)
    proyecto_data = documento.get('proyecto', {})
    encargados = documento.get('encargados', [])
    responsables = documento.get('responsables', [])
    
    # Formatear encargados
    if encargados and len(encargados) > 0:
        if isinstance(encargados[0], dict):
            encargados_texto = ", ".join([
                f"{e.get('nombres', '')} {e.get('apellido_paterno', '')}".strip()
                for e in encargados
            ])
        else:
            encargados_texto = ", ".join(str(e) for e in encargados)
    else:
        encargados_texto = "N/A"
    
    # Formatear responsables
    if responsables and len(responsables) > 0:
        if isinstance(responsables[0], dict):
            responsables_texto = ", ".join([
                f"{r.get('nombre', '')} {r.get('apellido_paterno', '')}".strip()
                for r in responsables
            ])
        else:
            responsables_texto = ", ".join(str(r) for r in responsables)
    else:
        responsables_texto = None
    
    # Extraer datos principales
    codigo_sistema = doc_data.get('codigo_sistema', 'N/A')
    numero_documento = doc_data.get('numero_documento', 'N/A')
    asunto = doc_data.get('asunto', 'Sin asunto')
    estado = doc_data.get('estado', 'N/A')
    fecha_ingreso = doc_data.get('fecha_ingreso', 'N/A')
    dias_inactivo = doc_data.get('dias_inactivo')
    
    # Nombre del proyecto
    if isinstance(proyecto_data, dict):
        proyecto_nombre = proyecto_data.get('nombre', 'N/A')
    else:
        proyecto_nombre = str(proyecto_data) if proyecto_data else 'N/A'
    
    # Construir mensaje detallado
    mensaje = f"""⚠️ *Alerta de Documento* ⚠️
⏱️ Han pasado *15 días sin movimiento*.  
Por favor, revisa y actualiza su estado a *"Atendido"* si corresponde. 🙏

📄 *Documento:* {numero_documento}  
🆔 *Código sistema:* {codigo_sistema}  
📋 *Asunto:* {asunto}  
🏗️ *Proyecto:* {proyecto_nombre}  
👤 *Encargado:* {encargados_texto}  
🔄 *Estado:* {estado}  
📅 *Fecha Ingreso:* {fecha_ingreso}"""
    
    # Agregar días de inactividad si existe
    if dias_inactivo is not None:
        mensaje += f"\n⏱️ *Días inactivo:* {dias_inactivo} días"
    
    # Agregar información de contacto
    mensaje += f"\n\n💡 *¿Quieres contactar?*  \n👤 *Encargado:* {encargados_texto}"
    
    if responsables_texto:
        mensaje += f"\n🏗️ *Responsable proyecto:* {responsables_texto}"
    
    return mensaje


#PROCESAR LA SELECCIÓN DE NOTIFICACIÓN
def procesar_notificacion_seleccionada(mensaje, numero_telefono, intent_data):
    """Procesa selección de notificación con formato detallado mejorado"""
    try:
        print("\n🔔 Procesando selección de notificación...", intent_data)
        parametro = (
            intent_data.get("parametro")
            or intent_data.get("notification_index")
            or (intent_data.get("documento_seleccionado") or {}).get("posicion_lista")
        )
                
        print(f"🔔 Procesando notificación #{parametro}")
        
        if parametro is None:
            return {
                "tipo": "error",
                "respuesta": "❌ No se especificó qué notificación ver. Usa 'mis notificaciones' para ver la lista.",
                "intent": "error_notificacion",
                "parameters": {}
            }
        
        # Obtener notificación
        notification = notification_manager.get_notification_by_index(numero_telefono, parametro)
        
        if not notification:
            return {
                "tipo": "error",
                "respuesta": f"❌ No pude encontrar la notificación #{parametro}. Usa 'mis notificaciones' para ver las disponibles.",
                "intent": "error_notificacion",
                "parameters": {}
            }
        
        print(f"✅ Notificación encontrada: {notification.get('id', 'N/A')}")
        
        # Marcar como vista
        notification_manager.mark_notification_as_viewed(numero_telefono, notification["id"])
        
     
        payload = notification.get('payload', {})
        documento = payload.get('documento', {})
        proyecto = payload.get('proyecto', {})
        encargados = payload.get('encargados', [])
        responsables = payload.get('responsables', [])
        
        # Datos principales
        codigo_sistema = notification.get('codigo_sistema') or documento.get('codigo_sistema', 'N/A')
        numero_documento = notification.get('numero_documento') or documento.get('numero_documento', 'N/A')
        asunto = documento.get('asunto', 'Sin asunto')
        estado = documento.get('estado', 'N/A')
        fecha_ingreso = documento.get('fecha_ingreso', 'N/A')
        dias_inactivo = documento.get('dias_inactivo')
        
        # Nombre del proyecto
        if isinstance(proyecto, dict):
            proyecto_nombre = proyecto.get('nombre', 'N/A')
        else:
            proyecto_nombre = str(proyecto) if proyecto else 'N/A'
        
        # Formatear encargados
        if encargados and len(encargados) > 0:
            if isinstance(encargados[0], dict):
                encargados_texto = ", ".join([
                    f"{e.get('nombres', '')} {e.get('apellido_paterno', '')}".strip()
                    for e in encargados
                ])
            else:
                encargados_texto = ", ".join(str(e) for e in encargados)
        else:
            encargados_texto = "N/A"
        
        # Formatear responsables
        if responsables and len(responsables) > 0:
            if isinstance(responsables[0], dict):
                responsables_texto = ", ".join([
                    f"{r.get('nombre', '')} {r.get('apellido_paterno', '')}".strip()
                    for r in responsables
                ])
            else:
                responsables_texto = ", ".join(str(r) for r in responsables)
        else:
            responsables_texto = None
        
        # Formatear timestamp
        timestamp_str = notification.get('timestamp', 'N/A')
        if isinstance(timestamp_str, (int, float)):
            from datetime import datetime
            timestamp_str = datetime.fromtimestamp(timestamp_str).strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(timestamp_str, str) and len(timestamp_str) > 19:
            timestamp_str = timestamp_str[:19].replace('T', ' ')
        
        # ============================
        # CONSTRUIR MENSAJE DETALLADO
        # ============================
        respuesta = f"""⚠️ *Alerta de Documento* ⚠️
⏱️ Han pasado *15 días sin movimiento*.  
Por favor, revisa y actualiza su estado a *"Atendido"* si corresponde. 🙏

📄 *Documento:* {numero_documento}  
🆔 *Código sistema:* {codigo_sistema}  
📋 *Asunto:* {asunto}  
🏗️ *Proyecto:* {proyecto_nombre}  
👤 *Encargado:* {encargados_texto}  
🔄 *Estado:* {estado}  
📅 *Fecha Ingreso:* {fecha_ingreso}"""
        
        # Agregar días de inactividad si existe
        if dias_inactivo is not None:
            respuesta += f"\n⏱️ *Días inactivo:* {dias_inactivo} días"
        
        # Agregar sección de contacto
        respuesta += f"\n\n💡 *¿Quieres contactar?*  \n👤 *Encargado:* {encargados_texto}"
        
        if responsables_texto:
            respuesta += f"\n🏗️ *Responsable proyecto:* {responsables_texto}"
        
        respuesta += "\n\n💬 Responde *'contactar encargado'* para enviar mensaje"
        
        respuesta += f"\n\n────────────────────────\n⏰ *Recibida:* {timestamp_str}"
        
        # ============================
        # GUARDAR CONTEXTO PARA CONTACTO
        # ============================
        conversation_memory.add_turn(
            phone_number=numero_telefono,
            user_message=f"Ver notificación {parametro}",
            bot_response=respuesta,
            intent="notification_selected",
            parameters={
                "selected_notification": notification,
                "notification_index": parametro
            },
            context={
                "alert_active": True,
                "alert_payload": payload,
                "selected_notification_id": notification["id"],
                "document_number": numero_documento,
                "system_code": codigo_sistema,
                "encargados": encargados,
                "responsables": responsables
            },
            message_type="notification_detail",
            flow="detalle_notificacion"
        )
        
    
        conversation_memory.set_conversation_state(
            numero_telefono,
            "awaiting_notification_choice",
            {
                "notifications_available": True,
                "has_notification_list": True,
                "is_notification_flow": True,
                "last_viewed_notification": notification.get("id")
            }
        )
        
        return {
            "tipo": "notificacion_seleccionada",
            "respuesta": respuesta,
            "intent": "seleccionar_notificacion",
            "parameters": {"notification": notification}
        }
        
    except Exception as e:
        print(f"❌ Error procesando notificación seleccionada: {e}")
        import traceback
        traceback.print_exc()
        return {
            "tipo": "error",
            "respuesta": "❌ Error procesando la notificación seleccionada",
            "intent": "error",
            "parameters": {}
        }

def generar_mensaje_whatsapp(payload, tipo_contacto="encargado"):
    """Genera mensaje para WhatsApp - VERSIÓN MEJORADA CON SOPORTE PARA ENCARGADO Y RESPONSABLE"""
    print(f"Información del documento (tipo_contacto: {tipo_contacto}):", payload)
    
    # Inicializar variables
    celular = None
    nombre = None
    etiqueta_contacto = "encargado" if tipo_contacto == "encargado" else "responsable"
    
    # Para documentos de prueba del JSON
    try:
        if tipo_contacto == "responsable":
            # Buscar en responsables
            responsables = None
            
            # Intentar diferentes estructuras
            if 'documento' in payload:
                if 'notification' in payload['documento'] and 'payload' in payload['documento']['notification']:
                    responsables = payload['documento']['notification']['payload'].get('responsables')
                elif 'responsables' in payload['documento']:
                    responsables = payload['documento']['responsables']
            elif 'responsables' in payload:
                responsables = payload['responsables']
            
            if responsables and len(responsables) > 0:
                celular = responsables[0].get('celular', None)
                nombre = f"{responsables[0].get('nombre', '')} {responsables[0].get('apellido_paterno', '')}".strip()
                print(f"✅ Responsable encontrado: {nombre}, {celular}")
            else:
                raise KeyError("No hay responsables en la lista")
                
        else:
            # Buscar en encargados (comportamiento original)
            encargados = None
            
            # Intentar diferentes estructuras
            if 'documento' in payload:
                if 'notification' in payload['documento'] and 'payload' in payload['documento']['notification']:
                    encargados = payload['documento']['notification']['payload'].get('encargados')
                elif 'encargados' in payload['documento']:
                    encargados = payload['documento']['encargados']
            elif 'encargados' in payload:
                encargados = payload['encargados']
            
            if encargados and len(encargados) > 0:
                celular = encargados[0].get('celular', None)
                nombre = f"{encargados[0].get('nombres', '')} {encargados[0].get('apellido_paterno', '')}".strip()
                print(f"✅ Encargado encontrado: {nombre}, {celular}")
            else:
                raise KeyError("No hay encargados en la lista")

    except Exception as e:
        celular = "+51972453786"
        nombre = "Usuario de Prueba"
    
    try:
        documento_info = payload['documento']['notification']['payload']['documento']
    except Exception as e:
        print("❌ Error leyendo documento:", e)
        documento_info = {}

    numero_doc = documento_info.get('numero_documento', 'DOC-001')
    asunto = documento_info.get('asunto', 'Asunto no disponible')[:100]

    # ============================
    # 2. Extraer encargado
    # ============================
    try:
        encargado = payload['documento']['notification']['payload']['encargados'][0]
        nombre = f"{encargado.get('nombres','')} {encargado.get('apellido_paterno','')}".strip()
        celular = encargado.get('celular', None)
    except Exception as e:
        print("❌ Error leyendo encargado:", e)
        nombre = "Usuario"
        celular = None

    # ============================
    # 3. Construir mensaje
    # ============================
    mensaje = (
        f"Hola {nombre.split()[0]}, te contacto respecto al documento:"
        f"\n📄 {numero_doc}"
        f"\n📝 {asunto}..."
        f"\n\n¿Podrías brindarme una actualización? ¡Gracias!"
    )

    
    # Limpiar y formatear número
    celular_limpio = re.sub(r"[^0-9]", "", celular)
    if not celular_limpio.startswith('51'):
        celular_limpio = '51' + celular_limpio.lstrip('0')
    
    url_whatsapp = f"https://wa.me/{celular_limpio}?text={requests.utils.quote(mensaje)}"
    
    # Retornar diccionario con ambas claves para compatibilidad
    return {
        'mensaje': mensaje,
        'url_whatsapp': url_whatsapp,
        'encargado': nombre,  
        'responsable': nombre,  
        'celular': celular
    }

def manejar_contacto_encargado(numero_telefono, conv_context, tipo_contacto="encargado"):
    """Maneja el contacto con el encargado o responsable"""
    try:
        print(f"🔍 Buscando información de contacto ({tipo_contacto}) para {numero_telefono}")

        alert_payload = None
        documento_info = None

        # 1. BUSCAR EN TURNOS RECIENTES
        if hasattr(conversation_memory, 'conversations') and numero_telefono in conversation_memory.conversations:
            ultimos = conversation_memory.conversations[numero_telefono][-5:]
            for i, turno in enumerate(reversed(ultimos)):  # más reciente primero
                ctx = turno.context if isinstance(turno.context, dict) else {}
                print(f"  Turno -{i+1}: intent={turno.intent} | alert_active={ctx.get('alert_active')} | tiene_payload={bool(ctx.get('alert_payload'))}")

                # Alerta activa con payload
                if ctx.get('alert_active') and ctx.get('alert_payload'):
                    alert_payload = ctx.get('alert_payload')
                    print(f"✅ alert_payload encontrado en turno -{i+1}")
                    break

                # Turno de notificación seleccionada
                if turno.intent == 'notification_selected':
                    params = turno.parameters if isinstance(turno.parameters, dict) else {}
                    notification = params.get('selected_notification', {})
                    if notification:
                        alert_payload = notification.get('payload', {})
                        print(f"✅ payload extraído de notification_selected en turno -{i+1}")
                        break

                # Turno de seguimiento con info de documento
                if turno.intent in ['seleccionar_notificacion', 'seguimiento_por_codigo', 'seguimiento_por_numero_documento']:
                    params = turno.parameters if isinstance(turno.parameters, dict) else {}
                    if params:
                        documento_info = params
                        print(f"📄 documento_info encontrado en turno -{i+1}: {turno.intent}")
                        break

        # 2. BUSCAR EN DOCUMENTOS GUARDADOS
        if not alert_payload and not documento_info:
            print("🔍 Buscando en documentos guardados...")
            documentos_guardados = conversation_memory.get_conversation_documents(numero_telefono, limit=5)

            if documentos_guardados:
                for doc in documentos_guardados:
                    encargados = doc.get('encargados', [])
                    responsables = doc.get('responsables', [])
                    if encargados or responsables or doc.get('usuario_asignado'):
                        documento_info = doc
                        print(f"📚 Documento con contacto encontrado: {doc.get('codigo_sistema', 'N/A')}")
                        break

        # PROCESAR
        if alert_payload:
            print("✅ Procesando alert_payload")
            return procesar_alert_payload(alert_payload, numero_telefono, tipo_contacto)

        elif documento_info:
            print("✅ Procesando documento_info")
            return procesar_documento_info(documento_info, numero_telefono, tipo_contacto)

        else:
            print("❌ No se encontró información de contacto")
            return generar_respuesta_sin_info_contacto(conv_context, tipo_contacto)

    except Exception as e:
        print(f"❌ Error manejando contacto: {e}")
        import traceback
        traceback.print_exc()
        return "❌ Error interno al generar el contacto. Por favor, inténtalo de nuevo."
def procesar_documento_info(documento_info, numero_telefono, tipo_contacto="encargado"):
    """Procesa información de documento para generar contacto con formato WhatsApp"""
    try:
        print(f"📄 Iniciando procesamiento de documento_info (tipo: {tipo_contacto})...")
        print("🔍 documento_info recibido:", documento_info)

        # Inicializar variables
        contacto_nombre = None
        celular = None
        documento_id = None
        
        # Etiquetas según tipo de contacto
        etiqueta_contacto = "encargado" if tipo_contacto == "encargado" else "responsable"
        etiqueta_mayus = "Encargado" if tipo_contacto == "encargado" else "Responsable"

        if isinstance(documento_info, dict):
            print(f"✅ documento_info es un diccionario, buscando {etiqueta_contacto}...")
            
            # Buscar contacto según tipo
            try:
                if tipo_contacto == "responsable":
                    # Buscar responsable
                    if documento_info.get("responsables"):
                        resp = documento_info["responsables"]
                        print("👥 Lista de responsables:", resp)
                        if isinstance(resp, list) and len(resp) > 0:
                            print("➡️ Primer responsable dict:", resp[0])
                            contacto_nombre = f"{resp[0].get('nombre', '')} {resp[0].get('apellido_paterno', '')}".strip()
                            celular = resp[0].get("celular")
                            print("👤 Responsable detectado:", contacto_nombre)
                            print("📱 Celular detectado:", celular)
                    elif documento_info.get("responsable"):
                        contacto_nombre = documento_info["responsable"]
                        print("👤 Responsable encontrado:", contacto_nombre)
                else:
                    # Buscar encargado (comportamiento original)
                    if documento_info.get("usuario_asignado"):
                        contacto_nombre = documento_info["usuario_asignado"]
                        print("👤 Encontrado usuario_asignado:", contacto_nombre)
                    elif documento_info.get("encargados"):
                        enc = documento_info["encargados"]
                        print("👥 Lista de encargados:", enc)
                        if isinstance(enc, list) and len(enc) > 0:
                            print("➡️ Primer encargado dict:", enc[0])
                            contacto_nombre = f"{enc[0].get('nombres', '')} {enc[0].get('apellido_paterno', '')}".strip()
                            celular = enc[0].get("celular")
                            print("👤 Encargado detectado:", contacto_nombre)
                            print("📱 Celular detectado:", celular)
                    elif documento_info.get("encargado"):
                        contacto_nombre = documento_info["encargado"]
                        print("👤 Encargado encontrado:", contacto_nombre)
            except Exception as e:
                print(f"❌ Error buscando {etiqueta_contacto}:", e)

            # Buscar celular si aún no lo tienes
            try:
                if not celular:
                    celular = (
                        documento_info.get('celular') or 
                        documento_info.get('telefono') or
                        documento_info.get('phone')
                    )
                print("📱 Celular final:", celular)
            except Exception as e:
                print("❌ Error buscando celular:", e)

            # Buscar ID de documento
            try:
                documento_id = (
                    documento_info.get('codigo_sistema') or
                    documento_info.get('numero_documento') or
                    documento_info.get('document_id')
                )
                print("🆔 Documento ID detectado:", documento_id)
            except Exception as e:
                print("❌ Error buscando documento_id:", e)

            # ✅ Usar la función generar_mensaje_whatsapp para armar respuesta final
            try:
                # Empaquetar en payload con estructura mínima para generar mensaje
                payload = {"documento": documento_info}
                if tipo_contacto == "responsable" and documento_info.get("responsables"):
                    payload["responsables"] = documento_info["responsables"]
                elif documento_info.get("encargados"):
                    payload["encargados"] = documento_info["encargados"]

                info_whatsapp = generar_mensaje_whatsapp(payload, tipo_contacto)

                respuesta = f"""
✅ ¡Perfecto! Te ayudo a contactar al {etiqueta_contacto}.

👤 *{etiqueta_mayus}: {info_whatsapp[etiqueta_contacto]}*
📱 {info_whatsapp['celular']}

🔗 *Link directo de WhatsApp:*
{info_whatsapp['url_whatsapp']}

📝 *Mensaje sugerido ya incluido:*
"{info_whatsapp['mensaje']}"

💡 Solo haz clic en el link y se abrirá WhatsApp con el mensaje listo para enviar.
"""
                print("🤖 Respuesta generada:\n", respuesta)

                # Registrar en la memoria de conversación
                try:
                    context_info = {
                        "contact_generated": True,
                        "contact_type": tipo_contacto,
                        "contact_sent_to": info_whatsapp[etiqueta_contacto],
                        "contact_phone": info_whatsapp['celular'],
                        "document_id": documento_id
                    }
                    print("📝 Context info a registrar:", context_info)

                    conversation_memory.add_turn(
                        phone_number=numero_telefono,
                        user_message=f"[CONTACTO_INFO_DOCUMENTO_{tipo_contacto.upper()}]",
                        bot_response=respuesta,
                        intent=f"contactar_{etiqueta_contacto}",
                        parameters={etiqueta_contacto: info_whatsapp[etiqueta_contacto], "document_id": documento_id},
                        context=context_info,
                        flow="contacto"
                    )
                    print("💾 Turno registrado en conversation_memory")
                except Exception as e:
                    print("❌ Error registrando en conversation_memory:", e)

                return respuesta

            except Exception as e:
                print("❌ Error generando mensaje WhatsApp:", e)
                return f"❌ No pude generar el mensaje de WhatsApp para el {etiqueta_contacto}."

        else:
            print("❌ documento_info no es un diccionario")
            return f"❌ No encontré información del {etiqueta_contacto} en este documento."

    except Exception as e:
        print(f"❌ Error procesando documento_info (nivel general): {e}")
        return "❌ Error procesando información del documento."


def procesar_alert_payload(alert_payload, numero_telefono, tipo_contacto="encargado"):
    """Procesa alert_payload para generar contacto"""
    try:
        # Convertir de string a dict si es necesario
        if isinstance(alert_payload, str):
            try:
                alert_payload = json.loads(alert_payload)
            except Exception as e:
                print("❌ Error convirtiendo alert_payload:", e)
                return "❌ El formato de la alerta no es válido."

        # Etiquetas según tipo de contacto
        etiqueta_contacto = "encargado" if tipo_contacto == "encargado" else "responsable"
        etiqueta_mayus = "Encargado" if tipo_contacto == "encargado" else "Responsable"

        # Generar mensaje de WhatsApp
        info_whatsapp = generar_mensaje_whatsapp(alert_payload, tipo_contacto)
                
        if info_whatsapp:
            respuesta = f"""
✅ ¡Perfecto! Te ayudo a contactar al {etiqueta_contacto}.

👤 *{etiqueta_mayus}: {info_whatsapp[etiqueta_contacto]}*
📱 {info_whatsapp['celular']}

🔗 *Link directo de WhatsApp:*
{info_whatsapp['url_whatsapp']}

📝 *Mensaje sugerido ya incluido:*
"{info_whatsapp['mensaje']}"

💡 Solo haz clic en el link y se abrirá WhatsApp con el mensaje listo para enviar.
"""
            
            # Registrar el contacto generado
            context_info = {
                "contact_generated": True,
                "contact_type": tipo_contacto,
                "contact_sent_to": info_whatsapp[etiqueta_contacto],
                "contact_phone": info_whatsapp['celular']
            }
            
            conversation_memory.add_turn(
                phone_number=numero_telefono,
                user_message=f"[CONTACTO_SOLICITADO_{tipo_contacto.upper()}]",
                bot_response=respuesta,
                intent=f"contactar_{etiqueta_contacto}",
                parameters={etiqueta_contacto: info_whatsapp[etiqueta_contacto]},
                context=context_info,
                flow="contacto"
            )
            
            return respuesta
        else:
            return f"❌ No pude generar la información de contacto del {etiqueta_contacto}. Inténtalo nuevamente."
    
    except Exception as e:
        print(f"❌ Error procesando alert_payload: {e}")
        return "❌ Error procesando información de contacto."


def generar_respuesta_sin_info_contacto(conv_context, tipo_contacto="encargado"):
    """Genera respuesta cuando no hay información de contacto disponible"""
    etiqueta_contacto = "encargado" if tipo_contacto == "encargado" else "responsable"
    
    return f"""
❌ No encontré información del {etiqueta_contacto} para este documento.

💡 *Opciones:*
- Realiza primero una búsqueda del documento
- Selecciona un documento de tus notificaciones
- Proporciona el código del documento

Luego podrás solicitar el contacto del {etiqueta_contacto}.
"""
# ========================= FUNCIONES DE WHATSAPP =========================
def enviar_mensaje_whatsapp(numero_telefono, mensaje):
    try:
        # Validar que el mensaje no esté vacío
        if not mensaje or mensaje.strip() == "":
            print(f"⚠️ Mensaje vacío, no se enviará a {numero_telefono}")
            return False
            
        headers = {
            'Authorization': f'Bearer {WHATSAPP_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        # Truncar mensaje si es muy largo (WhatsApp tiene límites)
        mensaje_truncado = mensaje[:4000] if len(mensaje) > 4000 else mensaje
        if len(mensaje) > 4000:
            mensaje_truncado += "\n\n📝 *Mensaje truncado por longitud*"
        
        data = {
            'messaging_product': 'whatsapp',
            'to': numero_telefono,
            'type': 'text',
            'text': {
                'body': mensaje_truncado
            }
        }
        
        response = requests.post(WHATSAPP_API_URL, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            print(f"✅ Mensaje enviado a {numero_telefono}")
            return True
        else:
            print(f"❌ Error enviando mensaje: {response.status_code} - {response.text}")
            return False
                  
    except requests.exceptions.Timeout:
        print(f"⏰ Timeout enviando mensaje a {numero_telefono}")
        return False
    except requests.exceptions.ConnectionError:
        print(f"🔌 Error de conexión enviando a {numero_telefono}")
        return False
    except Exception as e:
        print(f"❌ Error inesperado en envío WhatsApp: {e}")
        return False
    
def numero_autorizado(numero_telefono):
    """Verifica si el número está autorizado en la base de datos"""
    # Limpiar número (quitar prefijo internacional y caracteres especiales)
    numero_limpio = re.sub(r'[^0-9]', '', numero_telefono)
    
    # Si tiene código de país Perú (51), quitarlo para comparar
    if numero_limpio.startswith('51'):
        numero_limpio = numero_limpio[2:]
    
    query = """
        SELECT id, nombres, apellido_paterno, nivel_acceso
        FROM usuarios 
        WHERE celular LIKE %s 
        LIMIT 1
    """
    
    # Buscar el número
    parametro_busqueda = f"%{numero_limpio}%"
    resultado = ejecutar_query(query, (parametro_busqueda,))
    
    if resultado and len(resultado) > 0:
        return resultado[0]  
    return None





def respuesta_saludo_contextual(conversation_context):
    """Genera saludo personalizado basado en contexto"""
    if conversation_context.get("session_length", 0) > 0:
        if conversation_context.get("recent_documents"):
            return (
                f"👋 ¡Hola de nuevo! Veo que consultaste recientemente: "
                f"*{', '.join(conversation_context['recent_documents'][:2])}*\n\n"
                f"¿En qué más puedo ayudarte?\n\n{SUGERENCIAS_BUSQUEDA}"
            )
        elif conversation_context.get("recent_projects"):
            return (
                f"👋 ¡Hola de nuevo! Consultaste sobre el proyecto: "
                f"*{conversation_context['recent_projects'][0]}*\n\n"
                f"¿Necesitas algo más?\n\n{SUGERENCIAS_BUSQUEDA}"
            )
        else:
            return f"👋 ¡Hola de nuevo! ¿En qué más puedo ayudarte?\n\n{SUGERENCIAS_BUSQUEDA}"
    else:
        return respuesta_saludo()


def buscar_en_documentos_guardados(documentos_guardados, parametro, intent_type):
    """Busca en documentos previamente guardados según el intent"""
    resultados = []
    parametro_lower = parametro.lower()
    
    for doc in documentos_guardados:
        match = False
        
        # Buscar según tipo de intent
        if intent_type == "seguimiento_por_numero_documento":
            if parametro_lower in doc.get("numero_documento", "").lower():
                match = True
        elif intent_type == "seguimiento_por_codigo":
            if parametro_lower in doc.get("codigo_sistema", "").lower():
                match = True
        elif intent_type == "seguimiento_por_proyecto":
            if parametro_lower in doc.get("proyecto_nombre", "").lower():
                match = True
        elif intent_type == "seguimiento_por_asunto":
            if parametro_lower in doc.get("asunto", "").lower():
                match = True
        elif intent_type == "seguimiento_por_usuario":
            encargados = doc.get("encargados", "")
            responsable = doc.get("responsable_proyecto", "")
            if parametro_lower in encargados.lower() or parametro_lower in responsable.lower():
                match = True
        elif intent_type == "seguimiento_por_consecutivo":
            if parametro_lower in doc.get("numero_consecutivo", "").lower():
                match = True
        
        if match:
            resultados.append(doc)
    
    return resultados if resultados else None


def formatear_documento_detalle(documento):
    """Formatea un documento individual con todos sus detalles"""
    return f"""📄 **Documento Encontrado:**

• **Código:** {documento.get('codigo_sistema', 'N/A')}
• **Tipo:** {documento.get('tipo', 'N/A')}
• **Número:** {documento.get('numero_documento', 'N/A')}
• **Asunto:** {documento.get('asunto', 'N/A')}
• **Estado:** {documento.get('estado_flujo', 'N/A')}
• **Prioridad:** {documento.get('prioridad_nombre', 'N/A')}
• **Proyecto:** {documento.get('proyecto_nombre', 'N/A')}
• **Responsable:** {documento.get('responsable_proyecto', 'No asignado')}
• **Encargados:** {documento.get('encargados', 'No asignado')}
• **Fecha ingreso:** {documento.get('fecha_ingreso', 'No definida')}
• **Fecha límite:** {documento.get('fecha_limite', 'No definida')}"""


def formatear_lista_documentos(seguimientos):
    """
    Formatea lista DETALLADA de documentos para notificaciones de WhatsApp
    Muestra: número, código, tipo, asunto, proyecto, encargado, fecha
    Estilo similar al formato consolidado de email
    """
    if not seguimientos:
        return "❌ No se encontraron documentos."
    
    if not isinstance(seguimientos, list):
        return "⚠️ Error: formato de datos inválido."
    
    cantidad = len(seguimientos)
    mensaje = ""
    
    # Limitar a 10 documentos para legibilidad en WhatsApp
    documentos_a_mostrar = seguimientos[:100]
    
    for idx, seg in enumerate(documentos_a_mostrar, 1):
        # Extraer documento según estructura
        if isinstance(seg, dict):
            doc = seg.get('documento', seg)
            proyecto_data = seg.get('proyecto', {})
            encargados = seg.get('encargados', [])
            
            # Extraer campos del documento
            codigo = doc.get('codigo_sistema', 'N/A')
            tipo = doc.get('tipo', 'N/A')
            numero_doc = doc.get('numero_documento', 'N/A')
            asunto = doc.get('asunto', 'Sin asunto')
            dias_inactivo = doc.get('dias_inactivo')
            fecha_ingreso = doc.get('fecha_ingreso', '')
            estado = doc.get('estado', '')

            
            # Extraer nombre del proyecto
            if isinstance(proyecto_data, dict):
                proyecto = proyecto_data.get('nombre', 'N/A')
            elif isinstance(proyecto_data, str):
                proyecto = proyecto_data
            else:
                proyecto = 'N/A'
            
            # Obtener nombre del encargado
            encargado_nombre = 'Sin asignar'
            if encargados and len(encargados) > 0:
                enc = encargados[0]
                encargado_nombre = f"{enc.get('nombres', '')} {enc.get('apellido_paterno', '')}".strip()
            
            # Formatear fecha de ingreso
            if fecha_ingreso:
                try:
                    from datetime import datetime
                    fecha_obj = datetime.strptime(fecha_ingreso[:10], '%Y-%m-%d')
                    fecha_ingreso = fecha_obj.strftime('%d/%m/%Y')
                except:
                    fecha_ingreso = fecha_ingreso[:10] if len(fecha_ingreso) >= 10 else fecha_ingreso
            
            # Truncar asunto si es muy largo
            if len(asunto) > 70:
                asunto = asunto[:67] + "..."
            
            # Formato detallado
            mensaje += f"*{idx}. {numero_doc}*\n"
            
            if asunto and asunto != 'Sin asunto':
                mensaje += f"   📄 {asunto}\n"
            
            if proyecto and proyecto != 'N/A':
                mensaje += f"   🏗️ {proyecto}\n"
            
            mensaje += f"   👤 En atención de: {encargado_nombre}\n"
            
            if fecha_ingreso:
                mensaje += f"   📅 Ingreso: {fecha_ingreso}\n"
            
            if estado:
                mensaje += f"   📌 Estado: {estado}\n"

            # Agregar días de inactividad si existe
            if dias_inactivo is not None:
                mensaje += f"   ⏱️ Inactivo: {dias_inactivo} días\n"
            
            mensaje += "\n"
    
    # Indicar si hay más documentos
    if cantidad > 10:
        mensaje += f"_... y {cantidad - 10} documento(s) más_\n\n"
    
    mensaje += f"_Total: {cantidad} documento{'s' if cantidad != 1 else ''}_"
    
    return mensaje



def limpiar_notificaciones_antiguas():
    """Limpia notificaciones más antiguas de 1 hora"""
    try:
        current_time = datetime.now()
        for numero_telefono in list(notification_manager.pending_notifications.keys()):
            notifications = notification_manager.pending_notifications[numero_telefono]
            # Filtrar notificaciones más nuevas de 1 hora
            fresh_notifications = [
                n for n in notifications 
                if current_time - n['timestamp'] < timedelta(hours=1)
            ]
            
            if len(fresh_notifications) != len(notifications):
                print(f"🧹 Limpiadas {len(notifications) - len(fresh_notifications)} notificaciones antiguas para {numero_telefono}")
                if fresh_notifications:
                    notification_manager.pending_notifications[numero_telefono] = fresh_notifications
                else:
                    del notification_manager.pending_notifications[numero_telefono]
                    
    except Exception as e:
        print(f"❌ Error limpiando notificaciones antiguas: {e}")

