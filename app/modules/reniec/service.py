from .client import consultar_api_reniec

def consultar_dni_service(dni: str):
    if not dni.isdigit():
        return {"error": "Solo números permitidos"}

    if len(dni) != 8:
        return {"error": "El DNI debe tener 8 dígitos"}

    return consultar_api_reniec(dni)