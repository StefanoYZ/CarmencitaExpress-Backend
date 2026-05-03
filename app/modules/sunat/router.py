from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from app.modules.sunat.exceptions import LycetClientError, SunatEmissionBlockedError
from app.modules.sunat.pdf_service import generar_pdf_boleta_mock
from app.modules.sunat.schema import BoletaDesdeEncomiendaRequest, BoletaResponse
from app.modules.sunat.service import (
    emitir_boleta_desde_encomienda,
    generar_pdf_beta_desde_encomienda,
    generar_xml_beta_desde_encomienda,
    get_boleta_mock,
)


router = APIRouter(prefix="/sunat", tags=["sunat"])


@router.post("/boletas/emitir-desde-encomienda", response_model=BoletaResponse)
def emitir_boleta(payload: BoletaDesdeEncomiendaRequest) -> BoletaResponse:
    try:
        return emitir_boleta_desde_encomienda(
            encomienda_id=payload.encomienda_id,
            confirmar_pago=payload.confirmar_pago,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SunatEmissionBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LycetClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/boletas/beta/pdf-desde-encomienda")
def generar_pdf_beta(payload: BoletaDesdeEncomiendaRequest) -> Response:
    try:
        filename, pdf_bytes = generar_pdf_beta_desde_encomienda(
            encomienda_id=payload.encomienda_id,
            confirmar_pago=payload.confirmar_pago,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SunatEmissionBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LycetClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/boletas/beta/xml-desde-encomienda")
def generar_xml_beta(payload: BoletaDesdeEncomiendaRequest) -> dict:
    try:
        return generar_xml_beta_desde_encomienda(
            encomienda_id=payload.encomienda_id,
            confirmar_pago=payload.confirmar_pago,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SunatEmissionBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LycetClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/boletas/mock/{serie}/{numero}/pdf")
def descargar_pdf_mock(serie: str, numero: str) -> Response:
    record = get_boleta_mock(serie, numero)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Boleta mock no encontrada")

    pdf_bytes = generar_pdf_boleta_mock(record)
    filename = f"boleta_mock_{serie}_{numero}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
