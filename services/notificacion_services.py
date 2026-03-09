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
                return tipo_enum.name.lower()
        
        # Default
        return "inactivos"
 

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
    

    def limpiar_notificaciones_antiguas(self):
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

# ── Métodos faltantes — agregar a NotificationManager ────────────────────

    def get_all_documents_by_type(self, phone_number: str, tipo_interno: str) -> list:
        """
        Aplana todos los documentos de un tipo en una lista plana.
        Usado como fallback en chatbot_service cuando conversation_memory está vacío.
        """
        self._init_user(phone_number)
        documentos = []
        for group in self.user_notifications[phone_number].get(tipo_interno, []):
            documentos.extend(group.get("documentos", []))
        print(f"📦 {len(documentos)} docs consolidados [{tipo_interno}] para {phone_number}")
        return documentos

    def _identificar_tipo(self, tipo_backend: str) -> str:
        """Alias público de _identificar_tipo_notificacion (compatibilidad)."""
        return self._identificar_tipo_notificacion(tipo_backend)

    def _init_user(self, phone_number: str) -> None:
        """Inicializa estructura del usuario si no existe."""
        if phone_number not in self.user_notifications:
            self.user_notifications[phone_number] = {
                "sin_respuesta": [],
                "sin_firma": [],
                "inactivos": [],
                "stand_by": [],
            }
  



notification_manager = NotificationManager()