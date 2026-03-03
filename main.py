# app.py 

from flask import Flask, request, jsonify
import requests
from chatbot_system import *
from consultas_chatbot import *
from config import *
from constants import *
from algolia_chatbot import *
from utils import *
from core import *
from services import *

app = Flask(__name__)

@app.route('/whatsapp/webhook', methods=['GET', 'POST'])
def whatsapp_webhook():
    """Webhook para WhatsApp Business API - CON MEMORIA Y FLUJO DE CONFIRMACIÓN CORREGIDO"""
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
            if (data.get('entry') and len(data['entry']) > 0 
                and data['entry'][0].get('changes') 
                and len(data['entry'][0]['changes']) > 0 
                and 'messages' in data['entry'][0]['changes'][0]['value']):
                
                messages = data['entry'][0]['changes'][0]['value']['messages']
                
                for message in messages:
                    # Solo procesar mensajes de texto
                    if message.get('type') == 'text':
                        numero_telefono = message['from']
                        texto_mensaje = message['text']['body']
                        print(f"📱 Mensaje recibido de {numero_telefono}: {texto_mensaje}")
                        
                        # Verificar autorización
                        usuario = numero_autorizado(numero_telefono)
                        print("Usuario autorizado:", usuario)
                        if not numero_autorizado(numero_telefono):
                            if "chatbot" not in texto_mensaje.lower():
                                mensaje_contacto = (
                                    "👋 *¡Hola!*\n\n"
                                    "Este es el chatbot de ProRequest. "
                                    "Actualmente no estás registrado en nuestro sistema.\n\n"
                                    "📞 *Para agregar tus datos:*\n"
                                    "Comunicarse con la administración\n"
                                    "👤 *Juan David*\n"
                                    "📱 +51 957 133 488\n\n"
                                    "*Horario de atención:*\n"
                                    "Lunes a Viernes: 8:00 AM - 6:00 PM\n"
                                    "Sábados: 9:00 AM - 1:00 PM"
                                )
                                enviar_mensaje_whatsapp(numero_telefono, mensaje_contacto)
                                
                            print(f"❌ Número no autorizado: {numero_telefono}")
                            registrar_intento_no_autorizado(numero_telefono, texto_mensaje)
                            return jsonify({'status': 'unauthorized'}), 403
                        
                        # 🧠 Establecer rol del usuario en memoria
                        conversation_memory.set_user_role(numero_telefono, usuario["nivel_acceso"])
                        
                        # 🧠 Obtener estado actual ANTES de procesar
                        conversation_state = conversation_memory.get_conversation_state(numero_telefono)
                        conv_context = conversation_memory.get_conversation_context(numero_telefono)
                        
                        print(f"🧠 Estado conversación: {conversation_state['state']}")
                        print(f"🧠 Contexto: {conv_context['session_length']} turnos")
                        print(f"🔍 Debe buscar BD completa: {conversation_state['should_search_full_db']}")
                        
                        if conversation_state.get("awaiting_confirmation"):
                            print(f"⏳ Esperando confirmación tipo: {conversation_state.get('confirmation_type')}")
                        
                        # 🔄 NO hacer reset automático aquí - que lo maneje el flow.py
                        # Se removió la lógica de reset manual del webhook
                        
                        # Procesar mensaje con información de estado
                        print("🔄 Procesando mensaje...")
                        respuesta_completa = procesar_mensaje(
                            texto_mensaje, 
                            numero_telefono,
                            conversation_state=conversation_state,
                            conversation_context=conv_context
                        )
                        print("RESPUESTA ANTES DE WP:", respuesta_completa)
                        
                        # Extraer respuesta y tipo
                        if isinstance(respuesta_completa, dict):
                            respuesta = respuesta_completa.get("respuesta")
                            tipo = respuesta_completa.get("tipo")
                            intent = respuesta_completa.get("intent", "unknown")
                            parameters = respuesta_completa.get("parameters", {})
                        else:
                            respuesta = str(respuesta_completa)
                            tipo = "consulta"
                            intent = "general"
                            parameters = {}

                        print("🪵 DEBUG - Respuesta procesada:")
                        print(f"   • Tipo   : {tipo}")
                        print(f"   • Intent : {intent}")
                        print(f"   • Longitud: {len(str(respuesta)) if respuesta else 0} caracteres")
                        
                        # 🔄 Manejo especial para respuestas de confirmación
                        if isinstance(respuesta, dict):
                            print(f"   • Keys   : {list(respuesta.keys())}")
                            if 'contenido' in respuesta:
                                respuesta = respuesta['contenido']
                            elif 'message' in respuesta:
                                respuesta = respuesta['message']
                            else:
                                respuesta = str(respuesta)

                        # 🧠 DETERMINAR message_type basado en tipo de respuesta
                        message_type = "consulta"  # Default
                        
                        if tipo == 'detalle' or tipo == 'select_document':
                            message_type = "verificacion"
                        elif tipo == 'lista':
                            message_type = "eleccion"
                            if 'resultados' in respuesta_completa:
                                parameters["results_count"] = len(respuesta_completa['resultados'])
                        elif intent in ["contactar_encargado", "algolia_search"]:
                            message_type = "consulta"
                        elif intent == "confirmar_seleccion":
                            # 🆕 CLAVE: No cambiar message_type para confirmaciones
                            message_type = "confirmacion"

                        print(f"📝 Message type determinado: {message_type}")

                        # Enviar respuesta principal
                        if respuesta:
                            exito_envio = enviar_mensaje_whatsapp(numero_telefono, respuesta)
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
                                
                                # 🧠 GUARDAR DOCUMENTOS SI EXISTEN (solo para nuevas búsquedas)
                                if 'resultados' in respuesta_completa or intent == "confirmar_seleccion":
                                    success = conversation_memory.set_conversation_documents(
                                        phone_number=numero_telefono,
                                        documents=respuesta_completa['resultados'],
                                        source_intent=intent,
                                        source_query=texto_mensaje
                                    )

                                    if success:
                                        print(f"📚 {len(respuesta_completa['resultados'])} documentos guardados en memoria")
                                
                                # 🧠 MANEJO DE PREGUNTAS DE CONFIRMACIÓN Y ESTADOS
                                
                                # 1. Para listas nuevas -> pregunta de elección
                                if message_type == "eleccion":
                                    pregunta_confirmacion = "¿En cuál de los documentos requires informacion? \n Si quieres iniciar una nueva búsqueda, escribe 'Hola'"
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
                                
                                # 2. Para documento específico -> pregunta de verificación
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
                                
                                # 3. Para confirmaciones -> manejar según respuesta
                                elif intent == "confirmar_seleccion":
                                    params = parameters or {}
                                    confirmacion_positiva = params.get("confirmacion_positiva", False)
                                    
                                    if confirmacion_positiva:
                                        # Confirmación POSITIVA
                                        estado_anterior = conversation_state.get('state')
                                        
                                        if estado_anterior == "awaiting_choice":
                                            # Usuario confirmó elección -> activar modo filtrado
                                          #  conversation_memory.set_filtered_search_mode(numero_telefono)
                                            seguimiento_msg = "Perfecto! Ahora puedes hacer consultas específicas sobre estos documentos. ¿En qué más te puedo ayudar?"
                                            enviar_mensaje_whatsapp(numero_telefono, seguimiento_msg)
                                            print("✅ Modo búsqueda filtrada activado por confirmación positiva de elección")
                                            
                                        elif estado_anterior == "awaiting_verification":
                                            # Usuario confirmó verificación -> mantener estado actual  
                                            conversation_memory.set_awaiting_choice_search_mode(numero_telefono)
                                            seguimiento_msg = "¡Perfecto! ¿Necesitas ayuda con algo más?. Puedes escribir 'hola' para empezar de nuevo."
                                            enviar_mensaje_whatsapp(numero_telefono, seguimiento_msg)
                                            print("✅ Verificación confirmada")
                                    
                                    else:
                                        # Confirmación NEGATIVA
                                        estado_anterior = conversation_state.get('state')
                                        
                                        if estado_anterior == "awaiting_choice":
                                            # Usuario rechazó elección -> MANTENER documentos y cambiar a filtered_search
                                        #    conversation_memory.set_filtered_search_mode(numero_telefono)
                                            print("❌ Usuario rechazó elección, pero MANTIENE búsqueda filtrada")
                                            
                                        elif estado_anterior == "awaiting_verification":
                                            # Usuario rechazó verificación -> MANTENER documentos y cambiar a filtered_search
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

