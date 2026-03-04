# app.py 

from flask import Flask, request, jsonify
from services.chatbot_service import *
from services.algolia_service import *
from services.ia_service import *
from core.constants import *
from core.flow import *
from utils.formatter import *
from services.notificacion_services import *
from collections import defaultdict
from services.notificacion_services import (
    notification_manager
)
import threading

import os
import json
import requests
from typing import List, Dict, Union, Optional
app = Flask(__name__)


@app.route('/whatsapp/webhook', methods=['GET', 'POST'])
def whatsapp_webhook():
    """Webhook para WhatsApp Business API - CON SOPORTE PARA PLANTILLAS Y BOTONES POR TIPO"""
    if request.method == 'GET':
        # Verificación del webhook
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if token == WHATSAPP_VERIFY_TOKEN:
            print("✅ Webhook verificado correctamente")
            return challenge
        else:
            print("❌ Token de verificación inválido")
            return 'Token de verificación inválido', 403
        
    elif request.method == 'POST':
        # Procesar mensaje entrante
        try:
            data = request.get_json()
            
            # Verificar si hay mensajes entrantes
            if not (data.get('entry') and len(data['entry']) > 0 
                    and data['entry'][0].get('changes') 
                    and len(data['entry'][0]['changes']) > 0):
                return jsonify({'status': 'no_messages'}), 200
            
            changes = data['entry'][0]['changes'][0]
            value = changes.get('value', {})
            
            # MANEJAR RESPUESTAS DE BOTÓN Y TEXTO
            if 'messages' in value:
                message = value['messages'][0]
                numero_telefono = message['from']
                tipo = message.get('type')

                # Extraer payload del botón o texto del mensaje
                button_payload = ''
                message_text = ''

                if tipo == 'button':
                    button_payload = message.get('button', {}).get('payload', '')
                    message_text = message.get('button', {}).get('text', '').lower().strip()
                elif tipo == 'text':
                    message_text = message.get('text', {}).get('body', '').lower().strip()

      
                
                # Verificar autorización
                usuario = numero_autorizado(numero_telefono)
                if not usuario:
                    if "chatbot" not in message_text:
                        mensaje_contacto = (
                            "👋 *¡Hola!*\n\n"
                            "Este es el chatbot de ProRequest. "
                            "Actualmente no estás registrado en nuestro sistema.\n\n"
                            "📞 *Para agregar tus datos:*\n"
                            "Comunicarse con la administración\n"
                            "👤 *Juan David*\n"
                            "📱 +51 957 133 488"
                        )
                        enviar_mensaje_whatsapp(numero_telefono, mensaje_contacto)
                    return jsonify({'status': 'unauthorized'}), 403

                # MAPEO DE TIPOS DE REVISIÓN (botones y texto)
                TIPOS_REVISION = {
                    # Payloads de botones
                    "revisar_sin_respuesta": "sin_respuesta",
                    "revisar_sin_firma": "sin_firma",
                    "revisar_inactivos": "inactivos",
                    "revisar_stand_by": "stand_by",
                    # Textos equivalentes - PLURAL
                    "revisar sin respuesta": "sin_respuesta",
                    "sin respuesta": "sin_respuesta",
                    "revisar sin firma": "sin_firma",
                    "sin firma": "sin_firma",
                    "revisar inactivos": "inactivos",
                    "inactivos": "inactivos",
                    "revisar stand by": "stand_by",
                    "stand by": "stand_by",
                    "revisar sin respuesta": "sin_respuesta",  
                    "revisar sin firma": "sin_firma",  
                    "revisar inactivo": "inactivos",  
                    "inactivo": "inactivos",  
                    "revisar stand by": "stand_by"  
                }

                # Detectar tipo de revisión solicitada
                tipo_revision = None
                
                # Priorizar payload del botón
                if button_payload in TIPOS_REVISION:
                    tipo_revision = TIPOS_REVISION[button_payload]
                # Buscar en texto
                elif message_text in TIPOS_REVISION:
                    tipo_revision = TIPOS_REVISION[message_text]

                if tipo_revision:
                    print(f"🔍 Revisión solicitada para tipo: {tipo_revision}")
                    
                    # Obtener notificaciones de ese tipo específico
                    notifications = notification_manager.get_notifications_by_type(
                        numero_telefono, 
                        tipo_revision
                    )
                    
              
                    
                    # Si hay una sola notificación, mostrar documentos directamente
                    if len(notifications) > 0:
                        notification = notifications[0]
                        documentos = notification.get('documentos', [])
                        
                        print(f"📄 Mostrando lista de {len(documentos)} documentos tipo {tipo_revision}")
                        
                        #  USAR formatear_lista_documentos
                        respuesta = formatear_lista_documentos(documentos)
                        
                        enviar_mensaje_whatsapp(numero_telefono, respuesta)
                        
                        # Guardar documentos en memoria con tipo específico
                        conversation_memory.set_conversation_documents(
                            phone_number=numero_telefono,
                            documents=documentos,
                            source_intent=f"notificacion_{tipo_revision}",
                            source_query=f"Revisión: {tipo_revision}"
                        )
                        
                        # Cambiar estado a awaiting_notification_choice
                        conversation_memory.set_conversation_state(
                            phone_number=numero_telefono,
                            state="awaiting_notification_choice",
                            additional_info={
                                "has_document_list": True,
                                "last_search_results_count": len(documentos),
                                "notification_id": notification.get('id'),
                                "pending_notifications_count": len(notifications),
                                "notification_type": tipo_revision
                            }
                        )
                        
                        # Enviar pregunta de elección
                        pregunta = "¿En cuál de los documentos requieres información?\n\n" \
                                 "💡 Escribe el número del documento o describe cuál buscas.\n" \
                                 "Si quieres iniciar una nueva búsqueda, escribe 'Hola'"
                        enviar_mensaje_whatsapp(numero_telefono, pregunta)
                        
                        # Marcar notificación como vista
                        notification_manager.mark_notification_as_viewed(
                            numero_telefono, 
                            notification['id']
                        )
                        
                    else:
                        # Múltiples notificaciones del mismo tipo - mostrar grupos
                        respuesta = notification_manager.get_notifications_by_type(
                            numero_telefono, 
                            tipo_revision
                        )
                        enviar_mensaje_whatsapp(numero_telefono, respuesta)
                        
                        # Cambiar estado a awaiting_notification_choice
                        conversation_memory.set_conversation_state(
                            phone_number=numero_telefono,
                            state="awaiting_notification_choice",
                            additional_info={
                                "pending_notifications_count": len(notifications),
                                "notification_type": tipo_revision
                            }
                        )
                    
                    return jsonify({'status': 'success'}), 200

                
                #  SI NO ES REVISIÓN, PROCESAR COMO MENSAJE NORMAL
                if tipo == 'text':
                    texto_mensaje = message_text
                    print(f"📱 Mensaje de texto recibido: {texto_mensaje}")
                    
                    # 🧠 Establecer rol del usuario en memoria
                    conversation_memory.set_user_role(numero_telefono, usuario["nivel_acceso"])
                    
                    # 🧠 Obtener estado actual ANTES de procesar
                    conversation_state = conversation_memory.get_conversation_state(numero_telefono)
                    conv_context = conversation_memory.get_conversation_context(numero_telefono)
                    
                    print(f"🧠 Estado conversación: {conversation_state['state']}")
                    print(f"🧠 Contexto: {conv_context['session_length']} turnos")
                    print(f"🔍 Debe buscar BD completa: {conversation_state['should_search_full_db']}")
                    
                    # 🔄 Procesar mensaje con estados
                    print("🔄 Procesando mensaje...")
                    
                    # Forzar intent de búsqueda si contiene palabra clave
                    PALABRAS_BUSQUEDA = ["buscar", "busqueda", "búsqueda", "search", "uscar"]
                    intent_forzado = None
                    
                    texto_lower = texto_mensaje.lower()
                    if any(palabra in texto_lower for palabra in PALABRAS_BUSQUEDA):
                        intent_forzado = "buscar_documentos"
                    
                    respuesta_completa = procesar_mensaje(
                        texto_mensaje,
                        numero_telefono,
                        conversation_state=conversation_state,
                        conversation_context=conv_context,
                        intent_forzado=intent_forzado
                    )
                    
                    print("🔍 RESPUESTA ANTES DE WHATSAPP:", respuesta_completa)
                    
                    # Extraer respuesta y tipo
                    if isinstance(respuesta_completa, dict):
                        respuesta = respuesta_completa.get("respuesta")
                        tipo_resp = respuesta_completa.get("tipo")
                        intent = respuesta_completa.get("intent", "unknown")
                        parameters = respuesta_completa.get("parameters", {})
                    else:
                        respuesta = str(respuesta_completa)
                        tipo_resp = "consulta"
                        intent = "general"
                        parameters = {}
                    
                    # Actualizar flow según tipo
                    if tipo_resp == 'detalle':
                        conversation_memory.is_in_flow(numero_telefono, 'busqueda_general')
                    elif tipo_resp == 'lista':
                        conversation_memory.is_in_flow(numero_telefono, 'busqueda_en_lista')
                    
                    print("🪵 DEBUG - Respuesta procesada:")
                    print(f"   • Tipo   : {tipo_resp}")
                    print(f"   • Intent : {intent}")
                    print(f"   • Longitud: {len(str(respuesta)) if respuesta else 0} caracteres")
                    
                    # 🔄 Manejo especial para respuestas dict
                    if isinstance(respuesta, dict):
                        print(f"   • Keys   : {list(respuesta.keys())}")
                        if 'contenido' in respuesta:
                            respuesta = respuesta['contenido']
                        elif 'message' in respuesta:
                            respuesta = respuesta['message']
                        else:
                            respuesta = str(respuesta)
                    
                    # 🧠 DETERMINAR message_type
                    message_type = "consulta"  # Default
                    
                    if tipo_resp == 'detalle' or tipo_resp == 'select_document':
                        message_type = "verificacion"
                    elif tipo_resp == 'lista':
                        message_type = "eleccion"
                        if 'resultados' in respuesta_completa:
                            parameters["results_count"] = len(respuesta_completa['resultados'])
                    elif intent in ["contactar_encargado","contactar_responsable", "algolia_search"]:
                        message_type = "consulta"
                    elif intent == "confirmar_seleccion":
                        message_type = "confirmacion"
                    
                    print(f"📝 Message type determinado: {message_type}")
                    
                    # Enviar respuesta principal
                    if respuesta:
                        exito_envio = enviar_mensaje_whatsapp(numero_telefono, respuesta)
                        current_flow = conversation_memory.get_current_flow(numero_telefono)
                        print(f"FLOW ACTUAL: {current_flow}")
                        
                        if exito_envio:
                            print(f"✅ Respuesta enviada correctamente a {numero_telefono}")
                            
                            # 🧠 GUARDAR TURNO EN MEMORIA
                            conversation_memory.add_turn(
                                phone_number=numero_telefono,
                                user_message=texto_mensaje,
                                bot_response=respuesta,
                                intent=intent,
                                parameters=parameters,
                                context=conv_context,
                                message_type=message_type
                            )
                            
                            # 🧠 GUARDAR DOCUMENTOS SI EXISTEN
                            if 'resultados' in respuesta_completa or intent == "confirmar_seleccion":
                                success = conversation_memory.set_conversation_documents(
                                    phone_number=numero_telefono,
                                    documents=respuesta_completa['resultados'],
                                    source_intent=intent,
                                    source_query=texto_mensaje
                                )
                                
                                if success:
                                    print(f"📚 {len(respuesta_completa['resultados'])} documentos guardados en memoria")
                            
                            # 🧠 MANEJO DE PREGUNTAS DE CONFIRMACIÓN
                            if message_type == "eleccion":
                                pregunta_confirmacion = "¿En cuál de los documentos requieres información?\n\n" \
                                                      "Si quieres iniciar una nueva búsqueda, escribe 'Hola'"
                                print(f"❓ Enviando pregunta de elección: {pregunta_confirmacion}")
                                enviar_mensaje_whatsapp(numero_telefono, pregunta_confirmacion)
                                
                                conversation_memory.add_turn(
                                    phone_number=numero_telefono,
                                    user_message="[system] choice_question",
                                    bot_response=pregunta_confirmacion,
                                    intent="system_confirmation",
                                    parameters={"confirmation_type": "choice"},
                                    context={"awaiting_user_response": True},
                                    message_type="system_question"
                                )
                            
                            elif message_type == "verificacion":
                                pregunta_confirmacion = "¿El documento es lo que estabas buscando?"
                                print(f"❓ Enviando pregunta de verificación: {pregunta_confirmacion}")
                                enviar_mensaje_whatsapp(numero_telefono, pregunta_confirmacion)
                                
                                conversation_memory.add_turn(
                                    phone_number=numero_telefono,
                                    user_message="[system] verification_question",
                                    bot_response=pregunta_confirmacion,
                                    intent="system_confirmation",
                                    parameters={"confirmation_type": "verification"},
                                    context={"awaiting_user_response": True},
                                    message_type="system_question"
                                )
                            
                            elif intent == "confirmar_seleccion":
                                params = parameters or {}
                                confirmacion_positiva = params.get("confirmacion_positiva", False)
                                
                                if confirmacion_positiva:
                                    estado_anterior = conversation_state.get('state')
                                    
                                    if estado_anterior == "awaiting_choice":
                                        seguimiento_msg = "Perfecto! Ahora puedes hacer consultas específicas sobre estos documentos. ¿En qué más te puedo ayudar?"
                                        enviar_mensaje_whatsapp(numero_telefono, seguimiento_msg)
                                        print("✅ Modo búsqueda filtrada activado por confirmación positiva de elección")
                                    
                                    elif estado_anterior == "awaiting_verification":
                                        if current_flow in ['busqueda_en_lista', 'lista']:
                                            conversation_memory.set_awaiting_choice_search_mode(numero_telefono)
                                        seguimiento_msg = "¡Perfecto! ¿Necesitas ayuda con algo más? Puedes escribir 'hola' para empezar de nuevo."
                                        enviar_mensaje_whatsapp(numero_telefono, seguimiento_msg)
                                        print("✅ Verificación confirmada")
                                
                                else:
                                    estado_anterior = conversation_state.get('state')
                                    
                                    if estado_anterior == "awaiting_verification":
                                        if current_flow in ['busqueda_en_lista', 'lista']:
                                            conversation_memory.set_awaiting_choice_search_mode(numero_telefono)
                                        print("❌ Usuario rechazó verificación, pero MANTIENE búsqueda filtrada")
                        
                        else:
                            print(f"❌ Error enviando respuesta a {numero_telefono}")
                    else:
                        print("⚠️ No se generó respuesta para enviar")
            
            return jsonify({'status': 'success'}), 200
            
        except Exception as e:
            print(f"❌ Error procesando webhook WhatsApp: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'status': 'error', 'message': str(e)}), 500



def enviar_plantilla_whatsapp(numero: str, nombre_plantilla: str, parametros: List[str], idioma: str = "es_PE", tiene_boton: bool = True):
    """
    Envía una plantilla de WhatsApp Business aprobada
    
    Args:
        numero: Número de teléfono destino (con código país)
        nombre_plantilla: Nombre de la plantilla aprobada en Meta
        parametros: Lista de valores para reemplazar en {{1}}, {{2}}, etc.
        idioma: Código de idioma (es_PE para Español - Perú)
        tiene_boton: Si la plantilla tiene botón interactivo
    
    Returns:
        Dict con status y message_id
    """
    import requests
    from config import WHATSAPP_TOKEN, WHATSAPP_PHONE_ID
    
    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Construir componentes de parámetros
    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(param)} for param in parametros
            ]
        }
    ]
    
    # Solo agregar componente de botón si la plantilla lo tiene
    if tiene_boton:
        components.append({
            "type": "button",
            "sub_type": "quick_reply",
            "index": "0",
            "parameters": [
                {
                    "type": "payload",
                    "payload": "revisar_notificaciones"
                }
            ]
        })
    
    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "template",
        "template": {
            "name": nombre_plantilla,
            "language": {
                "code": idioma
            },
            "components": components
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            message_id = result.get('messages', [{}])[0].get('id')
            
            print(f"✅ Plantilla enviada: {nombre_plantilla} a {numero}")
            print(f"📧 Message ID: {message_id}")
            
            return {
                "status": "success",
                "message_id": message_id,
                "template": nombre_plantilla
            }
        else:
            error_data = response.json()
            error_msg = error_data.get('error', {}).get('message', 'Error desconocido')
            error_details = error_data.get('error', {})
            
            print(f"❌ Error enviando plantilla: {response.status_code}")
            print(f"   Mensaje: {error_msg}")
            print(f"   Detalles completos: {error_details}")
            
            return {
                "status": "error",
                "message": error_msg,
                "code": response.status_code,
                "details": error_details
            }
            
    except Exception as e:
        print(f"❌ Excepción enviando plantilla: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e)
        }


@app.route('/api/notificacion', methods=['POST'])
def recibir_notificacion():
    """
    Endpoint MEJORADO que agrupa notificaciones y envía plantilla única de WhatsApp
    Soporta: documentos_inactivos_masivo, documentos_en_stand_by_masivo, 
             documentos_en_firma_masivo, documentos_antiguos_masivo
    """
    try:
        data = request.get_json()
        
        tipo = data.get('tipo')
        cantidad = data.get('cantidad', 0)
        documentos = data.get('documentos', [])
        
        if not documentos:
            return jsonify({"error": "No hay documentos en el payload"}), 400
        

        plantillas_config = {
            'documentos_inactivos_masivo': {
                'nombre': 'alerta_documentos_inactivos',
                'descripcion': 'documentos sin gestión por más de 15 días'
            },
            'documentos_en_stand_by_masivo': {
                'nombre': 'documentos_stand_by',
                'descripcion': 'documentos en stand by'
            },
            'documentos_en_firma_masivo': {
                'nombre': 'documento_sin_firma',
                'descripcion': 'documentos con firma pendiente por más de 3 días'
            },
            'documentos_antiguos_masivo': {
                'nombre': 'documento_sin_respuesta',
                'descripcion': 'documentos sin respuesta por más de 30 días'
            }
        }

        
        #  AGRUPAR DOCUMENTOS POR DESTINATARIO
        documentos_por_usuario = defaultdict(list)
        
        for doc_data in documentos:
            destinatarios = doc_data.get('destinatarios', [])
            
            for telefono in destinatarios:
                telefono_normalizado = normalizar_numero_whatsapp(telefono)
                usuario_info = numero_autorizado(telefono_normalizado)
                if usuario_info:
                    documentos_por_usuario[telefono_normalizado].append(doc_data)
                else:
                    print(f"⚠️ Número no autorizado: {telefono_normalizado}")
        
        
        #  ENVIAR NOTIFICACIÓN AGRUPADA A CADA USUARIO
        resultados = {
            'exitosos': 0,
            'fallidos': 0,
            'detalles': []
        }
        
        for telefono, docs_usuario in documentos_por_usuario.items():
            try:
                usuario_info = numero_autorizado(telefono)
                nombre_usuario = usuario_info.get('nombres', 'Usuario') if usuario_info else 'Usuario'
                cantidad_docs = len(docs_usuario)
                
                print(f"📱 Procesando notificación para {telefono} ({cantidad_docs} docs)")
                
                #  ALMACENAR NOTIFICACIONES EN MEMORIA
                notification_data = {
                    "tipo": tipo,
                    "cantidad": cantidad_docs,
                    "documentos": docs_usuario
                }
                
                notification_group = notification_manager.store_notifications(
                    phone_number=telefono,
                    notifications_data=notification_data
                )
                
                if not notification_group:
                    raise Exception("Error almacenando notificaciones")
                
                
                # Verificar si el tipo está soportado
                if tipo not in plantillas_config:
                    print(f"⚠️ Tipo de notificación no soportado: {tipo}")
                    resultados['fallidos'] += 1
                    resultados['detalles'].append({
                        'telefono': telefono,
                        'status': 'error',
                        'error': f'Tipo no soportado: {tipo}'
                    })
                    continue
                
                #  ENVIAR PLANTILLA DE WHATSAPP
                config = plantillas_config[tipo]
                
          
                parametros = [
                    str(cantidad_docs),  # {{1}} - cantidad en título
                    nombre_usuario,      # {{2}} - nombre del usuario
                    str(cantidad_docs)   # {{3}} - cantidad en cuerpo
                ]
                
                # Enviar plantilla de WhatsApp Business
                resultado = enviar_plantilla_whatsapp(
                    numero=telefono,
                    nombre_plantilla=config['nombre'],
                    parametros=parametros,
                    idioma="es_PE"
                )
                
                if resultado.get('status') == 'success':
                    # Guardar el message_id de la plantilla
                    notification_manager.template_message_ids[notification_group['id']] = resultado.get('message_id')
                    
                    resultados['exitosos'] += 1
                    resultados['detalles'].append({
                        'telefono': telefono,
                        'documentos': cantidad_docs,
                        'status': 'success',
                        'tipo': tipo,
                        'plantilla': config['nombre'],
                        'notification_id': notification_group['id'],
                        'message_id': resultado.get('message_id')
                    })
                    print(f"✅ Plantilla '{config['nombre']}' enviada correctamente a {telefono}")
                else:
                    resultados['fallidos'] += 1
                    resultados['detalles'].append({
                        'telefono': telefono,
                        'documentos': cantidad_docs,
                        'status': 'error',
                        'tipo': tipo,
                        'plantilla': config['nombre'],
                        'error': resultado.get('message', 'Error desconocido')
                    })
                    print(f"❌ Error enviando plantilla '{config['nombre']}' a {telefono}: {resultado.get('message')}")
 
            except Exception as e:
                print(f"❌ Error procesando usuario {telefono}: {e}")
                import traceback
                traceback.print_exc()
                
                resultados['fallidos'] += 1
                resultados['detalles'].append({
                    'telefono': telefono,
                    'status': 'error',
                    'error': str(e)
                })
        
        return jsonify({
            'status': 'success',
            'message': f'Procesadas {resultados["exitosos"]} notificaciones exitosas, {resultados["fallidos"]} fallidas',
            'tipo': tipo,
            'total_usuarios': len(documentos_por_usuario),
            'total_documentos': cantidad,
            'resultados': resultados,
            'usa_plantilla': True,
            'plantilla_enviada': tipo in plantillas_config
        }), 200
        
    except Exception as e:
        print(f"❌ Error en recibir_notificacion: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/notificacion/derivado', methods=['POST'])
def recibir_notificacion_derivado():
    """
    Endpoint específico para notificación de DOCUMENTO DERIVADO
    Usa la función estándar enviar_plantilla_whatsapp (sin header separado)
    """
    try:
        data = request.get_json()
        print("📥 NOTIFICACIÓN DE DOCUMENTO DERIVADO:", data)
        
        # 1. Validar teléfono
        telefono = data.get('telefono')
        if not telefono:
            return jsonify({"error": "Falta el teléfono"}), 400
        
        # 2. Función para limpiar datos (Meta rechaza valores None o vacíos)
        def limpiar(valor, default="-"):
            if valor is None or str(valor).strip() == "":
                return default
            return str(valor)
        
        # 3. Extraer y limpiar datos
        nombre = limpiar(data.get('nombre'), "Usuario")
        numero_documento = limpiar(data.get('numero_documento'))
        asunto = limpiar(data.get('asunto'))
        proyecto = limpiar(data.get('proyecto'), "Sin proyecto")
        encargado = limpiar(data.get('encargado'), "Sin asignar")
        fecha_ingreso = limpiar(data.get('fecha_ingreso'))
        link = limpiar(data.get('link'), "https://prorequest.com")
        
        # 4. Preparar parámetros según tu plantilla en Meta
        # Si tu plantilla tiene variables {{1}}, {{2}}, {{3}}... etc.
        # ajusta la cantidad según cuántas variables tenga
        parametros = [
            nombre,           # {{1}}
            numero_documento, # {{2}}
            asunto,          # {{3}}
            proyecto,        # {{4}}
            encargado,       # {{5}}
            fecha_ingreso,   # {{6}}
            link             # {{7}}
        ]
        
        print(f"📋 Parámetros preparados ({len(parametros)} valores): {parametros}")
        
        # 5. Normalizar teléfono
        telefono_normalizado = normalizar_numero_whatsapp(telefono)
        
        # 6. Verificar autorización
        usuario_info = numero_autorizado(telefono_normalizado)
        if not usuario_info:
            print(f"⚠️ Número no autorizado: {telefono_normalizado}")
            return jsonify({"error": "Número no autorizado"}), 403
        
        # 7. Enviar usando la función estándar
        print(f"📤 Enviando plantilla 'derivados_prueba' a {telefono_normalizado}")
        
        resultado = enviar_plantilla_whatsapp(
            numero=telefono_normalizado,
            nombre_plantilla="derivados_prueba",
            parametros=parametros,
            idioma="es_PE",
            tiene_boton=False  # La plantilla de derivado NO tiene botón
        )
        
        if resultado.get('status') == 'success':
            print(f"✅ Notificación de derivado enviada a {telefono_normalizado}")
            
            return jsonify({
                'status': 'success',
                'message': 'Notificación de documento derivado enviada correctamente',
                'tipo': 'documento_derivado',
                'telefono': telefono_normalizado,
                'numero_documento': numero_documento,
                'message_id': resultado.get('message_id')
            }), 200
        else:
            print(f"❌ Error enviando notificación derivado: {resultado.get('message')}")
            
            return jsonify({
                'status': 'error',
                'message': resultado.get('message', 'Error al enviar plantilla'),
                'tipo': 'documento_derivado',
                'details': resultado.get('details', {})
            }), 500
        
    except Exception as e:
        print(f"❌ Error en recibir_notificacion_derivado: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

   
def schedule_cleanup():
    limpiar_notificaciones_antiguas()
    # Programar siguiente limpieza
    timer = threading.Timer(1800, schedule_cleanup)  # 30 minutos
    timer.daemon = True
    timer.start()

# Iniciar limpieza automática
schedule_cleanup()

if __name__ == '__main__':
    print("🚀 Iniciando Chatbot WhatsApp con Memoria Conversacional Avanzada...")
    print("=" * 70)
    print(f"🧠 Memoria: {conversation_memory.max_turns} turnos máx, {conversation_memory.session_timeout/60:.0f}min timeout")
    print(f"📚 Cache documentos: {conversation_memory.max_documents_cache} docs máx por usuario")
    print(f"🔄 Estados soportados: initial, awaiting_choice, awaiting_verification, filtered_search")
    print(f"📞 Funciones especiales: contactar_encargado, algolia_search (no afectan flujo)")
    print("=" * 70)
    
    app.run(debug=True, port=5000, host='0.0.0.0')
