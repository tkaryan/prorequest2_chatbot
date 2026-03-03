
ALERTAS_EJEMPLOS = {
    "alertas_pendientes": [
        {
            "proyecto": "Centro de Salud Chiquian",
            "documento": "1913-2025-OXI",
            "asunto": "Confirmar voluntad de acudir a arbitraje ante la denegatoria de trato directo",
            "estado": "Pendiente",
            "dias_restantes": 3,
            "encargado_actual": "María Rodríguez",
            "correo_encargado": "angeladiazreyes32@gmail.com",
            "celular_encargado": "+51 961 259 401",
            "fecha_limite": "2025-08-29",
            "prioridad": "Alta"
        },
        {
            "proyecto": "Sistema de Agua Potable",
            "documento": "2024-001-AGUA",
            "asunto": "Aprobación de presupuesto para instalación de tuberías",
            "estado": "En revisión",
            "dias_restantes": 1,
            "encargado_actual": "Carlos Mendoza",
            "correo_encargado": "angeladiazreyes32@gmail.com",
            "celular_encargado": "+51 961 259 401",
            "fecha_limite": "2024-01-13",
            "prioridad": "Urgente"
        }
    ]
}

#FUNCIÓN DE OBTENCIÓN DE DOCUMENTOS (Modo Prueba) 


def obtener_documentos_por_vencer(dias=7):
    """Obtiene documentos por vencer - VERSIÓN CON JSON Y ALEATORIEDAD"""
    # Usar datos de ejemplo del JSON
    documentos_ejemplo = ALERTAS_EJEMPLOS["alertas_pendientes"]
    
    # 🔁 Modo aleatorio: A veces devolver alertas, a veces no
    import random
    modo_prueba = random.choice(["con_alertas", "sin_alertas", "con_alertas", "con_alertas"])
    
    if modo_prueba == "sin_alertas":
        print("🎲 Modo prueba: No hay alertas (aleatorio)")
        return []  # No hay documentos para simular "está al día"
    else:
        # Seleccionar aleatoriamente 1-3 documentos del JSON
        num_alertas = random.randint(1, 3)
        documentos_seleccionados = random.sample(documentos_ejemplo, min(num_alertas, len(documentos_ejemplo)))
        
        print(f"🎲 Modo prueba: {len(documentos_seleccionados)} alertas (aleatorio)")
        return documentos_seleccionados


#FUNCIÓN DE INFORMACIÓN DE ENCARGADO (Mejorada)

def obtener_info_encargado(documento):
    """Obtiene información del encargado actual del documento - CORREGIDA"""
    try:
        # Para documentos de prueba del JSON
        if 'encargado_actual' in documento and 'celular_encargado' in documento:
            return {
                'nombre_completo': documento['encargado_actual'],
                'nombre': documento['encargado_actual'].split()[0],
                'correo': documento.get('correo_encargado', 'No disponible'),
                'celular': documento.get('celular_encargado', 'No disponible')
            }
        
        # El resto de la lógica original para documentos reales de BD...
        # [Mantener código existente para producción]
        
    except Exception as e:
        print(f"❌ Error obteniendo info encargado: {e}")
        return None
    
    
    #FUNCIÓN DE FORMATEO DE ALERTA (Corregida)
    
    def formatear_alerta(documento):
     """Formatea una alerta de documento por vencer - CORREGIDA"""
    dias_restantes = documento.get('dias_restantes', 0)
    
    # Obtener información del encargado
    encargado_info = obtener_info_encargado(documento)
    nombre_encargado = encargado_info['nombre_completo'] if encargado_info else "No asignado"
    
    # Determinar nivel de urgencia
    if dias_restantes <= 2:
        emoji = "🔴"
        urgencia = "URGENTE"
    elif dias_restantes <= 5:
        emoji = "🟡"
        urgencia = "PRÓXIMO A VENCER"
    else:
        emoji = "🔵"
        urgencia = "POR VENCER"
    
    # Manejar fecha límite (puede ser string o datetime)
    fecha_limite = documento.get('fecha_limite', 'N/A')
    if isinstance(fecha_limite, str) and fecha_limite != 'N/A':
        fecha_formateada = fecha_limite
    elif hasattr(fecha_limite, 'strftime'):
        fecha_formateada = fecha_limite.strftime('%d/%m/%Y')
    else:
        fecha_formateada = 'N/A'
    
    return f"""
{emoji} *{urgencia}* - {dias_restantes} días restantes
📄 *Documento:* {documento.get('numero_documento', 'N/A')}
📋 *Asunto:* {documento.get('asunto', 'N/A')[:60]}...
🏗️ *Proyecto:* {documento.get('proyecto_nombre', 'No asignado')}
👤 *Encargado:* {nombre_encargado}
📅 *Vence:* {fecha_formateada}
🔄 *Estado:* {documento.get('estado_flujo', 'N/A')}

💡 *¿Quieres contactar a {nombre_encargado.split()[0] if nombre_encargado != 'No asignado' else 'el responsable'}?*
"""

#FUNCIÓN DE WHATSAPP (Redirección Directa)

