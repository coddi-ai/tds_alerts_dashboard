# Auditoría de filtros e informe de confiabilidad EMIN

Fecha: 2026-10-06. Tarea: `tds-alerts-dashboard--codex--confiabilidad-emin-filtros`.

**Actualización de publicación:** el resultado final tras incorporar los commits
recientes de `origin/dev` es **983 pruebas aprobadas, 6 omitidas y ningún fallo**.
Los nueve fallos de Campbell AI descritos abajo corresponden a la base anterior.
El detalle de esta actualización aparece al final del informe.

## Objetivo, alcance y resultado

Auditar y corregir el selector global de sistemas, los indicadores y gráficos
del informe EMIN; comprobar que CDA y Capstone conservan su comportamiento.
Trabajo en la rama `ai/codex/confiabilidad-emin-filtros`, base
`35ce3338057d37036baef0b67daf9472c39620c7`.

Las 74 pruebas de Mantenciones pasan. La suite offline completa termina con
948 aprobadas, 9 fallidas, 6 omitidas y 69 advertencias. Los nueve fallos son
de Campbell AI y siguen pendientes; el repositorio completo no está validado.
La interfaz se comprobó con datos sintéticos usando el layout, los callbacks
y los estilos de producción. No se encontraron más fallos en los casos EMIN
auditados tras las correcciones.

## Correcciones encontradas durante la auditoría

| Hallazgo | Corrección y evidencia |
|---|---|
| El filtro de actividad estrechaba también el Pareto independiente de CDA/Capstone. | El alcance global por sistemas se aplica solo a EMIN; regresión parametrizada para ambos clientes. |
| Una variable de sistemas se sobrescribía con la población de Pareto. | Series separadas para agregados de actividad y Pareto. |
| Acciones sin sistema quedaban fuera del número de sistemas y mostraban etiquetas distintas en detalle. | Nulos y blancos se agrupan como `Sin sistema` en el contrato EMIN. |
| Filtros ocultos de actividad afectaban al selector global EMIN. | El callback ignora los filtros ocultos de sistemas, equipos y subsistemas. |
| Sistemas sin color fijo cambiaban de color al filtrar unidades/sistemas. | Los tres gráficos comparten la paleta del catálogo completo; regresión con Sistema Eléctrico. |
| Una intersección vacía de flota/unidad recuperaba el MTBF/MTTR de toda la flota. | Lista vacía EMIN permanece vacía; `None` conserva el significado de todos. |
| La fuente genérica `Equipo` aparecía como sistema técnico en las tablas. | Etiqueta visible `General del equipo`; el valor original sigue disponible para filtrar. |
| Persistía una nota técnica del catálogo en el filtro de flotas EMIN. | Nota visible solo en los otros clientes. |
| Mensajes de horas no disponibles se cortaban en móvil. | Anotación partida en líneas en ambos gráficos de horas. |
| Conteos pequeños solo mostraban el cero en el eje. | Ticks enteros adaptados a los conteos EMIN. |
| Un solo día mostraba horas y microsegundos en el eje de fechas. | Formato explícito día/mes/año y tick único cuando corresponde. |
| El aviso amarillo de selección parcial tenía poco contraste sobre blanco. | Color marrón oscuro, limitado al aviso EMIN con rol `status`; verificado en navegador. |

Las nuevas regresiones reprodujeron cinco fallos iniciales correspondientes a
cuatro defectos; las pruebas posteriores también reprodujeron el retorno
incorrecto de MTBF/MTTR para una intersección vacía. Todas pasan tras corregir.

## Comprobaciones funcionales y visuales

- Selección vacía y selección completa de sistemas equivalen a todos.
- Selección parcial filtra acciones, detalle y gráficos de actividad; horas,
  disponibilidad, downtime, MTBF y MTTR quedan no disponibles, con explicación.
- Pareto conserva denominador completo y corte 80% más tres unidades; el
  control de expansión no aparece en EMIN.
- Colores consistentes entre mix, equipos y Pareto aun al cambiar filtros.
- Filtros por mes, flota y unidad; selección de una fila; restablecimiento de
  unidad conservando el mes y la flota.
- Caso completo sintético: cinco acciones, cuatro sistemas, seis horas,
  disponibilidad 93,8%, MTBF 18 h y MTTR 3 h.
- Caso General del equipo: una acción, un sistema y ningún indicador temporal;
  la fecha del gráfico queda `02/01/2026`.
- Escritorio, móvil de 390 px y tableta de 768 px. Sin desbordamiento horizontal
  del documento en móvil/tableta; aviso de horas legible. Consola sin errores
  en las comprobaciones realizadas.
- Capturas y harness local en `.coddi-local/audit-desktop.jpg`,
  `.coddi-local/audit-mobile.jpg` y `.coddi-local/audit_dashboard.py`.
  La captura móvil precede al último cambio de contraste y formato de fecha.

## Validaciones reproducibles

Desde el worktree asignado, con el entorno existente; no se instalaron paquetes:

```powershell
$auditPython = 'C:\Users\panch\Desktop\Coddi\.worktrees\tds-alerts-dashboard\claude-dashboard-w34\.venv\Scripts\python.exe'
& $auditPython -m pytest -q tests --basetemp '.coddi-local/audit-complete-tmp' -p no:cacheprovider --tb=short --disable-warnings --junitxml='.coddi-local/audit-complete.xml'
```

