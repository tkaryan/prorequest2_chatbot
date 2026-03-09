"""
services/notification_manager.py
──────────────────────────────────
Responsabilidad: almacenar y recuperar notificaciones entrantes del backend.

NO resuelve selecciones de usuario (eso es flow.py → _resolver_seleccion).
NO accede a conversation_memory (evita import circular).
NO duplica documentos entre fuentes.
"""

import time
from enum import Enum
from typing import Dict, List, Optional


# ── TIPOS ─────────────────────────────────────────────────────────────────────

class TipoNotificacion(Enum):
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

TIPOS_VALIDOS = ["sin_respuesta", "sin_firma", "inactivos", "stand_by"]


# ── MANAGER ───────────────────────────────────────────────────────────────────

class NotificationManager:

    def __init__(self):
        self.user_notifications: Dict[str, Dict[str, List[Dict]]] = {}
        self.viewed_notifications: set = set()

    # ── Almacenamiento ────────────────────────────────────────────────────────

    def store_notifications(self, phone_number: str, notifications_data: Dict) -> Optional[Dict]:
        """Almacena un grupo de notificaciones entrantes agrupado por tipo."""
        try:
            self._init_user(phone_number)

            tipo_backend = notifications_data.get('tipo', '')
            tipo_interno = self._identificar_tipo(tipo_backend)
            documentos   = notifications_data.get('documentos', [])

            group = {
                "id":            f"{phone_number}_{tipo_interno}_{int(time.time())}",
                "tipo_interno":  tipo_interno,
                "tipo_original": tipo_backend,
                "cantidad":      len(documentos),
                "documentos":    documentos,
                "timestamp":     time.time(),
                "viewed":        False,
                "template_sent": False,
            }

            self.user_notifications[phone_number][tipo_interno].append(group)
            print(f"📥 [{tipo_interno}] {len(documentos)} docs → {phone_number} "
                  f"(grupos: {len(self.user_notifications[phone_number][tipo_interno])})")
            return group

        except Exception as e:
            print(f"❌ Error en store_notifications: {e}")
            return None

    # ── Consulta ──────────────────────────────────────────────────────────────

    def get_notifications_by_type(self, phone_number: str, tipo_interno: str) -> List[Dict]:
        """Retorna todos los grupos de un tipo (vistos o no)."""
        self._init_user(phone_number)
        notifications = self.user_notifications[phone_number].get(tipo_interno, [])
        print(f"📋 {len(notifications)} grupos [{tipo_interno}] para {phone_number}")
        return notifications

    def get_all_documents_by_type(self, phone_number: str, tipo_interno: str) -> List[Dict]:
        """
        Consolida todos los documentos de un tipo en una lista plana.
        Usado por handle_notificaciones para guardar en conversation_memory.
        """
        self._init_user(phone_number)
        documentos = []
        for group in self.user_notifications[phone_number].get(tipo_interno, []):
            documentos.extend(group.get("documentos", []))
        print(f"📦 {len(documentos)} docs consolidados [{tipo_interno}] para {phone_number}")
        return documentos

    def has_notifications(self, phone_number: str, tipo_interno: str) -> bool:
        self._init_user(phone_number)
        return bool(self.user_notifications[phone_number].get(tipo_interno))

    # ── Vista ─────────────────────────────────────────────────────────────────

    def mark_notification_as_viewed(self, phone_number: str, notification_id: str) -> bool:
        """Marca un grupo de notificación como visto."""
        if phone_number not in self.user_notifications:
            return False

        for tipo in TIPOS_VALIDOS:
            for notif in self.user_notifications[phone_number].get(tipo, []):
                if notif['id'] == notification_id:
                    notif['viewed'] = True
                    self.viewed_notifications.add(notification_id)
                    print(f"✅ Notificación {notification_id} [{tipo}] marcada como vista")
                    return True

        print(f"⚠️  Notificación {notification_id} no encontrada para marcar como vista")
        return False

    # ── Formato ───────────────────────────────────────────────────────────────

    def format_notifications_by_type(self, phone_number: str, tipo_interno: str) -> str:
        """
        Genera un resumen de cuántas notificaciones hay por tipo.
        Usado cuando hay múltiples grupos del mismo tipo.
        """
        self._init_user(phone_number)
        groups = self.user_notifications[phone_number].get(tipo_interno, [])

        if not groups:
            tipo_label = tipo_interno.replace("_", " ").title()
            return f"✅ No tienes notificaciones de tipo '{tipo_label}'."

        total_docs = sum(g.get("cantidad", 0) for g in groups)
        tipo_label = tipo_interno.replace("_", " ").title()

        lines = [f"📋 *Notificaciones: {tipo_label}*\n"]
        for i, g in enumerate(groups, 1):
            ts = time.strftime('%d/%m/%Y %H:%M', time.localtime(g["timestamp"]))
            visto = "✓" if g["viewed"] else "•"
            lines.append(f"{visto} Grupo {i}: {g['cantidad']} documentos ({ts})")

        lines.append(f"\n_Total: {total_docs} documentos en {len(groups)} grupo(s)_")
        return "\n".join(lines)

    # ── Helpers privados ──────────────────────────────────────────────────────

    def _init_user(self, phone_number: str) -> None:
        if phone_number not in self.user_notifications:
            self.user_notifications[phone_number] = {t: [] for t in TIPOS_VALIDOS}

    def _identificar_tipo(self, tipo_backend: str) -> str:
        tipo_lower = tipo_backend.lower()
        for tipo_enum in TipoNotificacion:
            if tipo_lower in [t.lower() for t in tipo_enum.value["tipos_backend"]]:
                return tipo_enum.name.lower()
        print(f"⚠️  Tipo backend desconocido '{tipo_backend}', usando 'inactivos' por defecto")
        return "inactivos"


notification_manager = NotificationManager()