# notification_manager.py - Sistema unificado de notificaciones con tipos
from collections import defaultdict
from datetime import datetime, timedelta
import threading
import time
import json
from typing import Dict, List, Optional
from enum import Enum


class TipoNotificacion(Enum):
    """Tipos de notificaciones con sus configuraciones"""
    SIN_RESPUESTA = {
        "nombre": "Sin Respuesta",
        "payload": "revisar_sin_respuesta",
        "emoji": "📬",
        "descripcion": "Documentos sin respuesta",
        "tipos_backend": ["documentos_antiguos_masivo", "documentos_sin_respuesta"]
    }
    SIN_FIRMA = {
        "nombre": "Sin Firma",
        "payload": "revisar_sin_firma",
        "emoji": "✍️",
        "descripcion": "Documentos pendientes de firma",
        "tipos_backend": ["documentos_en_firma_masivo", "documentos_sin_firma"]
    }
    INACTIVOS = {
        "nombre": "Inactivos",
        "payload": "revisar_inactivos",
        "emoji": "⏱️",
        "descripcion": "Documentos inactivos (+15 días)",
        "tipos_backend": ["documentos_inactivos_masivo", "documentos_inactivos", "documentos_en_espera"]
    }
    STAND_BY = {
        "nombre": "Stand By",
        "payload": "revisar_stand_by",
        "emoji": "⏸️",
        "descripcion": "Documentos en Stand By",
        "tipos_backend": ["documentos_en_stand_by_masivo", "documentos_stand_by"]
    }

