# Vista productiva de Mantenciones

La ruta protegida `/monitoring/mantenciones` se controla con
`monitoring-mantenciones` en `config/client_services.json`. Actualmente está
habilitada para CDA, EMIN y CAPSTONE; ENEX permanece sin acceso.

## Vistas y fuentes

- **Resumen**: selector mensual, cobertura/frescura, equipos con actividad,
  acciones, registros, sistemas intervenidos, días con actividad y
  participación de acciones Motor; cuatro KPIs rotulados **ESTIMADO**
  (disponibilidad, downtime, MTBF y MTTR); tendencia diaria, mix de actividad por
  sistema, Pareto de actividad por equipo con foco en Sistema Motor y ranking
  de equipos.
- **Actividad**: filtros dependientes de sistema, subsistema y equipo; matriz
  equipo × sistema y detalle paginado.
- **Evidencia semanal**: selector de semana y equipo, resumen por unidad y
  tareas agrupadas por día y sistema.

En el shell productivo actual solo se muestra **Resumen**. **Actividad** y
**Evidencia semanal** permanecen montadas y deshabilitadas para conservar sus
callbacks y contratos de componentes, listas para una futura reactivación.

Mientras esas vistas permanecen deshabilitadas, **Resumen** expone solo el
selector mensual. El selector semanal permanece montado dentro del contrato de
Evidencia semanal, pero no se muestra en la cabecera ejecutiva.

La jerarquía ejecutiva de **Resumen** sigue la lectura de los reportes de
referencia: cabecera y cobertura, señales rápidas (ESTIMADO, Motor priorizado,
fecha operacional), cuatro KPIs críticos primero, Pareto Motor por equipo y
tendencia diaria, y luego mix por sistema/ranking. Los agregados de actividad
quedan al final como contexto y no compiten visualmente con los indicadores
críticos.

La metadata del contrato conserva el archivo fuente de los KPIs **ESTIMADOS**,
su ventana de referencia y, cuando corresponde, la razón del fallback mensual;
estos detalles técnicos no se muestran en la cabecera ejecutiva.

Para mantener legibilidad aun cuando la hoja de Font Awesome no esté
disponible (por ejemplo, sin acceso al CDN), los iconos decorativos propios de
Mantenciones usan glifos Unicode locales con etiquetas accesibles. Los textos,
valores y títulos siguen siendo la fuente principal de significado. El mix por
sistema reserva espacio adicional para sus etiquetas inclinadas. El mix se
colorea por unidad y el ranking de equipos muestra el sistema predominante de
cada unidad. El cierre de la vista agrupa los indicadores secundarios bajo
**Indicadores de Interés**.

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
Pareto de actividad de mantenimiento agrupa por equipo dentro de Motor, ordena
por cantidad descendente y muestra tanto las acciones como la línea de
porcentaje acumulado; no representa frecuencia de fallas.

Los informes de referencia también muestran disponibilidad, indisponibilidad,
MTBF, MTTR, horas de reparación, backlog, metas y relaciones programado vs.
imprevisto. En esta iteración se incorporan solo como proxies explícitos
**ESTIMADOS**: query_4 aporta downtime y reparaciones precalculados en ventana
70d, pero no horas operativas gobernadas ni confirmación de fallas. No se
presentan como mediciones reales ni como frecuencia de fallas.

#### Metodología de los KPIs ESTIMADOS

Los cuatro valores priorizan `query_4_business_kpis.parquet` cuando están
disponibles `downtime_hours_70d`, `repairs_70d`, `total_actions_70d` y
`reference_date`. En ese caso la cobertura es la **ventana móvil de 70 días**
del KPI precalculado, aunque el selector de Resumen siga mostrando un mes; esa
diferencia se declara en `meta.estimated_kpis.coverage` y en el banner. Si el
extracto 70d está ausente/incompleto, o se filtra por sistema/subsistema (que
query_4 no desglosa), se usa el fallback mensual de acciones:

- Con query_4: `downtime_est_hours = sum(downtime_hours_70d)` y el evento proxy
  es `sum(repairs_70d)`; si no hay reparaciones, se usa `total_actions_70d` y
  finalmente registros de acciones.
- En fallback: `downtime_est_hours = acciones únicas × 1,5 h`; 1,5 h/acción es
  el proxy conservador y parametrizado de duración/indisponibilidad.
- `scheduled_hours_proxy = equipos cubiertos × días de la ventana × 24 h`
  (70 días con query_4; días calendario del mes en fallback).
- `availability_est_pct = max(scheduled_hours_proxy − downtime_est_hours, 0) /
  scheduled_hours_proxy × 100`.
- `event_count_proxy = reparaciones_70d`; si no hay reparaciones, `total_actions_70d`
  y finalmente registros únicos del extracto de acciones.
- `mttr_est_hours = downtime_est_hours / event_count_proxy`.
- `mtbf_est_hours = max(scheduled_hours_proxy − downtime_est_hours, 0) /
  event_count_proxy`.

Se aplica una validación de plausibilidad antes de usar query_4: si el downtime
70d es negativo, no finito o supera las horas calendario proxy de los equipos
cubiertos, se rechaza todo el bloque 70d y se usa el fallback mensual. La
anomalía queda en `meta.estimated_kpis.reason`; no se recorta silenciosamente
ni se presenta una disponibilidad artificialmente extrema.

Cada payload expone en `meta.estimated_kpis` la etiqueta, fuente, columnas,
unidad, cobertura, hipótesis y fórmulas. Los registros únicos son eventos de
mantenimiento proxy, no fallas confirmadas; si faltan acciones o registros se
devuelve `null` y un estado `unavailable`, nunca cero. Aunque query_4 aporta
valores precalculados, los cuatro indicadores siguen rotulados **ESTIMADO**:
no equivalen a una medición de disponibilidad ni confirman que los eventos
sean fallas.

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

Se mantienen fuera de la vista el backlog, estado sano/detenido, planes de
acción, metas, horas reales de operación/reparación y clasificación de fallas.
Los cuatro KPIs de confiabilidad visibles son únicamente los proxies
**ESTIMADOS** descritos arriba y deben reemplazarse por mediciones gobernadas
cuando exista esa fuente.
