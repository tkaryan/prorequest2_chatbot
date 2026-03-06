# notification_manager.py 
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
                    "mensaje": mensaje_completo,  # MENSAJE COMPLETO
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
            
            # MARCAR ESTADO COMO FLUJO DE NOTIFICACIÓN
            conversation_memory.set_conversation_state(
                numero_telefono,
                "awaiting_notification_choice",
                {
                    "notification_count": len(documentos),
                    "notifications_available": True,
                    "has_notification_list": True,
                    "is_consolidated": True,
                    "is_notification_flow": True  
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
                    "alert_active": puede_contactar, 
                    "alert_payload": notification["payload"],  
                    "notification_timestamp": notification["timestamp"].isoformat() if isinstance(notification["timestamp"], datetime) else str(notification["timestamp"]),
                    "can_contact_responsible": puede_contactar 
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
                    "tipo": "documento_en_espera",  
                    "mensaje": mensaje_completo,
                    "payload": doc_info,  
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
                "can_contact_responsible": True  
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
        
    def get_notification_by_index(self, numero_telefono: str, index):
        """
        Busca notificación/documento por índice, código, asunto o cualquier campo.
        """
        try:
            print(f"🔍 Buscando notificación '{index}' para {numero_telefono}")

            is_numeric = False
            idx = None
            query_str = str(index).strip() if index is not None else ""

            try:
                idx = int(query_str)
                is_numeric = True
            except (ValueError, TypeError):
                pass

            todos_los_docs = self._consolidar_todos_documentos(numero_telefono)
            if not todos_los_docs:
                print(f"❌ No hay documentos disponibles para {numero_telefono}")
                return None

            print(f"📦 Total documentos disponibles: {len(todos_los_docs)}")

            if is_numeric and 1 <= idx <= len(todos_los_docs):
                doc = todos_los_docs[idx - 1]
                print(f"✅ Encontrado por posición #{idx}")
                return self._convertir_documento_a_notificacion(doc.get("_raw"), doc.get("_notif_parent"))

            resultado = self._buscar_por_score(todos_los_docs, query_str)
            if resultado:
                print(f"✅ Encontrado por score flexible")
                return self._convertir_documento_a_notificacion(
                    resultado.get("_raw"), resultado.get("_notif_parent")
                )

            print(f"⚠️  Búsqueda local falló, usando Gemini para resolver '{query_str}'...")
            resultado_gemini = self._resolver_con_gemini(todos_los_docs, query_str)
            if resultado_gemini:
                print(f"✅ Gemini identificó el documento")
                return self._convertir_documento_a_notificacion(
                    resultado_gemini.get("_raw"), resultado_gemini.get("_notif_parent")
                )

            print(f"❌ No se encontró notificación para '{index}'")
            return None

        except Exception as e:
            print(f"❌ Error buscando notificación: {e}")
            import traceback
            traceback.print_exc()
            return None


    def _consolidar_todos_documentos(self, numero_telefono: str) -> list:
        """
        Consolida documentos de TODAS las fuentes en una lista plana.
        Cada item tiene: campos del doc + _raw (doc original) + _notif_parent.
        """
        resultado = []

        if numero_telefono in self.user_notifications:
            for tipo in ["sin_respuesta", "sin_firma", "inactivos", "stand_by"]:
                notifications = self.user_notifications[numero_telefono].get(tipo, [])
                for notif in notifications:
                    for doc_info in notif.get("documentos", []):
                        doc = doc_info.get("documento", doc_info)
                        entrada = {
                            "codigo_sistema":     doc.get("codigo_sistema", ""),
                            "numero_documento":   doc.get("numero_documento", ""),
                            "numero_consecutivo": doc.get("numero_consecutivo", ""),
                            "asunto":             doc.get("asunto", ""),
                            "tipo":               doc.get("tipo", ""),
                            "proyecto_nombre":    doc.get("proyecto_nombre", ""),
                            "estado_flujo":       doc.get("estado_flujo", ""),
                            "_tipo_notif":        tipo,
                            "_raw":               doc_info,
                            "_notif_parent":      notif,
                        }
                        encargados = notif.get("encargados", []) or doc.get("encargados", []) or []
                        nombres_enc = []
                        for enc in encargados:
                            if isinstance(enc, dict):
                                nombres_enc.append(
                                    f"{enc.get('nombres','')} {enc.get('apellido_paterno','')}".strip()
                                )
                        entrada["_encargados_texto"] = " ".join(nombres_enc).lower()
                        resultado.append(entrada)

        try:
            from core.flow import conversation_memory
            docs_guardados = conversation_memory.get_conversation_documents(numero_telefono)
            for doc in docs_guardados:
                doc_inner = doc.get("documento", doc)
                entrada = {
                    "codigo_sistema":     doc_inner.get("codigo_sistema", "") or doc.get("codigo_sistema", ""),
                    "numero_documento":   doc_inner.get("numero_documento", "") or doc.get("numero_documento", ""),
                    "numero_consecutivo": doc_inner.get("numero_consecutivo", "") or doc.get("numero_consecutivo", ""),
                    "asunto":             doc_inner.get("asunto", "") or doc.get("asunto", ""),
                    "tipo":               doc_inner.get("tipo", "") or doc.get("tipo", ""),
                    "proyecto_nombre":    doc_inner.get("proyecto_nombre", "") or doc.get("proyecto_nombre", ""),
                    "_tipo_notif":        "memory",
                    "_raw":               doc,
                    "_notif_parent":      None,
                    "_encargados_texto":  str(doc.get("encargados", "")).lower(),
                }
                resultado.append(entrada)
        except Exception as e:
            print(f"⚠️  Error cargando docs de memoria: {e}")

        return resultado


    def _buscar_por_score(self, todos_los_docs: list, query: str) -> dict | None:
        """
        Scoring flexible:
        - Coincidencia exacta:    peso 20
        - Substring completo:     peso 10 (codigo_sistema / numero_documento)
        - Substring en asunto:    peso  5
        - Substring en proyecto:  peso  3
        - Substring en encargado: peso  3
        - Fragmentos separados:   peso  2 por fragmento (ej: "10922" en "10922-MEP-CMA-GP-206-2025")
        """
        query_lower = query.lower().strip()

        import re
        fragmentos = [f for f in re.split(r'[-_/\s]+', query_lower) if len(f) >= 3]

        candidates = []

        for doc in todos_los_docs:
            score = 0

            campos_exactos = [
                ("codigo_sistema",     20, 10),
                ("numero_documento",   20, 10),
                ("numero_consecutivo", 18,  8),
            ]
            campos_parciales = [
                ("asunto",          5),
                ("proyecto_nombre", 3),
                ("tipo",            3),
            ]

            for campo, peso_exacto, peso_substr in campos_exactos:
                valor = str(doc.get(campo) or "").lower().strip()
                if not valor:
                    continue
                if valor == query_lower:
                    score += peso_exacto
                elif query_lower in valor or valor in query_lower:
                    score += peso_substr
                else:
                    for frag in fragmentos:
                        if frag in valor:
                            score += 2

            for campo, peso in campos_parciales:
                valor = str(doc.get(campo) or "").lower()
                if query_lower in valor:
                    score += peso
                else:
                    for frag in fragmentos:
                        if frag in valor:
                            score += 1

            enc_texto = doc.get("_encargados_texto", "")
            if query_lower in enc_texto:
                score += 3
            else:
                for frag in fragmentos:
                    if frag in enc_texto:
                        score += 1

            if score > 0:
                candidates.append((score, doc))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_doc = candidates[0]
        print(f"🎯 Mejor score: {best_score} → {best_doc.get('codigo_sistema')} | {best_doc.get('numero_documento')}")
        return best_doc


    def _resolver_con_gemini(self, todos_los_docs: list, query: str) -> dict | None:
        """
        Usa Gemini para identificar qué documento corresponde al texto del usuario.
        Solo se llama cuando la búsqueda local no encontró nada.
        """
        try:
            import requests, json, os
            from config import GEMINI_API_KEY, GEMINI_URL

            lista_docs = []
            for i, doc in enumerate(todos_los_docs[:30]):  
                lista_docs.append({
                    "posicion":           i + 1,
                    "codigo_sistema":     doc.get("codigo_sistema", ""),
                    "numero_documento":   doc.get("numero_documento", ""),
                    "numero_consecutivo": doc.get("numero_consecutivo", ""),
                    "asunto":             (doc.get("asunto") or "")[:80],
                    "tipo":               doc.get("tipo", ""),
                    "proyecto":           doc.get("proyecto_nombre", ""),
                })

            prompt = f"""
    Tengo una lista de documentos y el usuario escribió: "{query}"

    Tu tarea: identificar CUÁL documento corresponde a lo que escribió el usuario.
    El usuario pudo haber escrito: un número de posición (1,2,3), un código parcial, 
    parte del número de documento, parte del asunto, nombre del proyecto, etc.

    DOCUMENTOS DISPONIBLES:
    {json.dumps(lista_docs, ensure_ascii=False, indent=2)}

    Responde SOLO con JSON válido:
    {{
    "encontrado": true/false,
    "posicion": <número de posición 1-based, o null>,
    "razon": "<por qué coincide>"
    }}
    """

            headers = {
                "Content-Type": "application/json",
                "X-goog-api-key": GEMINI_API_KEY
            }
            data = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 200,
                    "responseMimeType": "application/json"
                }
            }

            response = requests.post(GEMINI_URL, headers=headers, json=data, timeout=15)

            if response.status_code == 200:
                content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                resultado = json.loads(content)
                print(f"🤖 Gemini responde: {resultado}")

                if resultado.get("encontrado") and resultado.get("posicion"):
                    pos = int(resultado["posicion"]) - 1
                    if 0 <= pos < len(todos_los_docs):
                        return todos_los_docs[pos]

            return None

        except Exception as e:
            print(f"❌ Error llamando Gemini para resolver notificación: {e}")
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
        



notification_manager = NotificationManager()