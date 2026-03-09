import re
from core.constants import *
from datetime import datetime
from typing import List
from services.db_service import ejecutar_query
# app.py 

from flask import Flask

import requests
from handlers.whatsapp_handler import *
from config import *

from typing import List


def normalizar_texto(t: str) -> str:
    """Normaliza texto para comparaciones"""
    return re.sub(r"\s+", " ", t.strip().lower())

def extraer_posible_codigo(texto: str):
    """Extrae posibles códigos de documento del texto"""
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
    
    if isinstance(docs, dict):
        docs = [docs]
    
    if not docs:
        return {"tipo": "vacio", "contenido": "No se encontraron documentos."}
    
    resultados = []
    multiple = len(docs) > 1
    
    if titulo_personalizado:
        resultados.append(f"{EMOJIS['search']} *{titulo_personalizado}*\n")
    
    for idx, doc in enumerate(docs, start=1):
        if multiple:
            # Versión reducida (solo algunos campos)
            resultado_doc = f"""{idx}. {EMOJIS['doc']} *Documento: {doc.get('codigo_sistema', doc.get('numero_documento', 'N/A'))}*
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


