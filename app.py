"""
app.py
──────
Punto de entrada Flask. Solo rutas — sin lógica de negocio.
Toda la lógica vive en services/.
"""

import threading
from flask import Flask, request, jsonify

from handlers.whatsapp_handler import handle_webhook_get, handle_webhook_post
from handlers.notificacion_handler import handle_notificacion, handle_notificacion_derivado
from services.notificacion_services import notification_manager



app = Flask(__name__)


# ── WhatsApp Webhook ──────────────────────────────────────────────────────────

@app.route('/whatsapp/webhook', methods=['GET', 'POST'])
def whatsapp_webhook():
    if request.method == 'GET':
        return handle_webhook_get(request)
    return handle_webhook_post(request)


# ── Notificaciones ────────────────────────────────────────────────────────────

@app.route('/api/notificacion', methods=['POST'])
def recibir_notificacion():
    return handle_notificacion(request)


@app.route('/api/notificacion/derivado', methods=['POST'])
def recibir_notificacion_derivado():
    return handle_notificacion_derivado(request)


# ── Limpieza periódica ────────────────────────────────────────────────────────

def _schedule_cleanup():
    notification_manager.limpiar_notificaciones_antiguas()
    t = threading.Timer(1800, _schedule_cleanup)
    t.daemon = True
    t.start()

_schedule_cleanup()


if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')