from app.modules.cotizacion.schema import CotizacionResponse
from app.modules.encomiendas.schema import EncomiendaResponse
from app.modules.encomiendas.service import get_encomienda


RECARGOS_FRAGILIDAD = {
    "BAJA": 0.00,
    "MEDIA": 5.00,
    "ALTA": 10.00,
}


def calcular_cotizacion_para_encomienda(encomienda: EncomiendaResponse) -> CotizacionResponse:
    tarifa_base = 10.00
    costo_peso = encomienda.peso_kg * 2.00
    volumen_m3 = encomienda.largo_cm * encomienda.ancho_cm * encomienda.alto_cm / 1_000_000
    costo_volumen = volumen_m3 * 20.00
    recargo_fragilidad = RECARGOS_FRAGILIDAD[encomienda.fragilidad]

    total = tarifa_base + costo_peso + costo_volumen + recargo_fragilidad
    subtotal = total / 1.18
    igv = total - subtotal

    return CotizacionResponse(
        encomienda_id=encomienda.id,
        codigo_encomienda=encomienda.codigo_encomienda,
        subtotal=round(subtotal, 2),
        igv=round(igv, 2),
        total=round(total, 2),
        moneda="PEN",
        detalle={
            "tarifa_base": round(tarifa_base, 2),
            "costo_peso": round(costo_peso, 2),
            "volumen_m3": round(volumen_m3, 6),
            "costo_volumen": round(costo_volumen, 2),
            "fragilidad": encomienda.fragilidad,
            "recargo_fragilidad": round(recargo_fragilidad, 2),
        },
    )


def calcular_cotizacion(encomienda_id: int) -> CotizacionResponse | None:
    encomienda = get_encomienda(encomienda_id)
    if encomienda is None:
        return None
    return calcular_cotizacion_para_encomienda(encomienda)
