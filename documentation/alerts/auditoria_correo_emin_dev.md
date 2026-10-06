# EMIN: cambios locales y comprobación del correo

## Objetivo y alcance

Actualizar la referencia remota `origin/dev`, corregir localmente las brechas
del correo y comprobar cada compromiso con el código y los archivos que ya
consume el dashboard. No se usa el ETL de migración ni se modifica el productor
de alertas que maneja Claude.

`git fetch --no-tags origin dev` actualizó `origin/dev` de `a77b084` a
`35ce3338057d37036baef0b67daf9472c39620c7`. Los cambios de esta tarea están
aislados en `ai/codex/auditar-correo-emin-dev`, creada con `ai.ps1 task-new`
sobre esa versión. Los cambios ajenos del checkout original se conservaron.
El parche anterior `a521fb8` no estaba integrado en la nueva referencia:
su lógica se adaptó localmente, respetando la nueva traducción de la interfaz.

No se ejecutó push, merge, rebase ni despliegue. Esta comprobación corresponde
al código y a los datos locales, no a una plataforma ya publicada.

## Comprobación de los compromisos

| Compromiso | Encontrado en origin/dev actualizado | Resultado local |
| --- | --- | --- |
| Mensaje informativo cuando faltan series de telemetría | Seguía mostrando «No hay datos de telemetría disponibles». | Corregido en español e inglés. Explica que la alerta está registrada, que faltan series de sensores para mostrar tendencias y dónde revisar la alerta y las otras evidencias. Se comprueban archivo ausente y ausencia de coincidencia para la alerta. |
| Multitécnica con al menos dos fuentes, más allá de Evento + Aceite | El dashboard tomaba únicamente el tipo publicado. Las 281 alertas locales EMIN seguían como Telemetría. | Parche de clasificación en el dashboard: evento + mantenimiento realmente resoluble se muestra como Multitécnica. 100 de 281 alertas locales cumplen la regla; 181 siguen como Telemetría. El tipo original se conserva y no se inventa tribología. La generación del productor externo no fue modificada ni auditada. |
| Presentación de detenciones en el resumen de alertas | El resumen mostraba diagnóstico, causa, acción y etiquetas de telemetría/tribología; el mantenimiento estaba solo en el detalle. | El resumen ahora muestra semana, resumen y actividades de la evidencia externa que sostiene la clasificación. Los archivos vinculados contienen mantenciones; no traen una duración de detención asociada a cada alerta. Se informa «Duración de detención: no informada para esta alerta». No se puede acreditar el compromiso de detenciones confirmadas con estos datos. |
| Pareto por acciones y duración | Ya incorporado para EMIN mediante dos gráficos independientes. | Verificado con datos locales: Pareto de acciones únicas por unidad y Pareto de horas intervenidas por unidad. El filtro de sistemas afecta las acciones y no recalcula las horas como si fueran un conteo. |
| Resumen por unidad con navegación más intuitiva | Ya incorporado por los nuevos commits remotos. | Verificado: acceso desde la fila de flota, ruta por unidad, cabecera fija, volver, anterior/siguiente y selector de unidad. La unidad de una alerta EMIN se resuelve y el contenido se construye sin error. No se evaluó usabilidad con Sergio ni la versión desplegada. |

## Regla y contrato utilizado

Únicamente archivos bajo `DASHBOARD_DATA_ROOT` (o `data`):

- `alerts/golden/emin/consolidated_alerts.csv`: `UnitId`,
  `Trigger_type`, `Semana_Resumen_Mantencion`, identificadores existentes.
- `mantentions/golden/emin/<WW-YYYY>.csv`: `UnitId`, `Summary`,
  `Tasks_List`.

Se exige la misma unidad, quitando espacios extremos, en la semana referenciada
por la alerta; resumen textual no vacío o JSON de actividades no vacías bajo
el contrato `{dia: {sistema: [actividad, ...]}}`. Se selecciona la primera
fila con contenido, también para el detalle. Un archivo ausente/corrupto,
referencia inválida, otro equipo o contenido vacío no agrega evidencia.
Una mención en el mensaje IA no es una segunda fuente.

Se derivan en memoria `has_maintenance`, `maintenance_evidence_summary`,
`maintenance_evidence_tasks` y `Trigger_type_original`. Solo EMIN obtiene
esta reclasificación. Los indicadores de telemetría y aceite permanecen
independientes: evento + mantenimiento no abre una sección de aceite.
Los casos ya publicados como Mixto se conservan.

