# Vista productiva de Mantenciones

La ruta protegida `/monitoring/mantenciones` se controla con
`monitoring-mantenciones` en `config/client_services.json`. Actualmente está
habilitada para CDA, EMIN y CAPSTONE; ENEX permanece sin acceso.

## Vistas y fuentes

- **Resumen**: selector mensual, filtro de flota/tipo de equipo según el catálogo
  de Tribología (los equipos sin coincidencia quedan en ``otros``) y selector ejecutivo de unidad (``Todas`` o una unidad), cobertura/frescura, equipos con actividad,
  acciones, registros, sistemas intervenidos, días con actividad y
  participación de acciones Motor; KPIs de tiempo respaldados por la fuente
  (disponibilidad, downtime, MTBF y MTTR); tendencia diaria de horas-equipo
  fuera de servicio, mix de actividad por
  sistema sin desglose por unidad, ranking de equipos y Paretos de actividad,
  seguido de una tabla con el detalle de las actividades realizadas. CDA conserva sus Paretos
  enfocados en Motor y Tren de Fuerza; EMIN y CAPSTONE muestran todos los
  sistemas tanto por equipo como por sistema.
- **Actividad**: filtros dependientes de sistema, subsistema y equipo; matriz
  equipo × sistema y detalle paginado.
- **Evidencia semanal**: selector de semana y equipo, resumen por unidad y
  tareas agrupadas por día y sistema.

En el shell productivo actual solo se muestra **Resumen**. **Actividad** y
**Evidencia semanal** permanecen montadas y deshabilitadas para conservar sus
callbacks y contratos de componentes, listas para una futura reactivación.

Mientras esas vistas permanecen deshabilitadas, **Resumen** expone el selector
mensual, el filtro de flota y el selector ejecutivo de unidad. El selector semanal permanece
montado dentro del contrato de Evidencia semanal, pero no se muestra en la
cabecera ejecutiva.

La jerarquía ejecutiva de **Resumen** sigue la lectura de los reportes de
referencia: cabecera y filtros, cuatro KPIs críticos, tendencias diarias
separadas de horas-equipo fuera de servicio y equipos intervenidos, mix por sistema y
ranking de equipos, y finalmente los Paretos de actividad. Los agregados de
actividad quedan al final como contexto y no compiten visualmente con los
indicadores críticos.

El filtro de flota y el selector de unidad se aplican a disponibilidad,
downtime, MTBF, MTTR, actividad diaria, mix, ranking, ambos Paretos, indicadores
de contexto y detalle tabular. La clasificación sigue el catálogo de
Tribología: ``classified.parquet`` aporta ``unitId → machineName`` y el valor
de ``machineName`` es la flota/tipo de equipo visible (por ejemplo,
``BULL_022 → bulldozer``). Antes de unir ambas fuentes se normalizan mayúsculas,
guion/guion bajo y ceros de unidad (``BULL-022`` = ``BULL_022`` y
``T_09`` = ``T_9``). Si una unidad de Mantenciones no existe en el catálogo,
se clasifica en la categoría controlada ``otros``; no se infiere una flota desde
el prefijo del código. La unidad se filtra por ``machine_code``
y sus opciones se limitan a las flotas seleccionadas. Sin selección de
flota/unidad se conserva todo el período.

La metadata del contrato conserva el archivo fuente de los KPIs de tiempo,
su ventana de referencia y, cuando corresponde, la razón por la que no están
disponibles para un filtro;
estos detalles técnicos no se muestran en la cabecera ejecutiva.

### Confiabilidad mensual y fallas por componente

La sección **Confiabilidad mensual** usa el cliente activo del selector global
como `source_system` (EMIN, CAPSTONE o CDA) y consume las vistas materializadas
adicionales:

- `query_5_reliability_monthly.parquet`: una fila por `machine_id × year_month`.
  Alimenta las series de MTBF, MTTF, MTTR y `total_downtime_hours`; el filtro de
  equipo usa `machine_code`.
- `query_6_component_failure_ranking.parquet`: ranking histórico acumulado de
  componentes asociados a fallas. No se interpreta como una serie mensual.

Los valores nulos de MTBF, MTTF o MTTR se mantienen como ausencia de dato
suficiente para ese equipo-mes. Las filas con `low_confidence=true` se marcan
con una línea/leyenda visual de baja confianza y tooltip de advertencia; nunca
se eliminan ni se imputan. Si una vista aún no está descargada, la sección
queda en estado vacío o parcial explícito y el resto de la pestaña continúa
operativo.

Para mantener legibilidad aun cuando la hoja de Font Awesome no esté
disponible (por ejemplo, sin acceso al CDN), los iconos decorativos propios de
Mantenciones usan glifos Unicode locales con etiquetas accesibles. Los textos,
valores y títulos siguen siendo la fuente principal de significado. Los
gráficos de barras usan orientación vertical y los rankings categóricos se
ordenan de mayor a menor de izquierda a derecha. Las tendencias diarias
conservan el orden cronológico. El mix por sistema agrega las acciones sin
mostrar la unidad; el ranking de equipos muestra los sistemas involucrados
como colores apilados.
Para CDA se omiten las categorías genéricas Equipo/Cabina; para EMIN y CAPSTONE
se muestran todas las categorías disponibles. El cierre de la vista agrupa los
indicadores secundarios bajo **Indicadores de Interés**.

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

