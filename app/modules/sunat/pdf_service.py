from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.modules.shipments.model import Shipment
from app.modules.sunat.model import ElectronicReceipt
from app.modules.sunat.schema import MockReceiptRecord


BRAND_GREEN = colors.HexColor("#28A745")
DARK_GREEN = colors.HexColor("#3C5940")
SOFT_GREEN = colors.HexColor("#E4ECE2")
TEXT_DARK = colors.HexColor("#212529")
TEXT_MUTED = colors.HexColor("#6C757D")
LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "logo.png"


def generate_electronic_receipt_pdf(
    receipt: ElectronicReceipt,
    shipment: Shipment,
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Boleta {receipt.series}-{receipt.number}",
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "ReceiptBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=TEXT_DARK,
    )
    small = ParagraphStyle(
        "ReceiptSmall",
        parent=body,
        fontSize=7.5,
        leading=10,
        textColor=TEXT_MUTED,
    )
    heading = ParagraphStyle(
        "ReceiptHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=DARK_GREEN,
        spaceAfter=5,
    )
    table_header = ParagraphStyle(
        "ReceiptTableHeader",
        parent=body,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )
    story = []

    logo = Image(str(LOGO_PATH), width=48 * mm, height=18 * mm) if LOGO_PATH.exists() else Paragraph(
        "<b>CARMENCITA EXPRESS</b><br/><font size='8'>TRANSPORTE Y CARGA GENERAL</font>",
        body,
    )
    document_box = Table(
        [
            [Paragraph("BOLETA DE VENTA ELECTRONICA", table_header)],
            [Paragraph(f"<font size='15'><b>{receipt.series}-{receipt.number}</b></font>", body)],
            [Paragraph("RUC 20161515648 - ENTORNO SUNAT BETA", small)],
        ],
        colWidths=[72 * mm],
    )
    document_box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1.2, BRAND_GREEN),
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_GREEN),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    header = Table([[logo, document_box]], colWidths=[94 * mm, 72 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.extend([header, Spacer(1, 8 * mm)])

    emitter = Paragraph(
        "<b>CARMENCITA EXPRESS CARGO</b><br/>"
        "Av. America Sur 257, Trujillo 13006<br/>"
        "Servicio de transporte de encomiendas",
        body,
    )
    receipt_meta = Paragraph(
        f"<b>Fecha de emision:</b> {receipt.issue_date}<br/>"
        f"<b>Moneda:</b> {receipt.currency}<br/>"
        f"<b>Estado SUNAT:</b> {'ACEPTADO' if receipt.status == 'ACEPTADO_MOCK' else receipt.status}",
        body,
    )
    meta_table = Table([[emitter, receipt_meta]], colWidths=[100 * mm, 66 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#A3CF84")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.extend([meta_table, Spacer(1, 6 * mm)])

    story.append(Paragraph("DATOS DEL CLIENTE", heading))
    client_data = [
        ["Nombre / Razon social", shipment.sender_name],
        ["Documento", f"{shipment.sender_document_type} {shipment.sender_document_number}"],
        ["Direccion", shipment.sender_address or "-"],
        ["Codigo de encomienda", shipment.shipment_code],
    ]
    story.extend([_information_table(client_data, body), Spacer(1, 6 * mm)])

    story.append(Paragraph("DETALLE DEL SERVICIO", heading))
    detail_data = [
        [
            Paragraph("Descripcion", table_header),
            Paragraph("Ruta", table_header),
            Paragraph("Cant.", table_header),
            Paragraph("Valor venta", table_header),
        ],
        [
            Paragraph(_escape(shipment.description), body),
            Paragraph(f"{_escape(shipment.origin)} - {_escape(shipment.destination)}", body),
            "1",
            f"S/ {receipt.subtotal:.2f}",
        ],
    ]
    detail_table = Table(detail_data, colWidths=[66 * mm, 55 * mm, 16 * mm, 29 * mm])
    detail_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), DARK_GREEN),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, DARK_GREEN),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C9D8C7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([detail_table, Spacer(1, 5 * mm)])

    totals = Table(
        [
            ["Subtotal", f"S/ {receipt.subtotal:.2f}"],
            ["IGV (18%)", f"S/ {receipt.igv:.2f}"],
            ["TOTAL", f"S/ {receipt.total:.2f}"],
        ],
        colWidths=[38 * mm, 30 * mm],
        hAlign="RIGHT",
    )
    totals.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BACKGROUND", (0, -1), (-1, -1), BRAND_GREEN),
                ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BOX", (0, 0), (-1, -1), 0.6, BRAND_GREEN),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C9D8C7")),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([totals, Spacer(1, 7 * mm)])

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def generate_mock_receipt_pdf(record: MockReceiptRecord) -> bytes:
    receipt = SimpleNamespace(
        series=record.series,
        number=record.number,
        issue_date=record.issue_date,
        currency=record.quote.get("currency", "PEN"),
        status="ACEPTADO",
        subtotal=record.quote["subtotal"],
        igv=record.quote["igv"],
        total=record.quote["total"],
    )
    return generate_electronic_receipt_pdf(
        receipt,
        SimpleNamespace(**record.shipment),
    )


def _information_table(rows: list[list[str]], style: ParagraphStyle) -> Table:
    data = [[Paragraph(f"<b>{_escape(label)}</b>", style), Paragraph(_escape(value), style)] for label, value in rows]
    table = Table(data, colWidths=[48 * mm, 118 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE3E0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDE3E0")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8F9FA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _escape(value) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