@app.route('/api/notificacion', methods=['POST'])
def recibir_notificacion():
    """
    Endpoint para recibir notificaciones desde tu backend Node.js
    y enviarlas por WhatsApp al usuario.
    NUEVO: Estas notificaciones pueden activar el flujo de "contactar encargado"
    """
    try:
        data = request.get_json()

        numero_telefono = data.get("telefono")
        mensaje = data.get("mensaje")
        payload = data.get("payload")
        tipo_notificacion = data.get("tipo", "general")  # NUEVO: tipo de notificación
        
        print("el payload:", payload)
        if not numero_telefono or not mensaje:
            return jsonify({"error": "Faltan parámetros (telefono, mensaje)"}), 400
        
        numero_telefono = normalizar_numero_whatsapp(numero_telefono)
        print(f"📢 Notificación {tipo_notificacion} recibida para {numero_telefono}: {mensaje}")
        
        # Guardar contexto de este documento (para seguimiento/contacto)
        guardar_contexto(numero_telefono, payload)
        
        # 🧠 NUEVO: Si es una notificación de alerta, guardar en memoria para posible "contactar encargado"
        if tipo_notificacion == "alerta":
            # Guardar turno de notificación en memoria (pero no afecta estados de búsqueda)
            conversation_memory.add_turn(
                phone_number=numero_telefono,
                user_message="[system] notification_received",
                bot_response=mensaje,
                intent="system_notification",
                parameters={
                    "notification_type": tipo_notificacion,
                    "payload": payload
                },
                context={"can_contact_responsible": True},
                message_type="notification"
            )

        # Enviar mensaje por WhatsApp
        enviado = enviar_mensaje_whatsapp(numero_telefono, mensaje)
        
        # 🧠 NUEVO: Si es alerta, enviar opción de contactar encargado
        if enviado and tipo_notificacion == "alerta":
            mensaje_opcion = "\n💬 Responde 'contactar encargado' si necesitas comunicarte con el responsable del proyecto."
            enviar_mensaje_whatsapp(numero_telefono, mensaje_opcion)

        if enviado:
            return jsonify({"status": "success", "message": "Notificación enviada por WhatsApp"}), 200
        else:
            return jsonify({"status": "error", "message": "Error al enviar por WhatsApp"}), 500

    except Exception as e:
        print(f"❌ Error en recibir_notificacion: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# 🧠 NUEVO: Endpoint para estadísticas de conversación
@app.route('/api/conversation-stats', methods=['GET'])
def conversation_stats():
    """Endpoint para obtener estadísticas de conversación"""
    try:
        # Estadísticas básicas
        total_conversations = len(conversation_memory.conversations)
        total_states = len(conversation_memory.conversation_states)
        total_cached_docs = sum(len(docs) for docs in conversation_memory.document_cache.values())
        
        # Estados actuales
        states_summary = {}
        for phone, state_info in conversation_memory.conversation_states.items():
            state = state_info["state"]
            if state in states_summary:
                states_summary[state] += 1
            else:
                states_summary[state] = 1
        
        stats = {
            "total_active_conversations": total_conversations,
            "total_conversation_states": total_states,
            "total_cached_documents": total_cached_docs,
            "states_distribution": states_summary,
            "memory_limits": {
                "max_turns": conversation_memory.max_turns,
                "session_timeout_minutes": conversation_memory.session_timeout / 60,
                "max_documents_cache": conversation_memory.max_documents_cache
            }
        }
        
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 🧠 NUEVO: Endpoint para limpiar conversación específica
@app.route('/api/clear-conversation', methods=['POST'])
def clear_conversation():
    """Endpoint para limpiar conversación de un usuario"""
    try:
        data = request.get_json()
        phone_number = data.get("phone_number")
        
        if not phone_number:
            return jsonify({"error": "phone_number requerido"}), 400
            
        conversation_memory.clear_conversation(phone_number)
        return jsonify({"status": "success", "message": "Conversación limpiada"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 🧠 NUEVO: Endpoint para obtener estado de conversación específica
@app.route('/api/conversation-state/<phone_number>', methods=['GET'])
def get_conversation_state(phone_number):
    """Endpoint para obtener el estado de una conversación específica"""
    try:
        state = conversation_memory.get_conversation_state(phone_number)
        context = conversation_memory.get_conversation_context(phone_number)
        cached_docs = conversation_memory.get_conversation_documents(phone_number, limit=5)
        
        response = {
            "phone_number": phone_number,
            "state": state,
            "context": context,
            "cached_documents_count": len(cached_docs),
            "recent_documents": [doc.get("document_id", "N/A") for doc in cached_docs[:3]]
        }
        
        return jsonify(response), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("🚀 Iniciando Chatbot WhatsApp con Memoria Conversacional Avanzada...")
    print("=" * 70)
    print(f"🧠 Memoria: {conversation_memory.max_turns} turnos máx, {conversation_memory.session_timeout/60:.0f}min timeout")
    print(f"📚 Cache documentos: {conversation_memory.max_documents_cache} docs máx por usuario")
    print(f"🔄 Estados soportados: initial, awaiting_choice, awaiting_verification, filtered_search")
    print(f"📞 Funciones especiales: contactar_encargado, algolia_search (no afectan flujo)")
    print("=" * 70)
    
    app.run(debug=True, port=5000, host='0.0.0.0')
