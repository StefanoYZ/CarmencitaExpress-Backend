"""Pruebas de seguridad/configuración del LLM del asistente.

Cubren: no llamar al LLM si está deshabilitado o sin API key, y que la API key
nunca se exponga en la respuesta del chat.
"""
from app.core.config import settings
from app.integrations.llm import client as llm_client
from app.modules.asistente import service
from app.modules.asistente.schema import ChatRequest


def test_llm_deshabilitado_sin_api_key(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", None)
    monkeypatch.setattr(settings, "assistant_llm_enabled", True)
    assert llm_client._llm_enabled() is False


def test_llm_no_se_llama_si_esta_deshabilitado(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_clave_de_prueba")
    monkeypatch.setattr(settings, "assistant_llm_enabled", False)
    assert llm_client._llm_enabled() is False


def test_respuesta_chat_no_expone_api_key(db_session, monkeypatch):
    sentinel = "gsk_SENTINEL_NO_DEBE_FILTRARSE_123"
    monkeypatch.setattr(settings, "groq_api_key", sentinel)
    monkeypatch.setattr(settings, "assistant_llm_enabled", True)
    # Evitar cualquier llamada de red.
    monkeypatch.setattr(llm_client, "_call_groq_raw", lambda prompt: "")

    resp = service.process_chat(
        db_session,
        ChatRequest(mensaje="¿a qué hora atienden?", canal="externo"),
    )
    assert sentinel not in resp.respuesta
    assert sentinel not in str(resp.model_dump())
