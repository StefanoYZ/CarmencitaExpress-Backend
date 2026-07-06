from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.modules.developer_view.schema import TableDataResponse, TableInfo
from app.modules.developer_view.service import (
    export_csv,
    export_excel,
    fetch_rows,
    list_tables,
)


router = APIRouter(
    prefix="/developer",
    tags=["Developer View"],
    dependencies=[Depends(require_permission("developer.read"))],
)


@router.get("/tablas", response_model=list[TableInfo])
def list_tables_endpoint(db: Session = Depends(get_db)) -> list[TableInfo]:
    return [TableInfo(**item) for item in list_tables(db)]


@router.get("/tablas/{nombre}", response_model=TableDataResponse)
def get_table_data_endpoint(
    nombre: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> TableDataResponse:
    try:
        return TableDataResponse(**fetch_rows(db, nombre, page=page, page_size=page_size))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/tablas/{nombre}/export.csv")
def export_table_csv_endpoint(nombre: str, db: Session = Depends(get_db)) -> Response:
    try:
        content = export_csv(db, nombre)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}.csv"'},
    )


@router.get("/tablas/{nombre}/export.xls")
def export_table_excel_endpoint(nombre: str, db: Session = Depends(get_db)) -> Response:
    try:
        content = export_excel(db, nombre)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/vnd.ms-excel",
        headers={"Content-Disposition": f'attachment; filename="{nombre}.xls"'},
    )
