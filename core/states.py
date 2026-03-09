"""
core/states.py
──────────────
Fuente única de verdad para los estados FSM del chatbot.

Flujo normal:
  INITIAL → (búsqueda) → SEARCHING → (lista) → AWAITING_SELECTION
          → (único resultado) → AWAITING_CONFIRMATION → INITIAL

Flujo notificación:
  INITIAL → (notificación llega) → AWAITING_SELECTION
          → (usuario selecciona) → AWAITING_CONFIRMATION → INITIAL
"""


class State:
    INITIAL               = "INITIAL"
    SEARCHING             = "SEARCHING"          # Tiene resultados activos en memoria
    AWAITING_SELECTION    = "AWAITING_SELECTION"  # Esperando que el usuario elija de una lista
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"  # Esperando sí/no tras ver un documento


PREGUNTA_SELECCION = (
    "¿En cuál de los documentos requieres información?\n\n"
    "💡 Escribe el número o describe cuál buscas.\n"
    "Si quieres iniciar una nueva búsqueda, escribe *'Hola'*"
)

PREGUNTA_CONFIRMACION = "¿El documento es lo que estabas buscando?"

MENSAJE_POST_CONFIRMACION = (
    "Perfecto! ¿En qué más puedo ayudarte?\n"
    "Si quieres iniciar una nueva búsqueda, escribe *'Hola'*"
)

MENSAJE_VOLVER_LISTA = (
    "Entendido. ¿Cuál de los documentos anteriores te interesa?\n\n"
    "💡 Escribe el número o describe cuál buscas.\n"
    "Si quieres iniciar una nueva búsqueda, escribe *'Hola'*"
)