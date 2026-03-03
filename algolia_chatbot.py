
import requests
from config import ALGOLIA_APP_ID, ALGOLIA_INDEX, ALGOLIA_API_KEY
from datetime import datetime
from algoliasearch.search_client import SearchClient


# Inicializar cliente de Algolia
try:
    algolia_client = SearchClient.create(ALGOLIA_APP_ID, ALGOLIA_API_KEY)
    algolia_index = algolia_client.init_index(ALGOLIA_INDEX)
    print("✅ Algolia inicializado correctamente")
except Exception as e:
    print(f"⚠️ Error inicializando Algolia: {e}")
    algolia_index = None

def buscar_en_algolia(texto, filtros=None):
    """Busca documentos en Algolia con filtros opcionales"""
    try:
        url = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
        headers = {
            "X-Algolia-API-Key": ALGOLIA_API_KEY,
            "X-Algolia-Application-Id": ALGOLIA_APP_ID,
            "Content-Type": "application/json"
        }
        
        # Preparar parámetros de búsqueda
        params = f"query={texto}&hitsPerPage=20"
        
        if filtros:
            params += f"&filters={filtros}"
            
        data = {"params": params}
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            return response.json().get("hits", [])
        else:
            print(f"Error en búsqueda Algolia: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        print(f"Error al buscar en Algolia: {e}")
        return []

def generar_respuesta_busqueda_algolia(texto_busqueda):
    """Búsqueda simple en Algolia para WhatsApp"""
    try:
        print(f"🔍 Búsqueda Algolia WhatsApp: '{texto_busqueda}'")
        
        resultados = buscar_en_algolia(texto_busqueda)
        
        if not resultados:
            return f"🔍 *No encontré documentos relacionados con* '{texto_busqueda}'"
        
        respuesta = f"🔍 *RESULTADOS DE BÚSQUEDA:* '{texto_busqueda}'\n"
        respuesta += f"📊 *Encontré {len(resultados)} documento(s)*\n\n"
        
        for i, hit in enumerate(resultados[:5], 1):
            nombre = hit.get("name", "Sin nombre")
            
            # Formatear fecha
            fecha_creacion = hit.get("createdTime", "")
            fecha_formateada = "Fecha no disponible"
            if fecha_creacion:
                try:
                    fecha_obj = datetime.fromisoformat(fecha_creacion.replace('Z', '+00:00'))
                    fecha_formateada = fecha_obj.strftime('%d/%m/%Y')
                except:
                    pass
            
            # Enlace de Google Drive
            object_id = hit.get("objectID", "").split('_')[0]
            drive_url = f"https://drive.google.com/file/d/{object_id}/view" if object_id else "#"
            
            respuesta += (
                f"📄 *{i}. {nombre}*\n"
                f"   📅 *Fecha:* {fecha_formateada}\n"
            )
            
            if drive_url and drive_url != "#":
                # Asegurar que no tnga paréntesis sobrantes
                drive_url = drive_url.strip().rstrip(")")
                respuesta += f"   🔗 [Ver PDF]({drive_url})\n"

            
            respuesta += "\n"
        
        if len(resultados) > 5:
            respuesta += f"📋 *Y {len(resultados) - 5} resultado(s) más...*\n"
        
        respuesta += "\n💡 *Tip: Usa el número exacto del documento para información completa del sistema.*"
        
        return respuesta
        
    except Exception as e:
        print(f"❌ Error en búsqueda Algolia: {e}")
        return f"❌ Error en la búsqueda. Intenta nuevamente."

