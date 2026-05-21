import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("RENIEC_API_URL")
API_TOKEN = os.getenv("RENIEC_API_TOKEN")


def consultar_api_reniec(dni: str):
    if not API_URL or not API_TOKEN:
        return {"error": "Configuración de API no encontrada"}

    try:
        headers = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        body = {"dni": dni}

        response = requests.post(API_URL, json=body, headers=headers, timeout=10)

        try:
            data = response.json()
        except Exception:
            return {"error": "Respuesta inválida de API externa"}

        if response.status_code != 200:
            return {
                "error": data.get("message", "Error en API externa"),
                "status_code": response.status_code
            }

        if not data.get("success") or not data.get("data"):
            return {"error": data.get("message", "No se encontró información")}

        persona = data.get("data", {})

        return {
            "dni": persona.get("numero", ""),
            "nombres": persona.get("nombres", ""),
            "apellido_paterno": persona.get("apellido_paterno", ""),
            "apellido_materno": persona.get("apellido_materno", ""),
        }

    except requests.exceptions.Timeout:
        return {"error": "Tiempo de espera agotado"}

    except requests.exceptions.RequestException as e:
        return {"error": "Error de red", "detalle": str(e)}

    except Exception as e:
        return {"error": "Error de conexión", "detalle": str(e)}