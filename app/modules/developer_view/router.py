from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.modules.developer_view.schema import (
    OptimizationTestModeStatus,
    OptimizationTestModeUpdate,
    RowCreateRequest,
    RowDeleteRequest,
    RowResponse,
    RowUpdateRequest,
    TableDataResponse,
    TableInfo,
    TableSchemaResponse,
)
from app.modules.developer_view.service import (
    DeveloperViewError,
    create_row,
    delete_row,
    export_csv,
    export_excel,
    fetch_rows,
    get_table_schema,
    list_tables,
    update_row,
)
from app.modules.optimization_poc.test_data import (
    clear_test_packages,
    count_test_packages_today,
    seed_test_packages,
    test_mode_active,
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


@router.get("/tablas/{nombre}/schema", response_model=TableSchemaResponse)
def get_table_schema_endpoint(nombre: str) -> TableSchemaResponse:
    try:
        return TableSchemaResponse(**get_table_schema(nombre))
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


@router.get(
    "/optimizacion/modo-prueba",
    response_model=OptimizationTestModeStatus,
)
def get_optimization_test_mode_endpoint(
    db: Session = Depends(get_db),
) -> OptimizationTestModeStatus:
    return OptimizationTestModeStatus(
        active=test_mode_active(db),
        count=count_test_packages_today(db),
    )


@router.post(
    "/optimizacion/modo-prueba",
    response_model=OptimizationTestModeStatus,
    dependencies=[Depends(require_permission("developer.write"))],
)
def set_optimization_test_mode_endpoint(
    payload: OptimizationTestModeUpdate,
    db: Session = Depends(get_db),
) -> OptimizationTestModeStatus:
    # ON: genera paquetes de prueba (el escenario de optimizacion los usara). Con
    # count=None el backend elige cantidad y semilla al azar -> lote distinto cada vez.
    # OFF: los borra (el escenario vuelve a las encomiendas reales de la web).
    if payload.active:
        count = payload.count if payload.count and payload.count > 0 else None
        seed_test_packages(db, n=count)
    else:
        clear_test_packages(db)
    return OptimizationTestModeStatus(
        active=test_mode_active(db),
        count=count_test_packages_today(db),
    )


@router.post(
    "/tablas/{nombre}/filas",
    response_model=RowResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("developer.write"))],
)
def create_row_endpoint(
    nombre: str,
    payload: RowCreateRequest,
    db: Session = Depends(get_db),
) -> RowResponse:
    try:
        return RowResponse(row=create_row(db, nombre, payload.data))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DeveloperViewError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put(
    "/tablas/{nombre}/filas",
    response_model=RowResponse,
    dependencies=[Depends(require_permission("developer.write"))],
)
def update_row_endpoint(
    nombre: str,
    payload: RowUpdateRequest,
    db: Session = Depends(get_db),
) -> RowResponse:
    try:
        return RowResponse(row=update_row(db, nombre, payload.pk, payload.data))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DeveloperViewError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete(
    "/tablas/{nombre}/filas",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("developer.write"))],
)
def delete_row_endpoint(
    nombre: str,
    payload: RowDeleteRequest,
    db: Session = Depends(get_db),
) -> None:
    try:
        delete_row(db, nombre, payload.pk)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DeveloperViewError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
