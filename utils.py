import re
from constants import EMOJIS
from constants import SUGERENCIAS_BUSQUEDA
from conversation_memory import *
from datetime import datetime

def normalizar_texto(t: str) -> str:
    """Normaliza texto para comparaciones"""
    return re.sub(r"\s+", " ", t.strip().lower())

def extraer_posible_codigo(texto: str):
    """Extrae posibles códigos de documento del texto"""
    # Acepta: con guiones, sin guiones, con espacios
    t = re.sub(r"[\s\-_]", "", texto.upper())
    m = re.search(r"[A-Z0-9]{5,}", t)
    return m.group(0) if m else None


def normalizar_estado(estado):
    """Normaliza el estado ingresado por el usuario"""
    estado_lower = estado.lower()
    mapeo_estados = {
        'atendido': 'Atendido',
        'atendidos': 'Atendido',
        'en firma': 'En firma',
        'derivado': 'Derivado',
        'derivados': 'Derivado',
        'pendiente': 'Pendiente',
        'pendientes': 'Pendiente',
        'observado': 'Observado',
        'observados': 'Observado',
        'en stand by': 'En stand by',
        'standby': 'En stand by'
    }
    return mapeo_estados.get(estado_lower, estado)

def formatear_seguimiento(docs, titulo_personalizado=None):
    """Formatea la información de uno o múltiples documentos y devuelve tipo de resultado"""
    if not docs:
        return {"tipo": "vacio", "contenido": "No se encontró información de documentos."}
    
    # Si recibe un solo documento (dict), convertirlo a lista
    if isinstance(docs, dict):
        docs = [docs]
    
    if not docs:
        return {"tipo": "vacio", "contenido": "No se encontraron documentos."}
    
    resultados = []
    multiple = len(docs) > 1
    
    # Si hay un título personalizado, agregarlo
    if titulo_personalizado:
        resultados.append(f"{EMOJIS['search']} *{titulo_personalizado}*\n")
    
    for idx, doc in enumerate(docs, start=1):
        if multiple:
            # Versión reducida (solo algunos campos)
            resultado_doc = f"""{idx}. {EMOJIS['doc']} *Documento: {doc.get('codigo_sistema', doc.get('numero_documento', 'N/A'))}*
• *Tipo:* {doc.get('tipo', 'N/A').title()}
• *Número:* {doc.get('numero_documento', 'N/A')}
• *Asunto:* {doc.get('asunto', 'N/A')}"""
        else:
            # Versión detallada
            encargados = "No asignado"
            if doc.get('encargados_actuales'):
                try:
                    import json
                    if isinstance(doc['encargados_actuales'], str):
                        encargados_data = json.loads(doc['encargados_actuales'])
                    elif isinstance(doc['encargados_actuales'], list):
                        encargados_data = doc['encargados_actuales']
                    else:
                        encargados_data = []
                    
                    if encargados_data and isinstance(encargados_data, list):
                        encargados_list = []
                        for enc in encargados_data:
                            if isinstance(enc, dict):
                                nombre_completo = f"{enc.get('nombres', '')} {enc.get('apellido_paterno', '')}".strip()
                                if nombre_completo:
                                    encargados_list.append(nombre_completo)
                        encargados = ", ".join(encargados_list) if encargados_list else "No asignado"
                except (json.JSONDecodeError, TypeError, KeyError):
                    encargados = "No asignado"

            responsable_proyecto = ""
            if doc.get('responsable_nombres') and doc.get('responsable_apellido_paterno'):
                responsable_proyecto = f"{doc['responsable_nombres']} {doc['responsable_apellido_paterno']}"
                if doc.get('responsable_apellido_materno'):
                    responsable_proyecto += f" {doc['responsable_apellido_materno']}"
            else:
                responsable_proyecto = "No asignado"

            resultado_doc = f"""{EMOJIS['doc']} *Documento: {doc.get('codigo_sistema', doc.get('numero_documento', 'N/A'))}*

• *Tipo:* {doc.get('tipo', 'N/A').title()}
• *Número:* {doc.get('numero_documento', 'N/A')}
• *Asunto:* {doc.get('asunto', 'N/A')}
• *Estado:* {doc.get('estado_flujo', 'N/A')}
• *Prioridad:* {doc.get('prioridad_nombre', 'No asignado')}
• *Proyecto:* {doc.get('proyecto_nombre', 'No asignado')}
• *Responsable del proyecto:* {responsable_proyecto}
• *Encargados actuales:* {encargados}
• *Fecha ingreso:* {formatear_fecha(doc.get('fecha_ingreso'), "%d/%m/%Y %H:%M", "N/A")}
• *Fecha límite:* {formatear_fecha(doc.get('fecha_limite'), "%d/%m/%Y", "No definida")}
"""

            if doc.get('url_documento'):
                resultado_doc += f"\n🔗 [Ver documento]({doc['url_documento']})"
        
        resultados.append(resultado_doc)
    
    if multiple:
        resultados.append(f"\n{EMOJIS['info']} *Total encontrados:* {len(docs)} documentos")

    return {
        "tipo": "lista" if multiple else "detalle",
        "contenido": "\n\n".join(resultados),
        "total": len(docs)
    }


