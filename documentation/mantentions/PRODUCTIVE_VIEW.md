# Vista productiva de Mantenciones

La ruta protegida `/monitoring/mantenciones` se controla con
`monitoring-mantenciones` en `config/client_services.json`. Actualmente está
habilitada para CDA, EMIN y CAPSTONE; ENEX permanece sin acceso.

## Vistas y fuentes

- **Resumen**: selector mensual, cobertura/frescura, equipos con actividad,
  acciones, registros, sistemas intervenidos, días con actividad y
  participación de acciones Motor; tendencia diaria, mix de actividad por
  sistema, Pareto de actividad por equipo con foco en Sistema Motor y ranking
  de equipos.
- **Actividad**: filtros dependientes de sistema, subsistema y equipo; matriz
  equipo × sistema y detalle paginado.
- **Evidencia semanal**: selector de semana y equipo, resumen por unidad y
  tareas agrupadas por día y sistema.

En el shell productivo actual solo se muestra **Resumen**. **Actividad** y
**Evidencia semanal** permanecen montadas y deshabilitadas para conservar sus
callbacks y contratos de componentes, listas para una futura reactivación.

### KPIs y visuales respaldados

La fuente `query_3_actions_all_equipment.parquet` respalda los siguientes
indicadores del Resumen:

- **Equipos con actividad**: equipos distintos (`machine_code`) con acciones
  en el período seleccionado.
- **Acciones registradas**: `action_id` únicos del período.
- **Registros de mantenimiento**: `record_id` únicos del período.
- **Sistemas intervenidos**: sistemas distintos no nulos de la acción.
- **Días con actividad**: fechas operacionales distintas (`change_date`).
- **Actividad en Motor**: porcentaje de acciones únicas cuyo
  `action_system_name` coincide con `Motor`, `Sistema Motor` o `Sistema de
  Motor`.

La tendencia diaria agrupa acciones únicas por `change_date`. El mix por
sistema y el ranking de equipos usan la misma métrica de acciones únicas. El
Pareto Motor agrupa por equipo, ordena por cantidad descendente y calcula el
porcentaje acumulado; no representa frecuencia de fallas.

Los informes de referencia también muestran disponibilidad, indisponibilidad,
MTBF, MTTR, horas de reparación, backlog, metas y relaciones programado vs.
imprevisto. Esos indicadores quedan fuera de esta iteración: los Parquet
actuales no aportan una fuente gobernada de horas operativas/reparación,
clasificación de fallas, backlog o metas, por lo que no se presentan como si
fueran derivados de actividad de mantenimiento.

La comparación se realizó contra el catálogo de patrones y los informes
`Informe de Confiabilidad semanal W19.pdf` e `Informe Mensual Confiabilidad
Mantenimiento Mina Julio 2025.pdf`. Sus visuales de mayor valor son el
scorecard de KPIs, la tendencia temporal, la distribución por sistema y los
Paretos de frecuencia/tiempo de reparación. Esta primera iteración conserva la
jerarquía visual, pero reemplaza los indicadores no respaldados por actividad
registrada auditable.

La actividad mensual usa `query_3_actions_all_equipment.parquet`. Los timestamps
se normalizan a UTC, pero las agregaciones se agrupan por `change_date`, la
fecha operacional. El Pareto del Resumen se filtra exclusivamente por
`action_system_name` en el sistema Motor (acepta `Motor`, `Sistema Motor` y
`Sistema de Motor`), usa `machine_code` como dimensión `equipment` y cuenta
`action_id` únicos por equipo. Se presenta como **Pareto de actividad de
mantenimiento por equipo · Sistema Motor**; no representa fallas ni mezcla
otros sistemas.
El detalle se limita a 250 filas por respuesta para no transferir la fuente
completa al navegador.

La evidencia semanal usa los archivos `ww-yyyy.csv`. `Tasks_List` se interpreta
como JSON y los archivos con filas inválidas se muestran como `partial`, sin
ocultar la evidencia válida.

## Contrato de respuesta

El repositorio entrega un objeto JSON serializable con `status`, `meta`,
`filters`, `kpis` y `data`. Los estados son `ok`, `empty`, `partial` y `error`.
Los valores faltantes se mantienen como faltantes; no se convierten en cero.
La ausencia de columnas requeridas, archivos vacíos o fuentes corruptas se
refleja en el estado visual correspondiente.

El botón **Refrescar** invalida las cachés del repositorio. La página abre el
último período disponible y muestra una advertencia con la fecha exacta del
último dato cuando ese período no coincide con el mes calendario vigente.

## Alcance excluido

Esta vista no calcula disponibilidad, MTBF, MTTR, downtime, backlog, estado
sano/detenido ni planes de acción. Esos conceptos requieren fuentes y
definiciones que no están respaldadas por el contrato actual de datos.
