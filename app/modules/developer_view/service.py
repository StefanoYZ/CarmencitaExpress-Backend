"""Vista developer: inspección de solo lectura de todas las tablas del sistema.

Expone el catálogo de tablas registradas en Base.metadata (whitelist implícita:
solo tablas del ORM, nunca SQL arbitrario del cliente) con paginación y
exportación a CSV/Excel. Los valores de columnas sensibles (passwords, tokens,
secretos) se enmascaran antes de salir del backend.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import Base

# Columnas cuyo contenido nunca debe salir por esta vista (se enmascara).
_SENSITIVE_TOKENS = ("password", "secret", "token", "key", "hash")

_MASK = "•••"


def _table_registry() -> dict[str, object]:
    return {table.name: table for table in Base.metadata.sorted_tables}


def _is_sensitive(column_name: str) -> bool:
    lowered = column_name.lower()
    return any(token in lowered for token in _SENSITIVE_TOKENS)


def _serialize_value(value, column_name: str):
    if value is None:
        return None
    if _is_sensitive(column_name):
        return _MASK
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binario {len(value)} bytes>"
    if isinstance(value, (dict, list)):
        return value
    return value


def list_tables(db: Session) -> list[dict]:
    """Todas las tablas del ORM, ordenadas alfabéticamente, con su total de filas."""
    tables = []
    for name, table in sorted(_table_registry().items()):
        row_count = db.execute(select(func.count()).select_from(table)).scalar() or 0
        tables.append({"name": name, "row_count": row_count})
    return tables


def get_table(name: str):
    table = _table_registry().get(name)
    if table is None:
        raise LookupError(f"Tabla desconocida: {name}")
    return table


def _ordered_query(table):
    # Más recientes primero cuando hay PK entera autoincremental; si no, orden natural.
    primary_keys = list(table.primary_key.columns)
    query = select(table)
    if primary_keys:
        query = query.order_by(primary_keys[0].desc())
    return query


def fetch_rows(db: Session, name: str, *, page: int = 1, page_size: int = 50) -> dict:
    table = get_table(name)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)

    total = db.execute(select(func.count()).select_from(table)).scalar() or 0
    result = db.execute(
        _ordered_query(table).limit(page_size).offset((page - 1) * page_size)
    )
    columns = list(result.keys())
    rows = [
        {column: _serialize_value(value, column) for column, value in zip(columns, row)}
        for row in result.fetchall()
    ]
    return {
        "table": name,
        "columns": columns,
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _all_rows(db: Session, name: str) -> tuple[list[str], list[list]]:
    table = get_table(name)
    result = db.execute(_ordered_query(table))
    columns = list(result.keys())
    rows = [
        [_serialize_value(value, column) for column, value in zip(columns, row)]
        for row in result.fetchall()
    ]
    return columns, rows


def export_csv(db: Session, name: str) -> bytes:
    columns, rows = _all_rows(db, name)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    # BOM para que Excel abra el CSV en UTF-8 sin romper tildes/ñ.
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _excel_cell(value) -> str:
    if value is None:
        return '<Cell><Data ss:Type="String"></Data></Cell>'
    if isinstance(value, bool):
        value = str(value)
    if isinstance(value, (int, float)):
        return f'<Cell><Data ss:Type="Number">{value}</Data></Cell>'
    return f'<Cell><Data ss:Type="String">{escape(str(value))}</Data></Cell>'


def export_excel(db: Session, name: str) -> bytes:
    """Mismo formato SpreadsheetML que usa reports.py (sin dependencias extra)."""
    columns, rows = _all_rows(db, name)
    header = "<Row>" + "".join(
        f'<Cell ss:StyleID="Header"><Data ss:Type="String">{escape(column)}</Data></Cell>'
        for column in columns
    ) + "</Row>"
    body = "".join(
        "<Row>" + "".join(_excel_cell(value) for value in row) + "</Row>"
        for row in rows
    )
    sheet_name = escape(name[:31])  # Excel limita el nombre de hoja a 31 chars.
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Styles>
  <Style ss:ID="Header">
   <Font ss:Bold="1" ss:Color="#FFFFFF"/>
   <Interior ss:Color="#28A745" ss:Pattern="Solid"/>
  </Style>
 </Styles>
 <Worksheet ss:Name="{sheet_name}">
  <Table>
   {header}{body}
  </Table>
 </Worksheet>
</Workbook>"""
    return content.encode("utf-8")
