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