La clasificación, etiquetas, contador, resumen y detalle son coherentes.
Se resuelve la evidencia fuera de la caché del CSV de alertas para que los
cambios y borrados semanales se reflejen sin reiniciar. El detalle EMIN muestra
actividades del equipo en todos los sistemas, igual que el contexto del resumen.
Los textos de datos fuente se conservan; se traduce únicamente la interfaz.

## Validación

Se usaron dependencias locales del dashboard y FastAPI del entorno de Hermes,
sin instalar paquetes. `PYTHONPATH` dio prioridad al entorno del dashboard.
`PYTHONDONTWRITEBYTECODE=1`; `TMP` y `TEMP` dentro de `.coddi-local/t`.

| Comando exacto | Resultado |
| --- | --- |
| `git fetch --no-tags origin dev` | Correcto: referencia actualizada a 35ce333. |
| `python -m pytest -q tests`, antes de editar | 936 pasan, 9 fallan, 10 omitidas. Registro local: `.coddi-local/validation-full.txt`. |
| `python -m pytest -q tests`, después de corregir | 962 pasan, los mismos 9 fallan, 10 omitidas. Las 26 pruebas añadidas pasan. Registro: `.coddi-local/validation-final.txt`. |
| `Get-Content -Raw -Encoding UTF8 .coddi-local/check_promises.py \| python -`, con `DASHBOARD_DATA_ROOT` apuntando al directorio local del dashboard | Correcto: clasificación, contador, mensaje, resumen con contenido real, Pareto y cabecera/navegación por unidad. Resultado agregado: `.coddi-local/audit-behaviour.json`. |
| `git diff --check` | Sin errores de espacios. |

La suite global sigue sin estar aprobada: nueve fallos preexistentes de
Campbell AI (cinco con fechas fijas fuera de la ventana actual, tres de gráficos
sin el workbook de ensayos en este worktree, uno de orden de conversaciones).
Un fallo introducido por el orden de claves de traducción fue corregido antes
de la validación final.

Comprobación con datos locales: 281 alertas, 100 Multitécnica, 181 Telemetría,
0 con tribología. En julio de 2026 los Pareto muestran 2.956 acciones en 529
unidades y 9.816,9525 horas-equipo intervenidas en 534 unidades; ambas figuras
contienen barras con sus unidades de medida correctas. Estas horas son de
intervenciones de mantención, no una confirmación de detenciones de la alerta.

## Ajustes necesarios al correo

No debe anunciarse que estos cambios locales ya están publicados hasta el
despliegue. Después de publicarlos, los puntos verificables pueden expresarse así:

- «La plataforma muestra como Multitécnica las alertas de evento que cuentan
  con evidencia adicional de mantenciones vinculada al equipo y la semana,
  además de los cruces ya existentes con aceite».
- «Se incorporó al resumen de alertas el contexto de mantenciones disponible,
  con semana, resumen y actividades reportadas. La duración de detención se
  indica como no informada cuando no existe ese dato vinculado».
- Reemplazo de **[CAMBIAR]**: «El Informe de Confiabilidad incorpora dos gráficos
  de Pareto por unidad: uno por número de acciones únicas y otro por horas
  intervenidas».

Para sostener literalmente «eventos + detenciones» o confirmar duración por
alerta se necesita que el productor publique una detención identificable,
equipo, inicio/fin o duración, fuente y vínculo con la alerta. Los CSV
actualmente vinculados solo entregan contexto semanal de mantenciones.
No se añadieron cruces nuevos con fuentes del ETL ni se infirieron detenciones
desde menciones IA o desde las horas agregadas de mantenciones.

## Handoff

Trabajo terminado: descarga remota, cambios locales, auditoría antes/después,
26 casos nuevos y comprobación funcional con los datos disponibles.
Archivos cambiados: `src/data/emin_alert_evidence.py`, `src/data/loaders.py`,
`dashboard/components/alerts_report.py`, `dashboard/components/alerts_tables.py`,
`dashboard/callbacks/alerts_callbacks.py`, ambos catálogos de idioma,
`tests/test_emin_alert_evidence.py` y este documento.
Los commits locales se registran en el handoff de
`tds-alerts-dashboard--codex--auditar-correo-emin-dev`.

Riesgos y pendiente: suite global con los fallos descritos; asociación
contextual equipo/semana que no demuestra causalidad; generación externa no
auditada; ninguna comprobación de la versión desplegada.

Siguiente acción: revisar el diff y los resultados, resolver o aceptar los
fallos globales, previsualizar la integración con `ai.ps1 integrate` y gestionar
integración/publicación bajo control humano. Revisar la plataforma después del
despliegue. La evolución de evidencia de detenciones corresponde al productor
que gestiona Claude; no se le enviaron mensajes desde esta tarea.
