# Backend SQLite del dashboard

El dashboard mantiene el backend de archivos como valor por defecto. Para
activar los snapshots publicados por `ETL_Dashboard_SQLite`:

```text
DASHBOARD_DATA_BACKEND=sqlite
DASHBOARD_SQLITE_ROOT=/opt/coddi/sqlite
DASHBOARD_SQLITE_DOMAINS=all
DASHBOARD_SQLITE_ETL_ROOT=/opt/coddi/ETL_Dashboard_SQLite
```

También se puede declarar una ruta individual por cliente con
`DASHBOARD_SQLITE_PATH_CDA`, `DASHBOARD_SQLITE_PATH_CAPSTONE`,
`DASHBOARD_SQLITE_PATH_EMIN` o `DASHBOARD_SQLITE_PATH_ENEX`. La ruta puede
ser un archivo `.sqlite`, una carpeta que contenga `{client}.sqlite` o una
plantilla con `{client}`.

La integración es vertical y reversible: los loaders existentes siguen usando
`data/` en modo `files`, mientras que en modo `sqlite` consultan solo la base
del cliente y conservan columnas, nulos y contratos vacíos de producción.
`dashboard_module_availability` expone `available`, `partial` y `missing` sin
crear filas sintéticas.
