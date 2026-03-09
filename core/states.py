"""
core/states.py — Fuente única de verdad para estados FSM.

Flujo normal:
  INITIAL → (búsqueda múltiple) → AWAITING_SELECTION
          → (único resultado)   → AWAITING_CONFIRMATION → INITIAL

Flujo notificación:
  INITIAL → (botón plantilla)  → AWAITING_SELECTION
          → (usuario elige)    → AWAITING_CONFIRMATION → INITIAL

SEARCHING: estado intermedio, tiene resultados en memoria pero puede hacer nueva búsqueda.
"""


class State:
    INITIAL               = "INITIAL"
    SEARCHING             = "SEARCHING"
    AWAITING_SELECTION    = "AWAITING_SELECTION"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"


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