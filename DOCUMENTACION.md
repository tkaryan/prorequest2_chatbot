# 📚 Documentación Completa - Chatbot WhatsApp ProRequest

**Última Actualización:** 4 de Marzo de 2026  
**Versión:** 1.0  
**Lenguaje:** Python 3.x

---

## 📋 Tabla de Contenidos

1. [Descripción General](#descripción-general)
2. [Estructura del Proyecto](#estructura-del-proyecto)
3. [Dependencias](#dependencias)
4. [Configuración](#configuración)
5. [Endpoints API](#endpoints-api)
6. [Módulos Principales](#módulos-principales)
7. [Flujo de Conversación](#flujo-de-conversación)
8. [Gestión de Memoria](#gestión-de-memoria)
9. [Servicios](#servicios)
10. [Funciones Clave](#funciones-clave)
11. [Funciones No Utilizadas](#funciones-no-utilizadas)
12. [Ejemplo de Uso](#ejemplo-de-uso)

---

## 🎯 Descripción General

El **Chatbot WhatsApp ProRequest** es un sistema inteligente de conversación que se integra con la plataforma de gestión de documentos **ProRequest**. Su propósito principal es:

- **Responder consultas de usuarios** sobre el estado de documentos y proyectos
- **Enviar notificaciones automáticas** sobre cambios en documentos
- **Mantener contexto conversacional** para brindar respuestas más personalizadas
- **Integrar inteligencia artificial** para detectar intenciones del usuario
- **Gestionar búsquedas avanzadas** en base de datos de documentos

### Características Principales

✅ **Memoria Conversacional Avanzada** - Mantiene contexto de hasta 10 turnos  
✅ **Detección de Intención con IA** - Usa Google Gemini API para entender intenciones  
✅ **Soporte para Notificaciones en Masa** - Agrupa documentos por usuario  
✅ **Plantillas de WhatsApp Business** - Envío de mensajes formateados desde Meta  
✅ **Búsqueda Inteligente** - Integración con Algolia para búsquedas avanzadas  
✅ **Seguimiento de Documentos** - Por número, código, proyecto o asunto  
✅ **Sistema de Roles** - Diferentes niveles de acceso según usuario  

---

## 📁 Estructura del Proyecto

```
chatbot/
├── app.py                           # Archivo principal con endpoints Flask
├── requirements.txt                 # Dependencias del proyecto
├── .env                            # Variables de entorno (no versionado)
│
├── core/                           # Lógica central del chatbot
│   ├── __init__.py
│   ├── constants.py                # Constantes y configuraciones
│   ├── conversationMemory.py       # Gestión de memoria conversacional
│   └── flow.py                     # Gestión de estados y flujos
│
├── services/                       # Servicios especializados
│   ├── __init__.py
│   ├── chatbot_service.py          # Procesamiento principal de mensajes
│   ├── ia_service.py               # Integración con IA (Gemini)
│   ├── algolia_service.py          # Búsqueda en Algolia
│   ├── db_service.py               # Consultas a base de datos
│   ├── notificacion_services.py    # Gestión de notificaciones
│
├── utils/                          # Utilidades
│   ├── __init__.py
│   └── formatter.py                # Formateo de mensajes WhatsApp
│
└── handlers/                       # Manejadores específicos (vacío)
```

---

## 📦 Dependencias

| Paquete | Versión | Propósito |
|---------|---------|----------|
| `Flask` | (implícito) | Framework web para endpoints |
| `requests` | 2.32.4 | Peticiones HTTP a APIs externas |
| `python-dotenv` | 1.1.1 | Cargar variables de entorno |
| `mysql-connector-python` | 9.3.0 | Conexión a base de datos MySQL |
| `algoliasearch` | 3.0.0 | Búsquedas avanzadas en documentos |

### Integraciones Externas

- **Meta WhatsApp Business API** - Envío de mensajes y plantillas
- **Google Gemini API** - Detección de intenciones con IA
- **Base de Datos MySQL** - Almacenamiento de documentos y usuarios
- **Algolia** - Motor de búsqueda indexado

---

## ⚙️ Configuración

### Variables de Entorno Requeridas

Crear archivo `.env` en la raíz del proyecto:

```bash
# WhatsApp Configuration
WHATSAPP_TOKEN=<tu_token_meta>
WHATSAPP_PHONE_ID=<id_telefono_meta>
WHATSAPP_VERIFY_TOKEN=<token_verificacion_webhook>

# Gemini AI
GEMINI_API_KEY=<tu_clave_api_gemini>

# Database
DB_HOST=localhost
DB_USER=chatbot_user
DB_PASSWORD=<contraseña>
DB_NAME=prorequest_db

# Algolia
ALGOLIA_APP_ID=<id_aplicacion>
ALGOLIA_API_KEY=<clave_api_algolia>
ALGOLIA_INDEX_NAME=documentos

# Server
FLASK_ENV=production
DEBUG=False
PORT=5000
HOST=0.0.0.0
```

### Inicializando la Aplicación

```python
# En app.py
from flask import Flask
from services.chatbot_service import *
from core.flow import conversation_memory

app = Flask(__name__)

# El servidor se inicia automáticamente con:
if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')
```

---

## 🌐 Endpoints API

### 1️⃣ Webhook de WhatsApp

**Ruta:** `GET/POST /whatsapp/webhook`

**Propósito:** Verificar webhook y recibir mensajes entrantes

#### GET - Verificación del Webhook
```http
GET /whatsapp/webhook?hub.verify_token=TOKEN&hub.challenge=CHALLENGE
```

**Response (200 OK):**
```
CHALLENGE_VALUE
```

#### POST - Recibir y Procesar Mensajes
```http
POST /whatsapp/webhook
Content-Type: application/json

{
  "entry": [
    {
      "changes": [
        {
          "value": {
            "messages": [
              {
                "from": "51957133488",
                "type": "text",
                "text": { "body": "¿Cuál es el estado del documento PR-2024-001?" }
              }
            ]
          }
        }
      ]
    }
  ]
}
```

**Flujo Procesado:**
1. Valida autorización del usuario
2. Detecta intención (búsqueda, seguimiento, etc.)
3. Mantiene memoria conversacional
4. Responde con información relevante

**Response (200 OK):**
```json
{ "status": "success" }
```

---

### 2️⃣ Endpoint de Notificaciones Agrupadas

**Ruta:** `POST /api/notificacion`

**Propósito:** Recibir notificaciones en masa y enviar plantillas WhatsApp

**Tipos Soportados:**
- `documentos_inactivos_masivo` - Documentos sin gestión por 15+ días
- `documentos_en_stand_by_masivo` - Documentos en pausa o estado "Stand by"
- `documentos_en_firma_masivo` - Pendientes de firma por 3+ días
- `documentos_antiguos_masivo` - Sin respuesta por 30+ días

**Request Body:**
```json
{
  "tipo": "documentos_inactivos_masivo",
  "cantidad": 5,
  "documentos": [
    {
      "numero_documento": "DOC-2024-001",
      "asunto": "Revisión de contrato",
      "destinatarios": ["51957133488", "51987654321"],
      "fecha_ingreso": "2024-01-15"
    }
  ]
}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "message": "Procesadas 2 notificaciones exitosas, 0 fallidas",
  "tipo": "documentos_inactivos_masivo",
  "total_usuarios": 2,
  "total_documentos": 5,
  "resultados": {
    "exitosos": 2,
    "fallidos": 0,
    "detalles": [...]
  },
  "usa_plantilla": true
}
```

---

### 3️⃣ Endpoint de Notificación de Derivado

**Ruta:** `POST /api/notificacion/derivado`

**Propósito:** Notificar sobre un documento derivado a otro usuario

**Request Body:**
```json
{
  "telefono": "51957133488",
  "nombre": "Juan García",
  "numero_documento": "DOC-2024-100",
  "asunto": "Revisión legal de contrato",
  "proyecto": "Proyecto Saneamiento",
  "encargado": "Dr. López",
  "fecha_ingreso": "2024-02-10",
  "link": "https://prorequest.com/documento/100"
}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "message": "Notificación de documento derivado enviada correctamente",
  "tipo": "documento_derivado",
  "telefono": "51957133488",
  "numero_documento": "DOC-2024-100",
  "message_id": "wamid.xxxxx"
}
```

---

## 🔧 Módulos Principales

### 1. `app.py` - Punto de Entrada

**Responsabilidades:**
- Definir endpoints Flask
- Coordinar webhooks de WhatsApp
- Gestionar flujos de notificación
- Enviar plantillas de WhatsApp Business

**Funciones Clave:**
- `whatsapp_webhook()` - Maneja GET/POST del webhook
- `recibir_notificacion()` - Procesa notificaciones en masa
- `recibir_notificacion_derivado()` - Procesa derivados
- `enviar_plantilla_whatsapp()` - Envía plantillas Meta
- `schedule_cleanup()` - Limpieza automática de notificaciones

---

### 2. `services/chatbot_service.py` - Lógica de Procesamiento

**Responsabilidades:**
- Procesar mensajes del usuario
- Detectar intenciones conversacionales
- Búsquedas en documentos guardados
- Manejar contacto con encargados
- Formatear respuestas para WhatsApp

**Función Principal:**
```python
def procesar_mensaje(mensaje, numero_telefono, conversation_state=None, 
                     conversation_context=None, intent_forzado=None):
    """
    Procesa un mensaje de usuario manteniendo contexto conversacional
    
    Args:
        mensaje: Texto del mensaje usuario
        numero_telefono: ID del usuario
        conversation_state: Estado actual (initial, awaiting_choice, etc.)
        conversation_context: Contexto de sesión
        intent_forzado: Fuerza una intención específica
    
    Returns:
        Dict con respuesta, tipo, intent y parámetros
    """
```

**Flujo de Procesamiento:**
```
1. Detectar RESET (palabra "hola")
2. Obtener contexto conversacional
3. Detectar intención con IA
4. Seleccionar documentos relevantes
5. Formatear respuesta
6. Guardar en memoria
7. Retornar respuesta
```

---

### 3. `services/ia_service.py` - Inteligencia Artificial

**Integración con Google Gemini API**

**Funciones Principales:**

```python
def detectar_intencion_con_contexto(texto_usuario, numero_telefono, context, 
                                    conversation_state):
    """
    Detecta la intención del usuario usando IA
    
    Retorna: {
        "intent": "seguimiento_por_codigo",
        "parameters": {"document_id": "PR-2024-001"},
        ...
    }
    """

def consultar_ia_con_memoria(consulta, context, conversation_state):
    """
    Consulta IA considerando historial conversacional
    
    Mejora la respuesta usando el contexto previo
    """

def seleccionar_respuesta(texto_usuario, context, documentos, 
                          conversation_state):
    """
    Selecciona la mejor respuesta entre múltiples documentos
    """
```

**Intenciones Detectadas:**
- `saludo` - Saludos iniciales
- `seguimiento_por_codigo` - Busca por PR-XXXX
- `seguimiento_por_numero_documento` - Busca por número
- `seguimiento_por_proyecto` - Busca por proyecto
- `buscar_documentos` - Búsqueda general
- `contactar_encargado` - Solicita contacto
- `conversacion_general` - Chat común

---

### 4. `services/algolia_service.py` - Búsqueda Avanzada

**Motor de Búsqueda Indexado**

```python
def buscar_en_algolia(texto, filtros=None):
    """
    Búsqueda rápida en índice Algolia
    
    Filtros disponibles:
        - estado: "activo", "en_firma", "en_standby"
        - proyecto: nombre del proyecto
        - rango_fechas: [inicio, fin]
    """

def generar_respuesta_busqueda_algolia(texto_busqueda):
    """
    Formatea resultados de Algolia para WhatsApp
    """
```

---

### 5. `services/db_service.py` - Base de Datos

**Consultas a MySQL**

```python
def consultar_por_numero_documento(numero_usuario):
    """Busca documento por número (ej: 2024-001)"""

def consultar_por_codigo_sistema(codigo_usuario):
    """Busca documento por código PR (ej: PR-2024-001)"""

def consultar_documentos_por_usuario(nombre_usuario):
    """Lista documentos de un usuario específico"""

def consultar_documentos_por_proyecto(nombre_proyecto):
    """Lista documentos de un proyecto"""

def consultar_documento_por_asunto(texto):
    """Búsqueda por palabras clave en asunto"""

def consultar_por_numero_consecutivo(numero_consecutivo):
    """Busca formulario por número consecutivo"""
```

---

### 6. `core/flow.py` - Gestión de Estados

**Sistema de Estados para Conversaciones**

```python
def detectar_intencion_con_contexto(texto_usuario, phone_number, 
                                    conversation_context, conversation_state):
    """
    Sistema principal de detección con estados
    
    Estados Soportados:
        - initial: Estado inicial
        - awaiting_choice: Esperando selección de lista
        - awaiting_verification: Esperando confirmación
        - filtered_search: Búsqueda en lista guardada
        - awaiting_notification_choice: Seleccionando notificación
    """
```

**Transiciones de Estados:**

```
initial
  ↓
[Usuario busca documentos]
  ↓
awaiting_choice (muestra lista)
  ↓
[Usuario selecciona documento]
  ↓
awaiting_verification (pide confirmación)
  ↓
[Sí/No confirmación]
  ↓
filtered_search (contraseña si necesita más)
```

---

### 7. `core/conversationMemory.py` - Memoria Conversacional

**Mantiene Contexto de Conversación**

```python
class ConversationMemory:
    """
    Gestiona la memoria de cada usuario
    
    Características:
        - Max 10 turnos de conversación
        - Timeout de 60 minutos
        - Cache de 50 documentos por usuario
    
    Métodos principales:
        - add_turn() - Agregar turno a memoria
        - get_conversation_state() - Obtener estado actual
        - set_conversation_documents() - Guardar documentos
        - get_conversation_context() - Contexto actual
        - _reset_conversation_state() - Reiniciar conversación
    """
```

**Estructura de Turno:**
```python
@dataclass
class ConversationTurn:
    timestamp: float              # Cuándo ocurrió
    user_message: str             # Mensaje usuario
    bot_response: str             # Respuesta bot
    intent: str                   # Intención detectada
    parameters: Dict              # Parámetros adicionales
    context: Dict                 # Contexto conversacional
    message_type: str             # "verificacion", "eleccion", "consulta"
    flow: str                     # Flujo actual
```

---

### 8. `services/notificacion_services.py` - Gestión de Notificaciones

**NotificationManager - Almacena y agrupa notificaciones**

```python
notification_manager = NotificationManager()

# Almacenar notificaciones
notification_group = notification_manager.store_notifications(
    phone_number="51957133488",
    notifications_data={
        "tipo": "documentos_inactivos_masivo",
        "cantidad": 5,
        "documentos": [...]
    }
)

# Obtener notificaciones por tipo
notifications = notification_manager.get_notifications_by_type(
    phone_number="51957133488",
    notification_type="sin_respuesta"
)

# Marcar como vista
notification_manager.mark_notification_as_viewed(
    phone_number="51957133488",
    notification_id="notif_123"
)
```

---

### 9. `utils/formatter.py` - Formateo de Mensajes

**Convierte datos a formato WhatsApp**

```python
def formatear_lista_documentos(documentos):
    """Formatea lista de documentos con emojis y numeración"""

def formatear_documento_detalle(documento):
    """Detalle completo de un documento"""

def formatear_documento_detalle_notificacion(documento):
    """Formato especial para documentos de notificaciones"""

def formatear_seguimiento(documento):
    """Información de seguimiento del documento"""
```

**Ejemplo de Salida:**
```
📄 DOC-2024-001 - Revisión de Contrato

📋 Detalles:
  • Estado: En Firma
  • Proyecto: Saneamiento
  • Encargado: Dr. López
  • Ingreso: 15 Enero 2024
  • Últimas 24h: Sin cambios

¿El documento es lo que estabas buscando?
```

---

## 🔄 Flujo de Conversación

### Ejemplo Completo: Búsqueda de Documento

```
Usuario: "Buscar documento PR-2024-001"
         ↓
[Webhook recibe mensaje]
         ↓
procesar_mensaje() {
  1. Reset check: ¿Es "hola"? No
  2. Obtener estado: "initial"
  3. Detectar intención: "seguimiento_por_codigo"
  4. Buscar en BD: encontrado
  5. Formatear respuesta
  6. Guardar en memoria
}
         ↓
Bot: "📄 DOC-2024-001 - Estado: En Firma
      Encargado: Dr. López
      ¿Es este el documento?"
         ↓
Estado → "awaiting_verification"
         ↓
Usuario: "Sí"
         ↓
Bot: "Perfecto! ¿Necesitas más información sobre este documento?"
         ↓
Estado → "filtered_search"
```

---

## 💾 Gestión de Memoria

### Ciclo de Vida de una Conversación

```
1. INICIO (initial)
   - Usuario envía primer mensaje
   - State = "initial"
   - Memoria vacía
   
2. BÚSQUEDA (awaiting_choice)
   - Se muestra lista de documentos
   - Documentos guardados en cache
   - State = "awaiting_choice"
   
3. VERIFICACIÓN (awaiting_verification)
   - Documento seleccionado mostrado
   - Esperando confirmación
   - State = "awaiting_verification"
   
4. BÚSQUEDA FILTRADA (filtered_search)
   - Búsquedas dentro de documentos guardados
   - Contexto previamente cargado
   - State = "filtered_search"
   
5. RESET (initial)
   - Usuario dice "Hola"
   - Borra toda la memoria
   - Vuelve a initial
   
6. TIMEOUT
   - 60 minutos sin actividad
   - Limpieza automática
```

### Límites de Memoria

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `max_turns` | 10 | Máximo de turnos guardados |
| `session_timeout` | 3600s (1h) | Tiempo antes de limpiar |
| `max_documents_cache` | 50 | Documentos máx guardados |

---

## 🔐 Seguridad

### Autorización de Usuarios

```python
def numero_autorizado(numero_telefono):
    """
    Valida que el usuario esté registrado
    
    Retorna:
        {
            "nombres": "Juan García",
            "nivel_acceso": "usuario",
            "permisos": ["ver_propios_documentos"],
            ...
        }
    
    Si no está autorizado:
        None → envía mensaje de contacto
    """
```

### Verificación de Webhook

```
1. Meta envía token en parámetro
2. comparar con WHATSAPP_VERIFY_TOKEN
3. Si coincide: retornar CHALLENGE
4. Si no: retornar 403 Forbidden
```

---

## 📊 Servicios Utilizados

### Servicios Activos en Cada Endpoint

#### `/whatsapp/webhook` (POST)
```
✅ chatbot_service.procesar_mensaje()
✅ ia_service.detectar_intencion_con_contexto()
✅ db_service.consultar_*()
✅ algolia_service.generar_respuesta_busqueda_algolia()
✅ formatter.formatear_*()
✅ chatbot_service.enviar_mensaje_whatsapp()
```

#### `/api/notificacion` (POST)
```
✅ chatbot_service.numero_autorizado()
✅ notificacion_services.notification_manager.store_notifications()
✅ app.enviar_plantilla_whatsapp()
```

#### `/api/notificacion/derivado` (POST)
```
✅ chatbot_service.numero_autorizado()
✅ chatbot_service.normalizar_numero_whatsapp()
✅ app.enviar_plantilla_whatsapp()
```

---

## 🛠️ Funciones Clave

### Función Principal: `procesar_mensaje()`

```python
def procesar_mensaje(mensaje, numero_telefono, conversation_state=None, 
                     conversation_context=None, intent_forzado=None):
    """
    UBICACIÓN: services/chatbot_service.py:16
    
    DESCRIPCIÓN:
    Procesa un mensaje de usuario con soporte completo de estados
    conversacionales y memoria de contexto.
    
    PARÁMETROS:
    - mensaje: str - Texto del usuario
    - numero_telefono: str - ID del usuario en WhatsApp
    - conversation_state: Dict - Estado actual (obtenido si es None)
    - conversation_context: Dict - Contexto de sesión
    - intent_forzado: str - Fuerza una intención (ej: "buscar_documentos")
    
    RETORNA:
    {
        "tipo": "detalle|lista|saludo|consulta|error",
        "respuesta": "Texto de respuesta para WhatsApp",
        "intent": "intención detectada",
        "parameters": {...datos específicos...}
    }
    
    FLUJO INTERNO:
    1. Verifica si es reset (/hola/)
    2. Obtiene estado conversacional
    3. Llama detectar_intencion_con_contexto()
    4. Según estado y intent, elige acción
    5. Busca documentos (BD o guardados)
    6. Formatea respuesta
    7. Guarda en memoria
    8. Retorna respuesta
    
    ESTADOS SOPORTADOS:
    - initial: Búsqueda nueva
    - awaiting_choice: Seleccionar de lista
    - awaiting_verification: Confirmar selección
    - filtered_search: Búsqueda en documentos guardados
    """
```

### Función: `detectar_intencion_con_contexto()`

```python
# Ubicación: core/flow.py:13
def detectar_intencion_con_contexto(texto_usuario, phone_number, 
                                    conversation_context, conversation_state):
    """
    Detecta QUÉ quiere hacer el usuario usando IA
    
    INTENCIONES DETECTADAS:
    
    1. saludo - "hola", "buenos días", etc.
    2. seguimiento_por_codigo - "¿Estado de PR-2024-001?"
    3. seguimiento_por_numero_documento - "Buscar 2024-001"
    4. seguimiento_por_proyecto - "Documentos del proyecto saneamiento"
    5. seguimiento_por_asunto - "Contratos pendientes"
    6. buscar_documentos - "Buscar documentos activos"
    7. conversacion_general - Chat común
    8. contactar_encargado - "Hablar con el responsable"
    9. confirmar_seleccion - "Sí", "No"
    10. seleccionar_notificacion - Elección de notificación
    
    MODO IA:
    - Usa Google Gemini API para análisis profundo
    - Con fallback a detección local si falla
    """
```

### Función: `enviar_plantilla_whatsapp()`

```python
def enviar_plantilla_whatsapp(numero: str, nombre_plantilla: str, 
                              parametros: List[str], idioma: str = "es_PE", 
                              tiene_boton: bool = True):
    """
    UBICACIÓN: app.py:403
    
    Envía plantilla Pre-aprobada por Meta
    
    PARÁMETROS REQUERIDOS:
    - numero: Número WhatsApp con código país (51...)
    - nombre_plantilla: Nombre en consola Meta
    - parametros: Lista de reemplazos para {{1}}, {{2}}, etc.
    - idioma: "es_PE" recomendado
    - tiene_boton: Si incluye botón interactivo
    
    PLANTILLAS DISPONIBLES:
    - alerta_documentos_inactivos
    - documentos_stand_by
    - documento_sin_firma
    - documento_sin_respuesta
    - derivados_prueba
    
    RETORNA:
    {
        "status": "success|error",
        "message_id": "wamid.xxxxx",
        "template": "nombre_plantilla"
    }
    """
```

---

## ⚫ Funciones No Utilizadas

Estas funciones están definidas pero **NUNCA se llaman** en el flujo actual:

### 1. `registrar_intento_no_autorizado()`
```python
# Ubicación: services/chatbot_service.py:1148
def registrar_intento_no_autorizado(numero_telefono, mensaje):
    """
    PROPÓSITO: Registrar intentos de acceso no autorizados en tabla DB
    ESTADO: No utilizada
    
    RAZÓN: El sistema simplemente rechaza usuarios no autorizados
    sin registrar intentos
    """
```

### 2. `listar_notificaciones_usuario()`
```python
# Ubicación: services/chatbot_service.py:1370
def listar_notificaciones_usuario(numero_telefono, limit=10):
    """
    PROPÓSITO: Listar notificaciones recientes del usuario
    ESTADO: No utilizada
    
    RAZÓN: Uses notification_manager directamente en su lugar
    """
```

---

## 📖 Ejemplo de Uso

### Ejemplo 1: Iniciar el Servidor

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Configurar variables de entorno
# Editar .env con tus credenciales

# 3. Iniciar servidor
python app.py

# Output esperado:
# 🚀 Iniciando Chatbot WhatsApp con Memoria Conversacional Avanzada...
# ============================================================
# 🧠 Memoria: 10 turnos máx, 60min timeout
# 📚 Cache documentos: 50 docs máx por usuario
# 🔄 Estados soportados: initial, awaiting_choice, awaiting_verification, filtered_search
# 📞 Funciones especiales: contactar_encargado, algolia_search (no afectan flujo)
# ============================================================
# * Running on http://0.0.0.0:5000
```

### Ejemplo 2: Usuario Busca Documento

```bash
# Mensaje (desde WhatsApp)
👤 Usuario: "¿Cuál es el estado del documento PR-2024-001?"

# Procesamiento interno
📱 Webhook recibe:
   - from: "51957133488"
   - type: "text"
   - body: "¿Cuál es el estado del documento PR-2024-001?"

🔍 procesar_mensaje():
   1. Reset? No
   2. Estado: "initial"
   3. Intent detectado: "seguimiento_por_codigo"
   4. Búsqueda en BD: Encontrado
   5. Formato: detalle
   6. Memoria: Guardado

✅ Respuesta enviada:
📄 PR-2024-001 - Revisión de Contrato

📋 Detalles Completos:
  • Estado: En Firma
  • Proyecto: Saneamiento - Presa Llimonaqui
  • Encargado: Dr. Juan López
  • Fecha Ingreso: 15 de Enero, 2024
  • Últimas 24h: Sin cambios

¿El documento es lo que estabas buscando?

// Estado cambió a: awaiting_verification
```

### Ejemplo 3: Enviar Notificación Masiva

```bash
# Solicitud HTTP
POST /api/notificacion
Content-Type: application/json

{
  "tipo": "documentos_inactivos_masivo",
  "cantidad": 3,
  "documentos": [
    {
      "numero_documento": "DOC-2024-050",
      "asunto": "Revisión de contrato de servicios",
      "estado": "Pendiente",
      "destinatarios": ["51957133488"],
      "fecha_ingreso": "2024-01-20"
    }
  ]
}

# Procesamiento:
✅ 1. Validar documentos ✓
✅ 2. Agrupar por usuario ✓
✅ 3. Obtener info usuario ✓
✅ 4. Almacenar en memoria ✓
✅ 5. Enviar plantilla WhatsApp ✓
✅ 6. Guardar message_id ✓

# Respuesta:
{
  "status": "success",
  "message": "Procesadas 1 notificaciones exitosas, 0 fallidas",
  "tipo": "documentos_inactivos_masivo",
  "total_usuarios": 1,
  "resultados": {
    "exitosos": 1,
    "fallidos": 0
  }
}
```

---

## 🚀 Características Avanzadas

### 1. Memoria Conversacional

El sistema mantiene conocimiento de la conversación anterior:

```
Turno 1: "Buscar documentos en firmware"
Turno 2: "¿Cuánto tiempo llevan?"
         → El sistema sabe que se refiere a documentos en firmware
```

### 2. Detección de Intención con IA

Usa Google Gemini para entender contexto:

```
"Necesito hablar con quien está a cargo"
→ Intent: contactar_encargado

"Dame los siguientes 3"
→ Intent: navigation (si hay lista previa)
```

### 3. Búsqueda Filtrada

Después de seleccionar documentos, las búsquedas posteriores se limitan:

```
Estado: awaiting_choice
  [Documentos: DOC1, DOC2, DOC3 guardados]
Usuario: "Cuál es el más antiguo"
  → Busca solo dentro de esos 3
```

### 4. Notificaciones Inteligentes

- Agrupa documentos por usuario
- Evita notificaciones duplicadas
- Mantiene historial de qué se notificó
- Solo envía a usuarios autorizados

---

## 📝 Notas Importantes

1. **Timezone:** La aplicación usa hora local del servidor
2. **Idioma:** Español Perú (es_PE) en plantillas
3. **Emojis:** Usados para mejor UX en WhatsApp
4. **Limpieza:** Automática cada 30 minutos
5. **Timeout:** 60 minutos sin mensajes = reset automático

---

## 🔗 Referencias

- [Meta WhatsApp API Docs](https://developers.facebook.com/docs/whatsapp/cloud-api/)
- [Google Gemini API](https://ai.google.dev/)
- [Algolia Search](https://www.algolia.com/)
- [Python Flask](https://flask.palletsprojects.com/)

---

**Documento Generado:** 4 Marzo 2026  
**Versión:** 1.0  
**Estado:** Completo ✅