class NotificationManager:
    """Gestiona notificaciones con buffer inteligente y plantillas WhatsApp"""
    
    def __init__(self):
        # Sistema de buffer para consolidación
        self.pending_notifications = {}
        self.timers = {}
        self.BUFFER_TIME = 5
        
        # Sistema de almacenamiento permanente
        self.user_notifications: Dict[str, Dict[str, List[Dict]]] = {}
        self.template_message_ids: Dict[str, str] = {}
        self.viewed_notifications: set = set()

    def _identificar_tipo_notificacion(self, tipo_backend: str) -> str:
        """Identifica el tipo interno desde el tipo del backend"""
        tipo_lower = tipo_backend.lower()
        
        # Buscar en cada enum
        for tipo_enum in TipoNotificacion:
            if tipo_lower in [t.lower() for t in tipo_enum.value["tipos_backend"]]:
                # Extraer nombre del enum (SIN_RESPUESTA -> sin_respuesta)
                return tipo_enum.name.lower()
        
        # Default
        return "inactivos"
    
    def _get_tipo_config(self, tipo_interno: str) -> Dict:
        """Obtiene la configuración del tipo de notificación"""
        tipo_map = {
            "sin_respuesta": TipoNotificacion.SIN_RESPUESTA.value,
            "sin_firma": TipoNotificacion.SIN_FIRMA.value,
            "inactivos": TipoNotificacion.INACTIVOS.value,
            "stand_by": TipoNotificacion.STAND_BY.value
        }
        return tipo_map.get(tipo_interno, TipoNotificacion.INACTIVOS.value)
    
    # ==================== MÉTODOS DE BUFFER Y CONSOLIDACIÓN ====================
    
    def add_notification(self, numero_telefono, mensaje, payload, tipo_notificacion="general"):
        """Agrega una notificación al buffer y maneja el timing"""
        try:
            if numero_telefono not in self.pending_notifications:
                self.pending_notifications[numero_telefono] = []
            
            is_consolidated = self._is_consolidated_notification(payload)
            
            notification_data = {
                "mensaje": mensaje,
                "payload": payload,
                "tipo": tipo_notificacion,
                "timestamp": datetime.now(),
                "id": f"{tipo_notificacion}_{int(time.time())}_{len(self.pending_notifications[numero_telefono]) + 1}",
                "viewed": False,
                "is_consolidated": is_consolidated
            }
            
            self.pending_notifications[numero_telefono].append(notification_data)
            print(f"📢 Notificación {'consolidada' if is_consolidated else 'individual'} agregada para {numero_telefono}. Total: {len(self.pending_notifications[numero_telefono])}")
            
            # Cancelar timer anterior y crear nuevo
            if numero_telefono in self.timers:
                self.timers[numero_telefono].cancel()
            
            timer = threading.Timer(
                self.BUFFER_TIME, 
                self._process_notifications, 
                args=[numero_telefono]
            )
            timer.start()
            self.timers[numero_telefono] = timer
            
            return True
            
        except Exception as e:
            print(f"❌ Error agregando notificación: {e}")
            return False
    
    def _is_consolidated_notification(self, payload):
        """Detecta si el payload es una notificación consolidada"""
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)
            
            return (
                payload.get("tipo") == "documentos_en_espera" and
                payload.get("cantidad", 0) >= 1 and
                isinstance(payload.get("documentos"), list)
            )
        except:
            return False
    
    def _process_notifications(self, numero_telefono):
        """Procesa las notificaciones acumuladas"""
        try:
            if numero_telefono not in self.pending_notifications:
                return
            
            notifications = self.pending_notifications[numero_telefono]
            if not notifications:
                return
            
            print(f"📤 Procesando {len(notifications)} notificaciones para {numero_telefono}")
            
            # Separar consolidadas de individuales
            consolidated_notifications = [n for n in notifications if n.get("is_consolidated", False)]
            individual_notifications = [n for n in notifications if not n.get("is_consolidated", False)]
            
            # Procesar consolidadas
            if consolidated_notifications:
                print(f"📦 Procesando {len(consolidated_notifications)} notificaciones consolidadas")
                for notif in consolidated_notifications:
                    self._send_consolidated_notification(numero_telefono, notif)
            
            # Procesar individuales
            if individual_notifications:
                print(f"📄 Procesando {len(individual_notifications)} notificaciones individuales")
                if len(individual_notifications) == 1:
                    self._send_single_notification(numero_telefono, individual_notifications[0])
                else:
                    self._send_notification_list(numero_telefono, individual_notifications)
            
            # Limpiar buffer
            if numero_telefono in self.timers:
                del self.timers[numero_telefono]
            
            del self.pending_notifications[numero_telefono]
                
        except Exception as e:
            print(f"❌ Error procesando notificaciones: {e}")
            import traceback
            traceback.print_exc()
    
    def _send_consolidated_notification(self, numero_telefono, notification):
        """Envía notificación consolidada"""
        try:
            from services.chatbot_service import enviar_mensaje_whatsapp
            
            payload = notification["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            
            cantidad_docs = payload.get("cantidad", 0)
            documentos = payload.get("documentos", [])
            
            print(f"📨 Enviando notificación consolidada con {cantidad_docs} documentos")
            
            # UN SOLO DOCUMENTO: Mensaje detallado completo
            if cantidad_docs == 1:
                doc_info = documentos[0]
                mensaje_completo = self._generar_mensaje_detallado_completo(doc_info)
                enviado = enviar_mensaje_whatsapp(numero_telefono, mensaje_completo)
                
                if enviado:
                    notification_to_save = {
                        "mensaje": mensaje_completo,
                        "payload": doc_info,
                        "tipo": "documento_en_espera",
                        "timestamp": notification["timestamp"],
                        "id": notification["id"],
                        "viewed": False
                    }
                    self._save_single_notification_to_memory(numero_telefono, notification_to_save)
                    
                    mensaje_opcion = "\n💬 Responde 'contactar encargado' si necesitas comunicarte con el responsable."
                    enviar_mensaje_whatsapp(numero_telefono, mensaje_opcion)
            
            # MÚLTIPLES DOCUMENTOS: Lista resumida
            else:
                mensaje_lista = f"📢 **Tienes {cantidad_docs} documentos en espera de atención:**\n\n"
                
                for i, doc_info in enumerate(documentos, 1):
                    doc = doc_info.get("documento", {})
                    creador = doc_info.get("creador", {})
                    
                    nombre_creador = f"{creador.get('nombres', '')} {creador.get('apellido_paterno', '')}".strip() if creador else "N/A"
                    
                    asunto = doc.get('asunto', 'Sin asunto')
                    asunto_corto = asunto[:40] + '...' if len(asunto) > 40 else asunto
                    
                    mensaje_lista += f"{i}. 🚨 **{doc.get('codigo_sistema', 'N/A')}**\n"
                    mensaje_lista += f"   📋 {asunto_corto}\n"
                    mensaje_lista += f"   👤 {nombre_creador}\n\n"
                
                mensaje_lista += "💡 **Responde con el número (1, 2, 3...) para ver los detalles completos de ese documento**"
                
                enviado = enviar_mensaje_whatsapp(numero_telefono, mensaje_lista)
                
                if enviado:
                    self._save_consolidated_to_memory(numero_telefono, notification, mensaje_lista, documentos)
            
        except Exception as e:
            print(f"❌ Error enviando notificación consolidada: {e}")
            import traceback
            traceback.print_exc()
    
    def _generar_mensaje_detallado_completo(self, doc_info):
        """Genera mensaje detallado COMPLETO para un documento"""
        doc = doc_info.get("documento", {})
        proyecto = doc_info.get("proyecto", {})
        encargados = doc_info.get("encargados", [])
        responsables = doc_info.get("responsables", [])
        
        # Formatear encargados
        encargados_texto = ""
        if encargados and len(encargados) > 0:
            if len(encargados) == 1:
                e = encargados[0]
                encargados_texto = f"{e.get('nombres', '')} {e.get('apellido_paterno', '')}".strip()
            else:
                encargados_texto = "\n".join([f"• {e.get('nombres', '')} {e.get('apellido_paterno', '')}".strip() for e in encargados])
        
        # Formatear responsables
        responsables_texto = ""
        if responsables and len(responsables) > 0:
            if len(responsables) == 1:
                r = responsables[0]
                responsables_texto = f"{r.get('nombre', '')} {r.get('apellido_paterno', '')}".strip()
            else:
                responsables_texto = "\n".join([f"• {r.get('nombre', '')} {r.get('apellido_paterno', '')}".strip() for r in responsables])

        encargados_section = (
            f"👤 Encargado{'s' if len(encargados) > 1 else ''}:\n{encargados_texto}"
            if encargados_texto
            else "👤 No hay encargado asignado"
        )

        responsables_section = (
            f"🏗️ Responsable{'s' if len(responsables) > 1 else ''} del proyecto:\n{responsables_texto}"
            if responsables_texto
            else ""
        )
        
        # Extraer nombre del proyecto correctamente
        proyecto_nombre = proyecto.get('nombre', 'N/A') if isinstance(proyecto, dict) else str(proyecto)
        
        mensaje = f"""⚠️ *Alerta de Documento* ⚠️
⏱️ Han pasado *15 días sin movimiento*.  
Por favor, revisa y actualiza su estado a *"Atendido"* si corresponde. 🙏

📄 *Documento*: {doc.get('numero_documento', 'N/A')}  
🆔 *Código sistema*: {doc.get('codigo_sistema', 'N/A')}  
📋 *Asunto:* {doc.get('asunto', 'N/A')}  
🏗️ *Proyecto:* {proyecto_nombre}  
👤 *Encargado:* {encargados_texto or 'N/A'}  
🔄 *Estado*: {doc.get('estado', 'N/A')}  
📅 *Fecha Ingreso*: {doc.get('fecha_ingreso', 'N/A')}  

💡 *¿Quieres contactar?*  
{encargados_section}

{responsables_section}"""
        
        return mensaje.strip()
    
    def _send_single_notification(self, numero_telefono, notification):
        """Envía una sola notificación"""
        try:
            from services.chatbot_service import enviar_mensaje_whatsapp
            enviado = enviar_mensaje_whatsapp(numero_telefono, notification["mensaje"])
            
            self._save_single_notification_to_memory(numero_telefono, notification)
            
            if enviado and notification["tipo"] == "alerta":
                mensaje_opcion = "\n💬 Responde 'contactar encargado' si necesitas comunicarte con el responsable del proyecto."
                enviar_mensaje_whatsapp(numero_telefono, mensaje_opcion)
            
        except Exception as e:
            print(f"❌ Error enviando notificación única: {e}")
    
    def _send_notification_list(self, numero_telefono, notifications):
        """Envía lista de notificaciones múltiples"""
        try:
            from services.chatbot_service import enviar_mensaje_whatsapp
            mensaje_lista = f"📢 **Tienes {len(notifications)} notificaciones nuevas:**\n\n"
            
            for i, notif in enumerate(notifications, 1):
                doc_info = self._extract_document_info(notif["payload"])
                tipo_emoji = "🚨" if notif["tipo"] == "alerta" else "📄"
                
                mensaje_lista += f"{i}. {tipo_emoji} **{doc_info['codigo']}**\n"
                mensaje_lista += f"   📋 {doc_info['asunto'][:40]}{'...' if len(doc_info['asunto']) > 40 else ''}\n"
                mensaje_lista += f"   👤 {doc_info['responsable']}\n\n"
            
            mensaje_lista += "💡 **Responde con el número (1, 2, 3...) para ver los detalles de esa notificación**"
            
            enviado = enviar_mensaje_whatsapp(numero_telefono, mensaje_lista)
            
            if enviado:
                self._save_notifications_to_memory(numero_telefono, notifications, mensaje_lista)
                
        except Exception as e:
            print(f"❌ Error enviando lista de notificaciones: {e}")
    
    # ==================== MÉTODOS DE ALMACENAMIENTO ====================
    
    def store_notifications(self, phone_number: str, notifications_data: Dict):
        """Almacena notificaciones agrupadas POR TIPO"""
        try:
            # Inicializar estructura si no existe
            if phone_number not in self.user_notifications:
                self.user_notifications[phone_number] = {
                    "sin_respuesta": [],
                    "sin_firma": [],
                    "inactivos": [],
                    "stand_by": []
                }
            
            # Identificar tipo
            tipo_backend = notifications_data.get('tipo', '')
            tipo_interno = self._identificar_tipo_notificacion(tipo_backend)
            documentos = notifications_data.get('documentos', [])
            
            # Crear grupo de notificación
            notification_group = {
                "id": f"{phone_number}_{tipo_interno}_{int(time.time())}",
                "tipo_interno": tipo_interno,
                "tipo_original": tipo_backend,
                "cantidad": len(documentos),
                "documentos": documentos,
                "timestamp": time.time(),
                "viewed": False,
                "template_sent": False
            }
            
            # Almacenar en lista del tipo correspondiente
            self.user_notifications[phone_number][tipo_interno].append(notification_group)
            
            print(f"📥 [{tipo_interno}] {len(documentos)} docs almacenados para {phone_number}")
            print(f"📊 Total {tipo_interno}: {len(self.user_notifications[phone_number][tipo_interno])} grupos")
            
            return notification_group
            
        except Exception as e:
            print(f"❌ Error almacenando notificación: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_notifications_by_type(self, phone_number: str, tipo_interno: str) -> List[Dict]:
        """Obtiene TODAS las notificaciones de UN TIPO específico (vistas o no)"""
        try:
            # Inicializar si no existe
            if phone_number not in self.user_notifications:
                self.user_notifications[phone_number] = {
                    "sin_respuesta": [],
                    "sin_firma": [],
                    "inactivos": [],
                    "stand_by": []
                }

            notifications = self.user_notifications[phone_number].get(tipo_interno, [])

            print(f"📋 {len(notifications)} notificaciones [{tipo_interno}] para {phone_number}")
            return notifications

        except Exception as e:
            print(f"❌ Error obteniendo notificaciones por tipo: {e}")
            return []

        
    def _save_consolidated_to_memory(self, numero_telefono, notification, mensaje_enviado, documentos):
        """Guarda notificación consolidada MARCANDO como flujo de notificación"""
        try:
            from core.flow import conversation_memory
            
            notifications_for_memory = []
            
            for i, doc_info in enumerate(documentos):
                mensaje_completo = self._generar_mensaje_detallado_completo(doc_info)
                
                notifications_for_memory.append({
                    "id": f"{notification['id']}_doc_{i+1}",
                    "tipo": "documento_en_espera",
                    "mensaje": mensaje_completo,  # 🔥 MENSAJE COMPLETO
                    "payload": doc_info,
                    "timestamp": notification["timestamp"].isoformat() if isinstance(notification["timestamp"], datetime) else str(notification["timestamp"]),
                    "viewed": False,
                    "index": i + 1
                })
            
            print(f"💾 Guardando {len(notifications_for_memory)} documentos en memoria")
            
            conversation_memory.add_turn(
                phone_number=numero_telefono,
                user_message="[system] consolidated_notification",
                bot_response=mensaje_enviado,
                intent="system_notification_list",
                parameters={
                    "notification_count": len(documentos),
                    "notifications": notifications_for_memory,
                    "notification_type": "documentos_en_espera"
                },
                context={
                    "awaiting_notification_selection": True,
                    "available_notifications": notifications_for_memory,
                    "notification_count": len(documentos),
                    "is_consolidated": True,
                    "can_contact_responsible": True
                },
                message_type="notification_list",
                flow="lista_documentos_espera"
            )
            
            # 🔥 MARCAR ESTADO COMO FLUJO DE NOTIFICACIÓN
            conversation_memory.set_conversation_state(
                numero_telefono,
                "awaiting_notification_choice",
                {
                    "notification_count": len(documentos),
                    "notifications_available": True,
                    "has_notification_list": True,
                    "is_consolidated": True,
                    "is_notification_flow": True  # 🔥 ESTO ES CRÍTICO
                }
            )
            
            print(f"✅ Estado marcado como flujo de notificación")
            
        except Exception as e:
            print(f"❌ Error guardando consolidada: {e}")
            import traceback
            traceback.print_exc()
    
    def _save_single_notification_to_memory(self, numero_telefono, notification):
        """Guarda notificación única en memoria"""
        try:
            from core.flow import conversation_memory
            tipo_notificacion = notification["tipo"]
            puede_contactar = tipo_notificacion in ["alerta", "documento_en_espera", "documentos_en_espera"]
            conversation_memory.add_turn(
                phone_number=numero_telefono,
                user_message="[system] single_notification",
                bot_response=notification["mensaje"],
                intent="system_notification",
                parameters={
                    "notification_type": notification["tipo"],
                    "payload": notification["payload"],
                    "notification_id": notification["id"]
                },
                context={
                    "alert_active": puede_contactar,  # 🔥 TRUE para documentos en espera
                    "alert_payload": notification["payload"],  # 🔥 GUARDAR PAYLOAD
                    "notification_timestamp": notification["timestamp"].isoformat() if isinstance(notification["timestamp"], datetime) else str(notification["timestamp"]),
                    "can_contact_responsible": puede_contactar  # 🔥 MARCAR COMO CONTACTABLE
                },
                message_type="notification",
                flow="notificacion_unica"
            )
            
            print(f"✅ Notificación única guardada en memoria")
            
        except Exception as e:
            print(f"❌ Error guardando notificación única: {e}")
    
    def _save_notifications_to_memory(self, numero_telefono, notification, mensaje_enviado, documentos):
        """Guarda lista de notificaciones en memoria"""
        try:
            from core.flow import conversation_memory
            
            notifications_for_memory = []
            for i, doc_info in enumerate(documentos):
                mensaje_completo = self._generar_mensaje_detallado_completo(doc_info)
                
                notifications_for_memory.append({
                    "id": f"{notification['id']}_doc_{i+1}",
                    "tipo": "documento_en_espera",  # 🔥 TIPO CONSISTENTE
                    "mensaje": mensaje_completo,
                    "payload": doc_info,  # 🔥 PAYLOAD COMPLETO con encargados
                    "timestamp": notification["timestamp"].isoformat() if isinstance(notification["timestamp"], datetime) else str(notification["timestamp"]),
                    "viewed": False,
                    "index": i + 1
                })

            print(f"💾 Guardando {len(notifications_for_memory)} documentos en memoria con mensajes completos")

            
            conversation_memory.add_turn(
            phone_number=numero_telefono,
            user_message="[system] consolidated_notification",
            bot_response=mensaje_enviado,
            intent="system_notification_list",
            parameters={
                "notification_count": len(documentos),
                "notifications": notifications_for_memory,
                "notification_type": "documentos_en_espera"
            },
            context={
                "awaiting_notification_selection": True,
                "available_notifications": notifications_for_memory,
                "notification_count": len(documentos),
                "is_consolidated": True,
                "can_contact_responsible": True  # 🔥 MARCAR COMO CONTACTABLE
            },
            message_type="notification_list",
            flow="lista_documentos_espera"
        )
        
            conversation_memory.set_conversation_state(
                numero_telefono,
                "awaiting_notification_choice",
                {
                    "notification_count": len(documentos),
                    "notifications_available": True,
                    "has_notification_list": True,
                    "is_consolidated": True
                }
            )
            
            print(f"✅ {len(documentos)} notificaciones guardadas en memoria con mensajes completos")
            
        except Exception as e:
            print(f"❌ Error guardando consolidada en memoria: {e}")
            import traceback
            traceback.print_exc()
    
    # ==================== MÉTODOS DE CONSULTA ====================
    
    def get_notification_by_index(self, numero_telefono: str, index):
        """Busca notificación/documento por índice o código EN TODOS LOS TIPOS"""
        try:
            print(f"🔍 Buscando notificación #{index} para {numero_telefono}")
            
            # Normalizar índice
            is_numeric = False
            try:
                idx = int(index)
                is_numeric = True
            except (ValueError, TypeError):
                idx = None
            
            # 1) BUSCAR EN NOTIFICACIONES ALMACENADAS (todos los tipos)
            if numero_telefono in self.user_notifications:
                for tipo in ["sin_respuesta", "sin_firma", "inactivos", "stand_by"]:
                    notifications = self.user_notifications[numero_telefono][tipo]
                    
                    for notif in notifications:
                        documentos = notif.get('documentos', [])
                        
                        # Búsqueda por índice numérico
                        if is_numeric and 1 <= idx <= len(documentos):
                            doc = documentos[idx - 1]
                            print(f"✅ Encontrado [índice {idx}] en tipo: {tipo}")
                            return self._convertir_documento_a_notificacion(doc, notif)
                        
                        # Búsqueda por código
                        for doc_info in documentos:
                            doc = doc_info.get('documento', {})
                            codigo = doc.get('codigo_sistema')
                            if str(codigo) == str(index):
                                print(f"✅ Encontrado [código {codigo}] en tipo: {tipo}")
                                return self._convertir_documento_a_notificacion(doc_info, notif)
            
            # 2) BUSCAR EN DOCUMENTOS GUARDADOS EN MEMORIA
            from core.flow import conversation_memory
            documentos_guardados = conversation_memory.get_conversation_documents(numero_telefono)
            
            if documentos_guardados:
                print(f"📦 Buscando en {len(documentos_guardados)} documentos guardados...")
                
                # Índice numérico
                if is_numeric and 1 <= idx <= len(documentos_guardados):
                    doc = documentos_guardados[idx - 1]
                    print(f"✅ Encontrado en docs guardados [índice {idx}]")
                    return self._convertir_documento_a_notificacion(doc)
                
                # Por código
                for doc in documentos_guardados:
                    codigo_doc = doc.get("codigo_sistema") or doc.get("documento", {}).get("codigo_sistema")
                    if str(codigo_doc) == str(index):
                        print(f"✅ Encontrado en docs guardados [código {codigo_doc}]")
                        return self._convertir_documento_a_notificacion(doc)
            
            print(f"❌ No se encontró notificación para '{index}'")
            return None
            
        except Exception as e:
            print(f"❌ Error buscando notificación: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _convertir_documento_a_notificacion(self, doc_info, notification=None):
        """Convierte un documento a formato de notificación"""
        try:
            documento_data = doc_info.get('documento', {})
            proyecto_data = doc_info.get('proyecto', {})
            encargados = doc_info.get('encargados', [])
            responsables = doc_info.get('responsables', [])
            
            return {
                'id': f"doc_{documento_data.get('id', 'unknown')}",
                'codigo_sistema': documento_data.get('codigo_sistema'),
                'numero_documento': documento_data.get('numero_documento'),
                'tipo': notification.get('tipo_interno') if notification else 'documento',
                'timestamp': notification.get('timestamp') if notification else time.time(),
                'payload': {
                    'documento': documento_data,
                    'proyecto': proyecto_data,
                    'encargados': encargados,
                    'responsables': responsables
                },
                'viewed': False
            }
            
        except Exception as e:
            print(f"❌ Error convirtiendo documento: {e}")
            return None
    
    def get_pending_notifications(self, phone_number: str) -> List[Dict]:
        """Obtiene TODAS las notificaciones pendientes (todos los tipos)"""
        all_pending = []
        
        if phone_number not in self.user_notifications:
            return []
        
        for tipo in ["sin_respuesta", "sin_firma", "inactivos", "stand_by"]:
            notifications = self.get_notifications_by_type(phone_number, tipo)
            all_pending.extend(notifications)
        
        return all_pending

    def mark_notification_as_viewed(self, numero_telefono: str, notification_id: str):
        """Marca una notificación como vista EN TODOS LOS TIPOS"""
        try:
            if numero_telefono not in self.user_notifications:
                return False
            
            # Buscar en todos los tipos
            for tipo in ["sin_respuesta", "sin_firma", "inactivos", "stand_by"]:
                for notif in self.user_notifications[numero_telefono][tipo]:
                    if notif['id'] == notification_id:
                        notif['viewed'] = True
                        self.viewed_notifications.add(notification_id)
                        print(f"✅ Notificación {notification_id} [{tipo}] marcada como vista")
                        return True
            
            # También marcar en memoria conversacional
            from core.flow import conversation_memory
            if hasattr(conversation_memory, 'conversations') and numero_telefono in conversation_memory.conversations:
                for turn in conversation_memory.conversations[numero_telefono]:
                    if turn.intent == "system_notification_list":
                        notifications = turn.context.get('available_notifications', [])
                        for notif in notifications:
                            if notif.get("id") == notification_id:
                                notif["viewed"] = True
                                break
            
            return False
            
        except Exception as e:
            print(f"❌ Error marcando notificación: {e}")
            return False
    
  
    # ==================== MÉTODOS DE FORMATEO ====================
    
    def format_notification_list(self, phone_number: str) -> str:
        """Formatea lista de TODAS las notificaciones pendientes"""
        pending = self.get_pending_notifications(phone_number)
        
        if not pending:
            return "📭 No tienes notificaciones pendientes."
        
        mensaje = "🔔 *Tus Notificaciones Pendientes:*\n\n"
        
        for idx, notif in enumerate(pending, 1):
            tipo = notif.get('tipo_interno', 'desconocido')
            cantidad = notif.get('cantidad', 0)
            timestamp = notif.get('timestamp', time.time())
            tipo_config = self._get_tipo_config(tipo)
            
            fecha = datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %H:%M")
            
            mensaje += f"{idx}. {tipo_config['emoji']} {tipo_config['nombre']}\n"
            mensaje += f"   📊 {cantidad} documentos\n"
            mensaje += f"   📅 {fecha}\n\n"
        
        mensaje += "💡 *Escribe el número o el tipo para ver detalles*"
        return mensaje
    
    def _extract_document_info(self, payload):
        """Extrae información básica del documento"""
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)
            
            doc = payload.get("documento", {})
            
            return {
                "codigo": doc.get("codigo_sistema", doc.get("numero_documento", "N/A")),
                "asunto": doc.get("asunto", "Sin asunto"),
                "responsable": self._get_responsible_name(payload)
            }
        except:
            return {
                "codigo": "N/A",
                "asunto": "Notificación del sistema",
                "responsable": "Sin asignar"
            }
    
    def _get_responsible_name(self, payload):
        """Obtiene el nombre del responsable"""
        try:
            if "encargados" in payload and payload["encargados"]:
                encargado = payload["encargados"][0]
                return f"{encargado.get('nombres', '')} {encargado.get('apellido_paterno', '')}".strip()
            return "Sin asignar"
        except:
            return "Sin asignar"
        



# Instancia global del gestor de notificaciones
notification_manager = NotificationManager()