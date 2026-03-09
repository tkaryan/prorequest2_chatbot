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
from handlers.whatsapp_handler import *

from typing import List
app = Flask(__name__)


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


def schedule_cleanup():
    limpiar_notificaciones_antiguas()
    # Programar siguiente limpieza
    timer = threading.Timer(1800, schedule_cleanup)  # 30 minutos
    timer.daemon = True
    timer.start()


@app.route('/whatsapp/webhook', methods=['GET','POST'])
def whatsapp_webhook():

    if request.method == 'GET':
        return verify_whatsapp_webhook(request)

    if request.method == 'POST':
        try:

            data = request.get_json()

            message = extract_message(data)
            if not message:
                return jsonify({"status": "no_message"}), 200

            numero_telefono = message["phone"]

            response = process_whatsapp_message(message)

            if response:
                enviar_mensaje_whatsapp(numero_telefono, response)

            return jsonify({"status": "ok"}), 200

        except Exception as e:
            print(f"❌ Error webhook: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error"}), 500
        

@app.route('/api/notificacion', methods=['POST'])
def recibir_notificacion():
    """
    Recibe notificaciones del backend, las almacena y envía plantilla WhatsApp.
    Guarda documentos en notification_manager (para consultas futuras por tipo)
    y pre-carga en conversation_memory (para selección inmediata si el usuario responde).
    """
    try:
        data     = request.get_json()
        tipo     = data.get('tipo')
        cantidad = data.get('cantidad', 0)
        documentos = data.get('documentos', [])

        if not documentos:
            return jsonify({"error": "No hay documentos en el payload"}), 400

        plantillas_config = {
            'documentos_inactivos_masivo':    {'nombre': 'alerta_documentos_inactivos'},
            'documentos_en_stand_by_masivo':  {'nombre': 'documentos_stand_by'},
            'documentos_en_firma_masivo':     {'nombre': 'documento_sin_firma'},
            'documentos_antiguos_masivo':     {'nombre': 'documento_sin_respuesta'},
        }

        # ── Agrupar por destinatario ──────────────────────────────────────────
        documentos_por_usuario = defaultdict(list)
        for doc_data in documentos:
            for telefono in doc_data.get('destinatarios', []):
                telefono_norm = normalizar_numero_whatsapp(telefono)
                if numero_autorizado(telefono_norm):
                    documentos_por_usuario[telefono_norm].append(doc_data)
                else:
                    print(f"⚠️ Número no autorizado: {telefono_norm}")

        resultados = {'exitosos': 0, 'fallidos': 0, 'detalles': []}

        for telefono, docs_usuario in documentos_por_usuario.items():
            try:
                usuario_info   = numero_autorizado(telefono)
                nombre_usuario = usuario_info.get('nombres', 'Usuario') if usuario_info else 'Usuario'
                cantidad_docs  = len(docs_usuario)

                print(f"📱 Notificación para {telefono} ({cantidad_docs} docs, tipo={tipo})")

                # ── 1. Guardar en notification_manager ────────────────────────
                notification_group = notification_manager.store_notifications(
                    phone_number=telefono,
                    notifications_data={"tipo": tipo, "cantidad": cantidad_docs, "documentos": docs_usuario}
                )
                if not notification_group:
                    raise Exception("Error almacenando en notification_manager")

                # ── 2. Pre-cargar en conversation_memory ──────────────────────
                # Así cuando el usuario responda al botón, flow.py ya tiene los docs
                tipo_interno = notification_manager._identificar_tipo(tipo)
                conversation_memory.set_conversation_documents(
                    phone_number=telefono,
                    documents=docs_usuario,
                    source_intent=f"notificacion_{tipo_interno}",
                    source_query=f"Notificación entrante: {tipo}"
                )
                s = conversation_memory._get_or_create_state(telefono)
                s["pending_notification_tipo"] = tipo_interno
                conversation_memory._b.set_state(telefono, s)
                print(f"📚 {cantidad_docs} docs pre-cargados en conversation_memory para {telefono}")

                # ── 3. Enviar plantilla WhatsApp ──────────────────────────────
                if tipo not in plantillas_config:
                    print(f"⚠️ Tipo no soportado para plantilla: {tipo}")
                    resultados['fallidos'] += 1
                    resultados['detalles'].append({
                        'telefono': telefono, 'status': 'error',
                        'error': f'Tipo no soportado: {tipo}'
                    })
                    continue

                config     = plantillas_config[tipo]
                parametros = [str(cantidad_docs), nombre_usuario, str(cantidad_docs)]

                resultado = enviar_plantilla_whatsapp(
                    numero=telefono,
                    nombre_plantilla=config['nombre'],
                    parametros=parametros,
                    idioma="es_PE"
                )

                if resultado.get('status') == 'success':
                    notification_manager.template_message_ids[notification_group['id']] = resultado.get('message_id')
                    resultados['exitosos'] += 1
                    resultados['detalles'].append({
                        'telefono':        telefono,
                        'documentos':      cantidad_docs,
                        'status':          'success',
                        'tipo':            tipo,
                        'plantilla':       config['nombre'],
                        'notification_id': notification_group['id'],
                        'message_id':      resultado.get('message_id')
                    })
                    print(f"✅ Plantilla '{config['nombre']}' enviada a {telefono}")
                else:
                    resultados['fallidos'] += 1
                    resultados['detalles'].append({
                        'telefono': telefono, 'documentos': cantidad_docs,
                        'status': 'error', 'tipo': tipo,
                        'plantilla': config['nombre'],
                        'error': resultado.get('message', 'Error desconocido')
                    })
                    print(f"❌ Error plantilla '{config['nombre']}' → {telefono}: {resultado.get('message')}")

            except Exception as e:
                print(f"❌ Error procesando {telefono}: {e}")
                import traceback; traceback.print_exc()
                resultados['fallidos'] += 1
                resultados['detalles'].append({'telefono': telefono, 'status': 'error', 'error': str(e)})

        return jsonify({
            'status':           'success',
            'message':          f'{resultados["exitosos"]} exitosas, {resultados["fallidos"]} fallidas',
            'tipo':             tipo,
            'total_usuarios':   len(documentos_por_usuario),
            'total_documentos': cantidad,
            'resultados':       resultados,
        }), 200

    except Exception as e:
        print(f"❌ Error en recibir_notificacion: {e}")
        import traceback; traceback.print_exc()
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



# Iniciar limpieza automática
schedule_cleanup()

if __name__ == '__main__':
    print("🚀 Iniciando Chatbot WhatsApp con Memoria Conversacional Avanzada...")
    print("=" * 70)
    print(f"🔄 Estados soportados: initial, awaiting_choice, awaiting_verification, filtered_search")
    print(f"📞 Funciones especiales: contactar_encargado, algolia_search (no afectan flujo)")
    print("=" * 70)
    
    app.run(debug=True, port=5000, host='0.0.0.0')
