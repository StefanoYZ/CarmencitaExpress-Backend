from typing import Any

from pydantic import BaseModel


class TableInfo(BaseModel):
    name: str
    row_count: int


class TableDataResponse(BaseModel):
    table: str
    columns: list[str]
    rows: list[dict]
    total: int
    page: int
    page_size: int


class ColumnMeta(BaseModel):
    name: str
    python_type: str
    nullable: bool
    is_primary_key: bool
    is_sensitive: bool
    has_default: bool


class TableSchemaResponse(BaseModel):
    table: str
    columns: list[ColumnMeta]
    primary_key: list[str]


class RowCreateRequest(BaseModel):
    data: dict[str, Any]


class RowUpdateRequest(BaseModel):
    pk: dict[str, Any]
    data: dict[str, Any]


class RowDeleteRequest(BaseModel):
    pk: dict[str, Any]


class RowResponse(BaseModel):
    row: dict


class OptimizationTestModeStatus(BaseModel):
    active: bool
    count: int


class OptimizationTestModeUpdate(BaseModel):
    active: bool
    # count opcional: si no se envia, el backend elige una cantidad al azar.
    count: int | None = None