def generar_mensaje_whatsapp(documento):
    """Genera mensaje para WhatsApp - VERSIÓN MEJORADA"""
    
    # Para documentos de prueba del JSON
    if 'encargado_actual' in documento and 'celular_encargado' in documento:
        celular = documento['celular_encargado']
        nombre = documento['encargado_actual']
    else:
        # Datos de prueba
        celular = "+51972453786"
        nombre = "Usuario de Prueba"
    
    # Mensaje directo y corto
    mensaje = (
        f"Hola {nombre.split()[0]}, te contacto respecto al documento "
        f"{documento.get('numero_documento', 'DOC-001')} - "
        f"{documento.get('asunto', 'Asunto de prueba')[:30]}... "
        f"¿Podrías darme una actualización? Gracias."
    )
    
    # Limpiar y formatear número
    celular_limpio = re.sub(r"[^0-9]", "", celular)
    if not celular_limpio.startswith('51'):
        celular_limpio = '51' + celular_limpio.lstrip('0')
    
    url_whatsapp = f"https://wa.me/{celular_limpio}?text={requests.utils.quote(mensaje)}"
    
    return {
        'mensaje': mensaje,
        'url_whatsapp': url_whatsapp,
        'encargado': nombre,
        'celular': celular
    }
    

#PROCESAMIENTO DE SOLICITUD DE ALERTAS (Mejorado)


def procesar_solicitud_alertas(numero_telefono):
    """Procesa solicitud de alertas de documentos por vencer - MENSAJE MEJORADO"""
    documentos = obtener_documentos_por_vencer(7)
    
    if not documentos:
        # NO HAY ALERTAS - Ofrecer opciones de búsqueda
        return (
            f"{EMOJIS['ok']} ✅ ¡Excelente! Estás al día. No hay documentos pendientes por vencer.\n\n"
            f"💡 *¿Qué te gustaría hacer ahora?*\n\n"
            f"• 'buscar [término]' - Buscar documentos específicos\n"
            f"• 'seguimiento [código]' - Ver estado de un documento\n"  
            f"• 'proyecto [nombre]' - Documentos de un proyecto\n"
            f"• 'usuario [nombre]' - Documentos por responsable\n"
            f"• 'alertas' - Volver a verificar documentos pendientes\n\n"
            f"*Ejemplo:* `buscar contrato sistema agua`"
        )
    
    # SÍ HAY ALERTAS - Mostrar documentos
    respuesta = f"🚨 *DOCUMENTOS POR VENCER*\n\n"
    
    for i, doc in enumerate(documentos[:3], 1):
        respuesta += formatear_alerta(doc)
        respuesta += "\n" + "─" * 40 + "\n"
        
        # Guardar contexto del primer documento para seguimiento
        if i == 1:
            guardar_contexto(numero_telefono, doc)
    
    respuesta += (
        f"\n{EMOJIS['tip']} *¿Qué deseas hacer? Responde con:*\n"
        f"• 'contactar' - 📞 Hablar directamente por WhatsApp\n"
        f"• 'seguimiento' - 🔍 Ver información completa\n"
        f"• 'atendido' - ✅ Marcar como resuelto\n"
        f"• 'más' - ⚙️ Ver otras opciones"
    )
    
    return respuesta

#PROCESAMIENTO DE RESPUESTA (Redirección Automática)

def procesar_respuesta_alerta(mensaje, numero_telefono, contexto):
    """Procesa la respuesta del usuario a una alerta - VERSIÓN ULTRA-DIRECTA"""
    mensaje_normalizado = normalizar_texto(mensaje)
    documento = contexto['documento']
    
    # PALABRAS CLAVE PARA REDIRECCIÓN AUTOMÁTICA A WHATSAPP
    palabras_contacto = [
        'contactar', 'contacto', 'comunicar', 'comunicarme', 'hablar', 
        'escribir', 'llamar', 'whatsapp', 'wasap', 'wsp', 'mensaje',
        'deseo contactar', 'quiero contactar', 'deseo comunicar', 
        'quiero hablar', 'necesito contactar', 'dame el contacto',
        'redirigir', 'redirigirme', 'escribirle', 'contactarlo',
        'sí', 'si', 'ok', 'vale', 'correcto', 'afirmativo'
    ]
    
    # 🔥 REDIRECCIÓN AUTOMÁTICA si detecta cualquier palabra de contacto
    if any(palabra in mensaje_normalizado for palabra in palabras_contacto):
        info_whatsapp = generar_mensaje_whatsapp(documento)
        
        if info_whatsapp:
            # ✅ VERSIÓN SUPER DIRECTA - SOLO LO ESENCIAL
            respuesta = (
                f"✅ *Redirigiendo a WhatsApp...*\n\n"
                f"👤 {info_whatsapp['encargado']}\n"
                f"📞 {info_whatsapp['celular']}\n\n"
                f"🔗 *HAZ CLIC AQUÍ para contactar ahora:*\n"
                f"{info_whatsapp['url_whatsapp']}\n\n"
                f"💬 El mensaje ya está preparado. Solo presiona ENVIAR."
            )
        else:
            respuesta = "❌ No se puede contactar en este momento."
        
        limpiar_contexto(numero_telefono)
        return respuesta
    
    # [Mantener el resto de la lógica para otras opciones...]


















































































