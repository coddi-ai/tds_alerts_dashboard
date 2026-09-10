# Vista productiva de Mantenciones

La ruta protegida `/monitoring/mantenciones` está habilitada únicamente para
CDA. El acceso se controla con `monitoring-mantenciones` en
`config/client_services.json`; la arquitectura queda preparada para habilitar
otros clientes cuando sus fuentes sean validadas.

## Vistas y fuentes

- **Resumen**: selector mensual, cobertura/frescura, equipos con actividad,
  acciones, registros y sistemas intervenidos; tendencia diaria, Pareto de
  actividad por sistema y ranking de equipos.
- **Actividad**: filtros dependientes de sistema, subsistema y equipo; matriz
  equipo × sistema y detalle paginado.
- **Evidencia semanal**: selector de semana y equipo, resumen por unidad y
  tareas agrupadas por día y sistema.

La actividad mensual usa `query_3_actions_all_equipment.parquet`. Los timestamps
se normalizan a UTC, pero las agregaciones se agrupan por `change_date`, la
fecha operacional. El Pareto cuenta cada `action_id` una vez por sistema y se
presenta como **Pareto de actividad de mantenimiento**; no representa fallas.
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
