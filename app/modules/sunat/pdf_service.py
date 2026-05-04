from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.modules.sunat.schema import BoletaMockRecord


def generar_pdf_boleta_mock(record: BoletaMockRecord) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    story = []

    encomienda = record.encomienda
    cotizacion = record.cotizacion

    story.append(Paragraph("BOLETA DE VENTA ELECTRONICA - MOCK", styles["Title"]))
    story.append(Paragraph("BOLETA DE PRUEBA - SIN VALOR TRIBUTARIO", styles["Heading2"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Carmencita Express Cargo S.A.C. (modo desarrollo)", styles["Normal"]))
    story.append(Paragraph("RUC no utilizado en modo mock", styles["Normal"]))
    story.append(Spacer(1, 16))

    data = [
        ["Codigo de encomienda", record.codigo_encomienda],
        ["Serie y numero", f"{record.serie}-{record.numero}"],
        ["Fecha", record.fecha_emision],
        ["Remitente", encomienda["remitente_nombre"]],
        ["Documento remitente", f"{encomienda['remitente_tipo_documento']} {encomienda['remitente_numero_documento']}"],
        ["Direccion remitente", encomienda.get("remitente_direccion") or ""],
        ["Telefono remitente", encomienda.get("remitente_telefono") or ""],
        ["Destinatario", encomienda["destinatario_nombre"]],
        ["Documento destinatario", _documento_destinatario(encomienda)],
        ["Destino", encomienda["destino"]],
        ["Servicio", encomienda["descripcion"]],
        ["Ruta", f"{encomienda['origen']} -> {encomienda['destino']}"],
        ["Peso", f"{encomienda['peso_kg']} kg"],
        ["Dimensiones", f"{encomienda['largo_cm']} x {encomienda['ancho_cm']} x {encomienda['alto_cm']} cm"],
        ["Fragilidad", encomienda["fragilidad"]],
        ["Subtotal", f"S/ {cotizacion['subtotal']:.2f}"],
        ["IGV", f"S/ {cotizacion['igv']:.2f}"],
        ["Total", f"S/ {cotizacion['total']:.2f}"],
    ]

    table = Table(data, colWidths=[160, 320])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 18))
    story.append(
        Paragraph(
            "Documento generado para pruebas de desarrollo. No representa un comprobante valido ante SUNAT.",
            styles["Italic"],
        )
    )

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def _documento_destinatario(encomienda: dict) -> str:
    tipo = encomienda.get("destinatario_tipo_documento") or ""
    numero = encomienda.get("destinatario_numero_documento") or ""
    return f"{tipo} {numero}".strip()