def formatear_fecha(valor, formato="%d/%m/%Y %H:%M", default="N/A"):
    if not valor:
        return default
    if isinstance(valor, datetime):  # ya es datetime
        return valor.strftime(formato)
    if isinstance(valor, str):  # es string
        try:
            # Intentar parsear automáticamente (ej. '2025-09-17 12:30:00')
            fecha = datetime.fromisoformat(valor.replace("Z", ""))  
        except Exception:
            try:
                # Si no es ISO, probar con un formato común (ej. '2025-09-17')
                fecha = datetime.strptime(valor, "%Y-%m-%d")
            except Exception:
                return valor  # devolver string original si no se puede parsear
        return fecha.strftime(formato)
    return default



# ========================= RUTAS DE LA APLICACIÓN =========================
def normalizar_numero_whatsapp(numero):
    # Eliminar caracteres no numéricos
    numero = ''.join(filter(str.isdigit, numero))

    # Ejemplo: asegurar que empiece con 51 para Perú
    if numero.startswith("0"):
        numero = numero[1:]  # eliminar cero inicial
    if not numero.startswith("51"):  
        numero = "51" + numero

    return numero

def limpiar_respuesta(respuesta: str) -> str:
    """
    Limpia y optimiza la respuesta generada por el modelo de IA
    para que sea más legible y apropiada para WhatsApp
    
    Args:
        respuesta: Texto de respuesta a limpiar
        
    Returns:
        Respuesta limpiada y optimizada
    """
    if not respuesta or not isinstance(respuesta, str):
        return "❓ No se pudo generar una respuesta válida."
    
    # 1. Remover espacios y saltos de línea excesivos
    respuesta = respuesta.strip()
    respuesta = re.sub(r'\n\s*\n\s*\n+', '\n\n', respuesta)  # Máximo 2 saltos seguidos
    respuesta = re.sub(r'[ \t]+', ' ', respuesta)  # Espacios múltiples a uno solo
    
    # 2. Remover patrones de prompts o instrucciones que puedan haberse colado
    patrones_a_remover = [
        r'RESPUESTA:?\s*',
        r'CONTEXTO:?\s*',
        r'CONSULTA:?\s*',
        r'INSTRUCCIONES:?\s*',
        r'^\s*-+\s*',  # Líneas con guiones
        r'^\s*=+\s*',  # Líneas con igual
        r'--- .* ---',  # Separadores con texto
        r'HISTORIAL:?\s*',
        r'ENTRADA:?\s*',
        r'Usuario:?\s*$',  # "Usuario:" al final
        r'Asistente:?\s*$',  # "Asistente:" al final
    ]
    
    for patron in patrones_a_remover:
        respuesta = re.sub(patron, '', respuesta, flags=re.IGNORECASE | re.MULTILINE)
    
    # 3. Limpiar caracteres de formato problemáticos
    respuesta = respuesta.replace('```', '')  # Remover bloques de código
    respuesta = respuesta.replace('`', '')    # Remover código inline
    respuesta = re.sub(r'\*{3,}', '**', respuesta)  # Múltiples asteriscos a negrita
    
    # 4. Optimizar formato para WhatsApp
    respuesta = optimizar_formato_whatsapp(respuesta)
    
    # 5. Validar longitud mínima
    if len(respuesta.strip()) < 5:
        return "❓ No se pudo generar una respuesta clara. ¿Puedes reformular tu pregunta?"
    
    # 6. Limitar longitud máxima
    if len(respuesta) > 1600:
        respuesta = respuesta[:1597] + "..."
    
    return respuesta.strip()

