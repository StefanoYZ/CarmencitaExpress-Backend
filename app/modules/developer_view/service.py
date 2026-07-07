"""Vista developer: inspección y edición (CRUD) de todas las tablas del sistema.

Expone el catálogo de tablas registradas en Base.metadata (whitelist implícita:
solo tablas del ORM, nunca SQL arbitrario del cliente) con paginación,
exportación a CSV/Excel y mutaciones (crear/actualizar/eliminar filas). Los
valores de columnas sensibles (passwords, tokens, secretos) se enmascaran en
lectura y NUNCA se aceptan en escritura por este editor genérico: se ignoran
silenciosamente si vienen en el payload.
"""
from __future__ import annotations

import codecs
import csv
import io
from datetime import date, datetime
from decimal import Decimal
from html import escape

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base

# Columnas cuyo contenido nunca debe salir por esta vista (se enmascara) ni
# aceptarse en escritura (se ignoran si vienen en el payload de create/update).
_SENSITIVE_TOKENS = ("password", "secret", "token", "key", "hash")

_MASK = "•••"


class DeveloperViewError(Exception):
    """Error de negocio en una operación de la vista developer (400 en el router)."""


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


def _column_meta(column) -> dict:
    try:
        python_type = column.type.python_type.__name__
    except NotImplementedError:
        python_type = "str"
    return {
        "name": column.name,
        "python_type": python_type,
        "nullable": bool(column.nullable),
        "is_primary_key": bool(column.primary_key),
        "is_sensitive": _is_sensitive(column.name),
        "has_default": column.default is not None or column.server_default is not None,
    }


def get_table_schema(name: str) -> dict:
    table = get_table(name)
    return {
        "table": name,
        "columns": [_column_meta(column) for column in table.columns],
        "primary_key": [column.name for column in table.primary_key.columns],
    }


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
    return codecs.BOM_UTF8 + buffer.getvalue().encode("utf-8")


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


# --------------------------------------------------------------------------
# CRUD (create / update / delete). Todas las operaciones excluyen columnas
# sensibles del payload de entrada: nunca se escribe un password/token/secret
# a través de este editor genérico. Para eso ya existe la pantalla de Usuarios.
# --------------------------------------------------------------------------

def _strip_sensitive(table, data: dict) -> dict:
    valid_columns = {column.name for column in table.columns}
    unknown = set(data) - valid_columns
    if unknown:
        raise DeveloperViewError(f"Columnas desconocidas: {', '.join(sorted(unknown))}")
    return {key: value for key, value in data.items() if not _is_sensitive(key)}


def _coerce_value(column, raw_value):
    if raw_value is None:
        return None
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return raw_value
    if isinstance(raw_value, python_type):
        return raw_value
    try:
        if python_type is bool:
            if isinstance(raw_value, str):
                return raw_value.strip().lower() in {"true", "1", "yes", "si", "sí"}
            return bool(raw_value)
        if python_type in (date, datetime) and isinstance(raw_value, str):
            parsed = datetime.fromisoformat(raw_value)
            return parsed.date() if python_type is date else parsed
        return python_type(raw_value)
    except (TypeError, ValueError) as exc:
        raise DeveloperViewError(
            f"Valor invalido para '{column.name}': se esperaba {python_type.__name__}"
        ) from exc


def _coerce_payload(table, data: dict) -> dict:
    coerced = {}
    for key, value in data.items():
        column = table.columns[key]
        coerced[key] = _coerce_value(column, value)
    return coerced


def _missing_required_sensitive_columns(table, provided: dict) -> list[str]:
    missing = []
    for column in table.columns:
        if not _is_sensitive(column.name):
            continue
        if column.nullable or column.default is not None or column.server_default is not None:
            continue
        if column.name not in provided:
            missing.append(column.name)
    return missing


def create_row(db: Session, name: str, data: dict) -> dict:
    table = get_table(name)
    payload = _strip_sensitive(table, data)

    missing_sensitive = _missing_required_sensitive_columns(table, data)
    if missing_sensitive:
        raise DeveloperViewError(
            "Esta tabla tiene columnas sensibles obligatorias que este editor no "
            f"puede completar ({', '.join(missing_sensitive)}). Usa la pantalla "
            "dedicada correspondiente (p. ej. Usuarios internos) para crear este registro."
        )

    payload = _coerce_payload(table, payload)
    primary_keys = [column.name for column in table.primary_key.columns]
    try:
        result = db.execute(insert(table).values(**payload))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DeveloperViewError(_friendly_integrity_error(exc)) from exc

    inserted_pk = result.inserted_primary_key
    if inserted_pk and primary_keys:
        pk_filter = dict(zip(primary_keys, inserted_pk))
        return get_row(db, name, pk_filter)
    return {column: _serialize_value(value, column) for column, value in payload.items()}


def get_row(db: Session, name: str, pk_values: dict) -> dict:
    table = get_table(name)
    query = select(table)
    for column_name, value in pk_values.items():
        query = query.where(table.columns[column_name] == value)
    result = db.execute(query).first()
    if result is None:
        raise LookupError("Fila no encontrada")
    columns = list(table.columns.keys())
    return {column: _serialize_value(value, column) for column, value in zip(columns, result)}


def update_row(db: Session, name: str, pk_values: dict, data: dict) -> dict:
    table = get_table(name)
    if not pk_values:
        raise DeveloperViewError("Se requiere la clave primaria para actualizar una fila")

    payload = _strip_sensitive(table, data)
    payload = {key: value for key, value in payload.items() if key not in pk_values}
    if not payload:
        raise DeveloperViewError("No hay columnas editables para actualizar")

    payload = _coerce_payload(table, payload)
    query = update(table)
    for column_name, value in pk_values.items():
        query = query.where(table.columns[column_name] == value)

    try:
        result = db.execute(query.values(**payload))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DeveloperViewError(_friendly_integrity_error(exc)) from exc

    if result.rowcount == 0:
        raise LookupError("Fila no encontrada")
    return get_row(db, name, pk_values)


def delete_row(db: Session, name: str, pk_values: dict) -> None:
    table = get_table(name)
    if not pk_values:
        raise DeveloperViewError("Se requiere la clave primaria para eliminar una fila")

    query = delete(table)
    for column_name, value in pk_values.items():
        query = query.where(table.columns[column_name] == value)

    try:
        result = db.execute(query)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DeveloperViewError(_friendly_integrity_error(exc)) from exc

    if result.rowcount == 0:
        raise LookupError("Fila no encontrada")


def _friendly_integrity_error(exc: IntegrityError) -> str:
    message = str(exc.orig) if exc.orig else str(exc)
    lowered = message.lower()
    if "foreign key" in lowered or "violates foreign key constraint" in lowered:
        return (
            "No se puede completar la operacion: otra tabla depende de este registro "
            "(restriccion de clave foranea)."
        )
    if "unique" in lowered or "duplicate" in lowered:
        return "Ya existe un registro con ese valor unico."
    if "not null" in lowered or "null value" in lowered:
        return "Falta un valor obligatorio."
    return "No se pudo completar la operacion por una restriccion de la base de datos."
