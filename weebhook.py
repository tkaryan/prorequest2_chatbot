@app.route('/whatsapp/webhook', methods=['GET', 'POST'])
def whatsapp_webhook():
    """Webhook para WhatsApp Business API - CON VALIDACIÓN DE SEGURIDAD"""
    if request.method == 'GET':
        # [Código de verificación existente...]
        return challenge
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            
            if (data.get('entry') and 
                len(data['entry']) > 0 and 
                data['entry'][0].get('changes') and 
                len(data['entry'][0]['changes']) > 0 and 
                'messages' in data['entry'][0]['changes'][0]['value']):
                
                messages = data['entry'][0]['changes'][0]['value']['messages']
                
                for message in messages:
                    if message.get('type') == 'text':
                        numero_telefono = message['from']
                        texto_mensaje = message['text']['body']
                        
                        print(f"📱 Mensaje recibido de {numero_telefono}: {texto_mensaje}")
                        
                        # 🔐 VALIDAR NÚMERO AUTORIZADO
                        if not numero_autorizado(numero_telefono):
                            print(f"❌ Número no autorizado: {numero_telefono}")
                            registrar_intento_no_autorizado(numero_telefono, texto_mensaje)
                            
                            # ✅ ENVIAR SOLO MENSAJE DE CONTACTO (una vez)
                            # Evitar múltiples envíos del mismo mensaje
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
                                # Solo enviar si el mensaje no es del propio chatbot
                                enviar_mensaje_whatsapp(numero_telefono, mensaje_contacto)
                            
                            return jsonify({'status': 'unauthorized'}), 403
                        
                        # ✅ Si está autorizado, procesar NORMALMENTE (alertas y todo)
                        respuesta = procesar_mensaje(texto_mensaje, numero_telefono)
                        
                        if respuesta:
                            enviar_mensaje_whatsapp(numero_telefono, respuesta)
            
            return jsonify({'status': 'success'}), 200
            
        except Exception as e:
            print(f"❌ Error procesando webhook WhatsApp: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500