def optimizar_formato_whatsapp(texto: str) -> str:
    """
    Optimiza el formato del texto para WhatsApp
    
    Args:
        texto: Texto a optimizar
        
    Returns:
        Texto optimizado para WhatsApp
    """
    # 1. Convertir formato de listas para WhatsApp
    texto = re.sub(r'^\s*[\-\*\+]\s+', '• ', texto, flags=re.MULTILINE)
    texto = re.sub(r'^\s*\d+\.\s+', '▫️ ', texto, flags=re.MULTILINE)
    
    # 2. Mejorar encabezados
    texto = re.sub(r'^#{1,3}\s+(.+)$', r'*\1*', texto, flags=re.MULTILINE)
    
    # 3. Asegurar espacios después de emojis
    texto = re.sub(r'([🔍📊📱📢🤖💬✅❌⚠️ℹ️🚨])([^\s])', r'\1 \2', texto)
    
    # 4. Limpiar espacios antes de signos de puntuación
    texto = re.sub(r'\s+([,.!?;:])', r'\1', texto)
    
    # 5. Asegurar espacios después de puntos
    texto = re.sub(r'\.([A-ZÁÉÍÓÚÑ])', r'. \1', texto)
    
    return texto

def respuesta_saludo():
    """Genera mensaje de saludo y ayuda"""
    return (
        f"👋 ¡Hola! Soy tu asistente de ProRequest.\n\n"
        f"{SUGERENCIAS_BUSQUEDA}"
    )

#Para notificaciones
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


def formatear_alerta(documento):
    """Formatea una alerta de documento por vencer - CORREGIDA"""
    dias_restantes = documento.get('dias_restantes', 0)
        
        # Obtener información del encargado
    encargado_info = obtener_info_encargado(documento)
    nombre_encargado = encargado_info['nombre_completo'] if encargado_info else "No asignado"
        

        
        # Manejar fecha límite (puede ser string o datetime)
    fecha_limite = documento.get('fecha_limite', 'N/A')
    if isinstance(fecha_limite, str) and fecha_limite != 'N/A':
            fecha_formateada = fecha_limite
    elif hasattr(fecha_limite, 'strftime'):
            fecha_formateada = fecha_limite.strftime('%d/%m/%Y')
    else:
            fecha_formateada = 'N/A'
        
    return f"""
     {dias_restantes} días restantes
    📄 *Documento:* {documento.get('numero_documento', 'N/A')}
    📋 *Asunto:* {documento.get('asunto', 'N/A')[:60]}...
    🏗️ *Proyecto:* {documento.get('proyecto_nombre', 'No asignado')}
    👤 *Encargado:* {nombre_encargado}
    📅 *Vence:* {fecha_formateada}
    🔄 *Estado:* {documento.get('estado_flujo', 'N/A')}

    💡 *¿Quieres contactar a {nombre_encargado.split()[0] if nombre_encargado != 'No asignado' else 'el responsable'}?*
    """

def guardar_contexto(numero_telefono, payload):
    """Guarda el contexto de la alerta para seguimiento posterior"""
    try:
        # Usar el sistema de memoria conversacional existente
        context_info = {
            "alert_payload": payload,
            "alert_active": True,
            "document_number": payload.get('numero_documento'),
            "system_code": payload.get('codigo_sistema')
        }
        
        # Actualizar memoria conversacional con la alerta
        conversation_memory.add_turn(
            phone_number=numero_telefono,
            user_message="[ALERTA_RECIBIDA]",
            bot_response="[ALERTA_ENVIADA]",
            intent="alerta_documento",
            parameters=payload,
            context=context_info
        )
        
        print(f"✅ Contexto de alerta guardado para {numero_telefono}")
        return True
        
    except Exception as e:
        print(f"❌ Error guardando contexto alerta: {e}")
        return False