Resultado final: **948 passed, 9 failed, 6 skipped, 69 warnings**, 33,78 s,
salida 1. Dentro de este perfil, las 74 pruebas de Mantenciones pasan.
El perfil específico final también produjo
**74 passed, 8 warnings**:

```powershell
& $auditPython -m pytest -q tests/test_mantenciones_productive.py --basetemp '.coddi-local/audit-focused-final-tmp' -p no:cacheprovider --tb=short
```

`git diff --check`: salida 0, sin errores de espacios; Git advierte sobre
normalización LF/CRLF. Evidencia completa del perfil en
`.coddi-local/audit-complete.xml`.

## Nueve fallos pendientes de Campbell AI

| Archivo | Pruebas fallidas | Causa reproducida |
|---|---:|---|
| `tests/test_campbell_ai.py` | 5 | Fixtures de julio de 2026 fuera de la ventana relativa de 60 días al ejecutar el 6 de octubre. |
| `tests/test_campbell_ai_chart_types.py` | 3 | Falta `data/oil/essays_elements.xlsx`; el catálogo alternativo no cubre todos los grupos requeridos por las pruebas. |
| `tests/test_campbell_ai_persistence.py` | 1 | Dos escrituras reciben el mismo timestamp en Windows; el orden por fecha no desempata de forma determinista. |

Son los mismos nueve fallos del perfil previo. Los archivos Campbell AI no
están modificados respecto a la base de esta tarea y no importan el repositorio
de Mantenciones. Un experimento diagnóstico, aplicando únicamente en memoria
una fecha fija, un catálogo sintético y timestamps crecientes, hizo pasar las
nueve pruebas (`.coddi-local/audit_campbell_diagnostic.py`). Este resultado
explica los fallos y **no sustituye la suite real ni constituye una reparación**.

## Archivos, commits y decisiones

Archivos cambiados: `dashboard/assets/custom_layout.css`,
`dashboard/callbacks/mantenciones_general_callbacks.py`,
`dashboard/tabs/tab_mantenciones_general.py`,
`src/data/maintenance_repository.py`, `tests/test_mantenciones_productive.py`
y este informe. Commits nuevos: ninguno. Cambios locales pendientes de revisión.

Se preservó el alcance registrado. No se modificaron módulos Campbell AI ni
otras ramas/worktrees. El servidor local de pruebas se detuvo al finalizar.
No hubo integración, publicación remota ni cambios de fuentes reales.

## Riesgos, trabajo pendiente y siguiente acción

- El worktree no contiene `data/mantentions/golden/emin/Maintance_Labeler_Views`.
  Falta conciliar estos cambios con los Parquet reales en una ruta asignada.
- No se validaron AWS, S3, pipelines, servicios externos ni el despliegue.
  Las reglas del workspace requieren aprobación explícita para integración.
- Campbell AI necesita una tarea con archivos reclamados para reparar las
  nueve pruebas; la suite general sigue fallando hasta entonces.
- Diagnóstico del meta-repo: `.\ai.ps1 doctor` termina con salida 1 porque
  el manifiesto contiene once repositorios y exige exactamente nueve. También
  informa instrucciones pendientes y falta de remoto `origin` en un repositorio
  ajeno a esta tarea. No se modificó la configuración compartida.
- `.\ai.ps1 sync-instructions -Check`: salida 1; instrucciones ausentes o
  desincronizadas en el meta-repo y los once repositorios. Su regeneración
  afecta rutas ajenas a la tarea y queda pendiente del flujo de coordinación.
- La rama parte de una base anterior a otros trabajos. La integración y su
  validación corresponden al flujo supervisado del workspace.

Siguiente acción: revisar este diff, asignar las reparaciones de Campbell AI y
la conciliación con datos reales; repetir el perfil completo tras integrar.
La tarea queda en handoff, sin declararla completa globalmente.

## Actualización tras la solicitud de publicación

La persona usuaria solicitó publicar estos cambios en `origin/dev`.
Se consultó el remoto `https://github.com/coddi-ai/tds_alerts_dashboard.git`.
La referencia remota estaba en `64cb7f6b9146034e1635e15eb74cde05f64530a1`,
dos commits por delante de la base original. Incluyen reparaciones de las
pruebas de Campbell AI que fallaban en la auditoría inicial.

- Commit de cambios EMIN: `335cfd78a34d5068a99bb1ed6b9760984f8301be`.
- Previsualización: `.\ai.ps1 integrate -TaskId tds-alerts-dashboard--codex--confiabilidad-emin-filtros -Target origin/dev`.
- Incorporación de la referencia remota en la rama asignada, sin conflictos:
  `7d858546adc1d3e5fb02c3d68e1d1c0d97cdbece`. No se cambió la rama del
  checkout principal ni se editaron otros worktrees.
- `git merge-base --is-ancestor origin/dev HEAD`: salida 0; la historia remota
  se conserva. El diff frente a `origin/dev` contiene solo los seis archivos
  de esta tarea.

Validación del código combinado, ejecutada antes de publicar:

```powershell
& $auditPython -m pytest -q tests --basetemp '.coddi-local/publish-offline-tmp' -p no:cacheprovider --tb=short --disable-warnings --junitxml='.coddi-local/publish-offline.xml'
```

Resultado: **983 passed, 6 skipped, 72 warnings**, 34,40 s, salida 0.
Las seis omisiones siguen sin representar pruebas ejecutadas. Los problemas
de coordinación del meta-repo y la validación con datos reales/despliegue
descritos en la auditoría inicial permanecen fuera de esta publicación.
