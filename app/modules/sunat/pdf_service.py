from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.modules.sunat.schema import MockReceiptRecord


def generate_mock_receipt_pdf(record: MockReceiptRecord) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    story = []

    shipment = record.shipment
    quote = record.quote

    story.append(Paragraph("BOLETA DE VENTA ELECTRONICA - MOCK", styles["Title"]))
    story.append(Paragraph("BOLETA DE PRUEBA - SIN VALOR TRIBUTARIO", styles["Heading2"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Carmencita Express Cargo S.A.C. (modo desarrollo)", styles["Normal"]))
    story.append(Paragraph("RUC no utilizado en modo mock", styles["Normal"]))
    story.append(Spacer(1, 16))

    data = [
        ["Codigo de encomienda", record.shipment_code],
        ["Serie y numero", f"{record.series}-{record.number}"],
        ["Fecha", record.issue_date],
        ["Remitente", shipment["sender_name"]],
        ["Documento remitente", f"{shipment['sender_document_type']} {shipment['sender_document_number']}"],
        ["Direccion remitente", shipment.get("sender_address") or ""],
        ["Telefono remitente", shipment.get("sender_phone") or ""],
        ["Destinatario", shipment["recipient_name"]],
        ["Documento destinatario", _recipient_document(shipment)],
        ["Destino", shipment["destination"]],
        ["Servicio", shipment["description"]],
        ["Ruta", f"{shipment['origin']} -> {shipment['destination']}"],
        ["Peso", f"{shipment['weight_kg']} kg"],
        ["Dimensiones", f"{shipment['length_cm']} x {shipment['width_cm']} x {shipment['height_cm']} cm"],
        ["Fragilidad", shipment["fragility"]],
        ["Subtotal", f"S/ {quote['subtotal']:.2f}"],
        ["IGV", f"S/ {quote['igv']:.2f}"],
        ["Total", f"S/ {quote['total']:.2f}"],
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


def _recipient_document(shipment: dict) -> str:
    document_type = shipment.get("recipient_document_type") or ""
    document_number = shipment.get("recipient_document_number") or ""
    return f"{document_type} {document_number}".strip()