La tendencia diaria calcula horas-equipo fuera de servicio a partir de
`first_event_ts` y `last_event_ts` de `query_2_unit_records_actions.parquet`,
distribuyendo cada intervalo por día UTC y recortándolo al mes seleccionado.
Los intervalos superpuestos se unen por equipo y día antes de sumar la flota.
Si `query_2` no está disponible, se usa el mínimo/máximo `event_ts` por
`record_id` de `query_3` como compatibilidad. El total de una flota puede
superar 24 h en un día porque suma horas de varios equipos; con un equipo
seleccionado el máximo físico diario es 24 h. El mix por sistema agrega por
sistema y no expone series o leyenda por unidad; el ranking
de equipos conserva las unidades y los sistemas involucrados. Ambos usan la
misma métrica de acciones únicas. Los
Paretos ordenan por cantidad descendente y muestran acciones junto a la línea
de porcentaje acumulado; no representan frecuencia de fallas. CDA mantiene el
foco en Motor y Tren de Fuerza. EMIN y CAPSTONE no aplican una lista permitida
de sistemas: muestran un Pareto total por equipo y otro Pareto por todos los
sistemas, incluidos Equipo/Cabina cuando aparezcan en la fuente.

Los informes de referencia también muestran disponibilidad, indisponibilidad,
MTBF, MTTR, horas de reparación, backlog, metas y relaciones programado vs.
imprevisto. En esta iteración se usan las horas definidas por el origen:
`query_4` aporta el total móvil de 70 días y `query_2` aporta los límites
temporales de cada registro para la tendencia diaria. No se infieren horas a
partir del conteo de acciones.

#### Metodología de los KPIs de tiempo

Los cuatro valores priorizan `query_4_business_kpis.parquet` cuando están
disponibles `downtime_hours_70d` y `reference_date`. En ese caso la cobertura
es la **ventana móvil de 70 días** del KPI precalculado, aunque el selector de
Resumen siga mostrando un mes; esa diferencia se declara en
`meta.estimated_kpis.coverage` y en el banner. Si el extracto 70d está
ausente/incompleto, o se filtra por sistema/subsistema (que query_4 no
desglosa), el tiempo queda `null` con estado `unavailable`:

- `downtime_est_hours = sum(downtime_hours_70d)`.
- `scheduled_hours_proxy = equipos cubiertos × 70 días × 24 h`.
- `availability_est_pct = max(scheduled_hours_proxy − downtime_est_hours, 0) /
  scheduled_hours_proxy × 100`.
- `event_count` usa `repairs_70d`, luego `total_actions_70d` como denominador
  operativo para MTTR/MTBF.
- Los valores negativos o no finitos se consideran fuente inválida; no se
  reemplazan por cero ni por una estimación de acciones.

Cada payload expone en `meta.estimated_kpis` la fuente, columnas, unidad,
cobertura e hipótesis. Si faltan las columnas de tiempo se devuelve `null` y
un estado `unavailable`, nunca cero. La aplicación respeta la definición de
origen; no aplica un tope calendario ni convierte acciones a horas.

La comparación se realizó contra el catálogo de patrones y los informes
`Informe de Confiabilidad semanal W19.pdf` e `Informe Mensual Confiabilidad
Mantenimiento Mina Julio 2025.pdf`. Sus visuales de mayor valor son el
scorecard de KPIs, la tendencia temporal, la distribución por sistema y los
Paretos de frecuencia/tiempo de reparación. Esta primera iteración conserva la
jerarquía visual, pero reemplaza los indicadores no respaldados por actividad
registrada auditable.

La actividad mensual usa `query_3_actions_all_equipment.parquet`. Los timestamps
se normalizan a UTC, pero las agregaciones se agrupan por `change_date`, la
fecha operacional. Los Paretos usan `action_id` únicos y `machine_code` para
los cortes por equipo. En CDA el primer Pareto se filtra por Motor (acepta
`Motor`, `Sistema Motor` y `Sistema de Motor`) y el segundo por Tren de Fuerza.
En EMIN y CAPSTONE el primer Pareto incluye todos los sistemas por equipo y el
segundo agrupa las acciones por sistema, sin excluir categorías de origen. Los
títulos y `meta.pareto_scope` declaran el modo aplicado.
El detalle se limita a 250 filas por respuesta para no transferir la fuente
completa al navegador. En Resumen se presenta después de **Indicadores de
Interés** como una tabla paginada, ordenable y filtrable con fecha, unidad,
sistema, subsistema, tipo de acción y detalle.

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
acción, metas y clasificación de fallas. Las horas mostradas respetan las
definiciones disponibles en el origen; si falta el desglose temporal para un
filtro, el valor queda no disponible.
