import mysql.connector
import re
import os
from mysql.connector import Error

DB_CONFIG = {
    'host': os.getenv("DB_HOST", ""),
    'user': os.getenv("DB_USER", ""),
    'password': os.getenv("DB_PASSWORD", ""),
    'database': os.getenv("DB_NAME", ""),
    'port': int(os.getenv('DB_PORT', )),
    'charset': 'utf8mb4',
}

def get_db_connection():
    """Obtiene conexión a la base de datos MySQL"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"❌ Error conectando a MySQL: {e}")
        return None

def ejecutar_query(query, params=None):
    """Ejecuta una consulta SQL y devuelve resultados"""
    connection = get_db_connection()
    if not connection:
        return []
    
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(query, params or ())
        resultados = cursor.fetchall()
        return resultados
    except Error as e:
        print(f"❌ Error ejecutando query: {e}")
        return []
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def consultar_por_numero_documento(numero_usuario):
    """Consulta documento por numero_documento"""
    partes = re.split(r"[\s\-_]+", numero_usuario.strip())
    partes = [p.upper() for p in partes if p]
    
    if not partes:
        return None
    
    condiciones = []
    params = []
    for parte in partes:
        condiciones.append("UPPER(d.numero_documento) LIKE %s")
        params.append(f"%{parte}%")
    
    where_clause = " AND ".join(condiciones)
    
    query = f"""
        SELECT d.*, 
               u.nombres, u.apellido_paterno, u.apellido_materno, u.celular,
               p.nombre as proyecto_nombre,
               pr.nombre as prioridad_nombre,
               -- Obtener el responsable del proyecto
               ur.nombres as responsable_nombres,
               ur.apellido_paterno as responsable_apellido_paterno,
               ur.apellido_materno as responsable_apellido_materno
        FROM documentos d
        LEFT JOIN usuarios u ON d.usuario_id = u.id
        LEFT JOIN proyectos p ON d.proyecto_id = p.id
        LEFT JOIN prioridades pr ON d.prioridad_id = pr.id
        LEFT JOIN proyecto_responsables pres ON d.proyecto_id = pres.proyecto_id 
                                              AND pres.tipo = 'encargado' 
                                              AND pres.estado = 1
        LEFT JOIN usuarios ur ON pres.usuario_id = ur.id
        WHERE ({where_clause})
          AND d.estado = 1
        ORDER BY d.fecha_ingreso DESC
        LIMIT 5
    """
    
    resultados = ejecutar_query(query, tuple(params))
    return resultados if resultados else None

def consultar_por_codigo_sistema(codigo_usuario):
    """Consulta documento por codigo_sistema"""
    partes = re.split(r"[\s\-_]+", codigo_usuario.strip())
    partes = [p.upper() for p in partes if p]

    if not partes:
        return None

    condiciones = []
    params = []
    for parte in partes:
        condiciones.append("UPPER(d.codigo_sistema) LIKE %s")
        params.append(f"%{parte}%")

    where_clause = " AND ".join(condiciones)

    query = f"""
        SELECT d.*, 
               u.nombres, u.apellido_paterno, u.apellido_materno, u.celular,
               p.nombre as proyecto_nombre,
               pr.nombre as prioridad_nombre,
               -- Obtener el responsable del proyecto
               ur.nombres as responsable_nombres,
               ur.apellido_paterno as responsable_apellido_paterno,
               ur.apellido_materno as responsable_apellido_materno
        FROM documentos d
        LEFT JOIN usuarios u ON d.usuario_id = u.id
        LEFT JOIN proyectos p ON d.proyecto_id = p.id
        LEFT JOIN prioridades pr ON d.prioridad_id = pr.id
        LEFT JOIN proyecto_responsables pres ON d.proyecto_id = pres.proyecto_id 
                                              AND pres.tipo = 'encargado' 
                                              AND pres.estado = 1
        LEFT JOIN usuarios ur ON pres.usuario_id = ur.id
        WHERE ({where_clause})
          AND d.estado = 1
        ORDER BY d.fecha_ingreso DESC
        LIMIT 5
    """

    resultados = ejecutar_query(query, tuple(params))
    return resultados if resultados else None

def consultar_documentos_por_usuario(nombre_usuario):
    """Consulta documentos por nombre de usuario"""
    partes = re.split(r"[\s\-_]+", nombre_usuario.strip())
    partes = [p.upper() for p in partes if p]

    if not partes:
        return None

    condiciones = []
    params = []
    for parte in partes:
        condiciones.append(
            "(UPPER(CONCAT(u.nombres, ' ', u.apellido_paterno, ' ', u.apellido_materno)) LIKE %s "
            "OR UPPER(CONCAT(u.nombres, ' ', u.apellido_paterno)) LIKE %s "
            "OR UPPER(d.encargados_actuales) LIKE %s)"
        )
        params.extend([f"%{parte}%"] * 3)

    where_clause = " AND ".join(condiciones)

    query = f"""
        SELECT d.*, 
               u.nombres, u.apellido_paterno, u.apellido_materno, u.celular,
               p.nombre as proyecto_nombre,
               pr.nombre as prioridad_nombre,
               ur.nombres as responsable_nombres,
               ur.apellido_paterno as responsable_apellido_paterno,
               ur.apellido_materno as responsable_apellido_materno
        FROM documentos d
        LEFT JOIN usuarios u ON d.usuario_id = u.id
        LEFT JOIN proyectos p ON d.proyecto_id = p.id
        LEFT JOIN prioridades pr ON d.prioridad_id = pr.id
        LEFT JOIN proyecto_responsables pres ON d.proyecto_id = pres.proyecto_id 
                                              AND pres.tipo = 'encargado' 
                                              AND pres.estado = 1
        LEFT JOIN usuarios ur ON pres.usuario_id = ur.id
        WHERE ({where_clause})
          AND d.estado = 1
        ORDER BY d.fecha_ingreso DESC
        LIMIT 15
    """

    return ejecutar_query(query, tuple(params))

def consultar_documentos_por_proyecto(nombre_proyecto):
    """Consulta documentos por proyecto"""
    partes = re.split(r"[\s\-_]+", nombre_proyecto.strip())
    partes = [p.upper() for p in partes if p]

    if not partes:
        return None

    condiciones = []
    params = []
    for parte in partes:
        condiciones.append("UPPER(p.nombre) LIKE %s")
        params.append(f"%{parte}%")

    where_clause = " AND ".join(condiciones)

    query = f"""
        SELECT d.*, 
               u.nombres, u.apellido_paterno, u.apellido_materno, u.celular,
               p.nombre as proyecto_nombre,
               pr.nombre as prioridad_nombre,
               ur.nombres as responsable_nombres,
               ur.apellido_paterno as responsable_apellido_paterno,
               ur.apellido_materno as responsable_apellido_materno
        FROM documentos d
        LEFT JOIN usuarios u ON d.usuario_id = u.id
        LEFT JOIN proyectos p ON d.proyecto_id = p.id
        LEFT JOIN prioridades pr ON d.prioridad_id = pr.id
        LEFT JOIN proyecto_responsables pres ON d.proyecto_id = pres.proyecto_id 
                                              AND pres.tipo = 'encargado' 
                                              AND pres.estado = 1
        LEFT JOIN usuarios ur ON pres.usuario_id = ur.id
        WHERE ({where_clause})
          AND d.estado = 1
        ORDER BY d.fecha_ingreso DESC
        LIMIT 5
    """

    return ejecutar_query(query, tuple(params))

def consultar_documento_por_asunto(texto):
    """Busca documentos cuyo asunto contenga el texto"""
    partes = re.split(r"[\s\-_]+", texto.strip())
    partes = [p.upper() for p in partes if p]

    if not partes:
        return None

    condiciones = []
    params = []
    for parte in partes:
        condiciones.append("UPPER(d.asunto) LIKE %s")
        params.append(f"%{parte}%")

    where_clause = " AND ".join(condiciones)

    query = f"""
        SELECT d.*, 
               u.nombres, u.apellido_paterno, u.apellido_materno, u.celular,
               p.nombre as proyecto_nombre,
               pr.nombre as prioridad_nombre,
               ur.nombres as responsable_nombres,
               ur.apellido_paterno as responsable_apellido_paterno,
               ur.apellido_materno as responsable_apellido_materno
        FROM documentos d
        LEFT JOIN usuarios u ON d.usuario_id = u.id
        LEFT JOIN proyectos p ON d.proyecto_id = p.id
        LEFT JOIN prioridades pr ON d.prioridad_id = pr.id
        LEFT JOIN proyecto_responsables pres ON d.proyecto_id = pres.proyecto_id 
                                              AND pres.tipo = 'encargado' 
                                              AND pres.estado = 1
        LEFT JOIN usuarios ur ON pres.usuario_id = ur.id
        WHERE ({where_clause})
          AND d.estado = 1
        ORDER BY d.fecha_ingreso DESC
        LIMIT 5
    """

    return ejecutar_query(query, tuple(params))


def consultar_por_numero_consecutivo(numero_consecutivo):
    """Consulta documento a partir del numero_consecutivo del seguimiento"""
    partes = re.split(r"[\s\-_]+", numero_consecutivo.strip())
    partes = [p.upper() for p in partes if p]
    
    if not partes:
        return None
    
    condiciones = []
    params = []
    for parte in partes:
        condiciones.append("UPPER(s.numero_consecutivo) LIKE %s")
        params.append(f"%{parte}%")
    
    where_clause = " AND ".join(condiciones)
    
    query = f"""
        SELECT d.*, 
               u.nombres, u.apellido_paterno, u.apellido_materno, u.celular,
               p.nombre AS proyecto_nombre,
               pr.nombre AS prioridad_nombre,
               -- Responsable del proyecto
               ur.nombres AS responsable_nombres,
               ur.apellido_paterno AS responsable_apellido_paterno,
               ur.apellido_materno AS responsable_apellido_materno,
               -- Datos del seguimiento
               s.id AS seguimiento_id,
               s.estado_seguimiento,
               s.observaciones,
               s.fecha_derivacion,
               s.numero_consecutivo,
               s.enviado_por,
               s.respondido_por,
               s.comentarios
        FROM seguimiento s
        INNER JOIN documentos d ON s.documento_id = d.id
        LEFT JOIN usuarios u ON d.usuario_id = u.id
        LEFT JOIN proyectos p ON d.proyecto_id = p.id
        LEFT JOIN prioridades pr ON d.prioridad_id = pr.id
        LEFT JOIN proyecto_responsables pres 
               ON d.proyecto_id = pres.proyecto_id 
              AND pres.tipo = 'encargado' 
              AND pres.estado = 1
        LEFT JOIN usuarios ur ON pres.usuario_id = ur.id
        WHERE ({where_clause})
          AND d.estado = 1
        ORDER BY d.fecha_ingreso DESC
        LIMIT 5
    """
      
    return ejecutar_query(query, tuple(params))
    



