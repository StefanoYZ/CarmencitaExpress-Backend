from typing import Any

import httpx

from app.core.config import Settings, settings
from app.modules.sunat.exceptions import LycetClientError, SunatEmissionBlockedError


LYCET_INVOICE_PDF_ENDPOINT = "/api/v1/invoice/pdf"
LYCET_INVOICE_XML_ENDPOINT = "/api/v1/invoice/xml"
LYCET_INVOICE_SEND_ENDPOINT = "/api/v1/invoice/send"
LYCET_INVOICE_STATUS_ENDPOINT = "/api/v1/invoice/status"


class LycetClient:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    @property
    def base_url(self) -> str:
        base_url = self.config.lycet_api_url.strip().rstrip("/")
        if base_url.endswith("/api/v1"):
            return base_url[:-7]
        return base_url

    def generar_pdf(self, payload: dict[str, Any]) -> bytes:
        response = self._post(LYCET_INVOICE_PDF_ENDPOINT, payload)
        content_type = response.headers.get("content-type", "").lower()
        if "application/pdf" not in content_type and not response.content.startswith(b"%PDF"):
            detail = response.text[:500] if response.text else "Lycet no devolvio un PDF valido"
            raise LycetClientError(f"Lycet no devolvio un PDF valido: {detail}")
        return response.content

    def generar_xml(self, payload: dict[str, Any]) -> dict[str, Any] | str:
        response = self._post(LYCET_INVOICE_XML_ENDPOINT, payload)
        content_type = response.headers.get("content-type", "").lower()
        if "xml" in content_type or response.text.lstrip().startswith("<?xml") or response.text.lstrip().startswith("<"):
            return response.text
        return self._json_response(response)

    def emitir_boleta(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.config.sunat_env == "production" and not self.config.sunat_allow_real_emission:
            raise SunatEmissionBlockedError("Emision real bloqueada por configuracion")

        if self.config.sunat_env != "beta":
            return {
                "success": False,
                "estado": "NO_ENVIADO",
                "mensaje": "LycetClient solo envia comprobantes cuando SUNAT_ENV=beta.",
            }

        response = self._post(LYCET_INVOICE_SEND_ENDPOINT, payload)
        data = self._json_response(response)
        return {
            "success": True,
            "estado": data.get("estado", "ENVIADO_BETA"),
            "mensaje": data.get("mensaje", "Boleta enviada a Lycet beta."),
            "raw_response": data,
        }

    def consultar_cdr(
        self,
        *,
        document_type: str,
        series: str,
        number: str,
        ruc: str,
    ) -> dict[str, Any]:
        response = self._get(
            LYCET_INVOICE_STATUS_ENDPOINT,
            params={
                "tipo": document_type,
                "serie": series,
                "numero": number,
                "ruc": ruc,
            },
        )
        return self._json_response(response)

    def _post(self, endpoint: str, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url}{endpoint}"
        params = {"token": self.config.lycet_client_token}

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, params=params, json=payload)
                response.raise_for_status()
                return response
        except httpx.HTTPStatusError as exc:
            detail = self._response_error_detail(exc.response)
            raise LycetClientError(f"Error HTTP de Lycet {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise LycetClientError(f"No se pudo conectar con Lycet: {exc}") from exc

    def _get(self, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url}{endpoint}"
        query = {"token": self.config.lycet_client_token, **params}

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=query)
                response.raise_for_status()
                return response
        except httpx.HTTPStatusError as exc:
            detail = self._response_error_detail(exc.response)
            raise LycetClientError(f"Error HTTP de Lycet {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise LycetClientError(f"No se pudo conectar con Lycet: {exc}") from exc

    def _json_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise LycetClientError("Lycet devolvio una respuesta no JSON") from exc
        if not isinstance(data, dict):
            raise LycetClientError("Lycet devolvio una respuesta JSON no esperada")
        return data

    def _response_error_detail(self, response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return response.text[:1000] if response.text else response.reason_phrase
        return str(data)[:1000]
