# EMIN: retirar información redundante del evento

Fecha: 14 de octubre de 2026.

## Objetivo y base

Retirar el bloque «Evento registrado» que duplicaba los datos de la cabecera
en el detalle EMIN. La cabecera de la alerta conserva fecha, unidad,
sistema, componente, señal, tipo publicado y análisis.

Se actualizó la referencia con `git fetch origin dev`; la base sigue siendo
`afbbb1bd04c1a4b698e87c7d3a97ac83613ba0f6`. Se creó una tarea mediante
`ai.ps1 task-new`, después de revisar AGENTS, estado, claims y descriptor:

- Tarea: `tds-alerts-dashboard--codex--emin-quitar-evento-redundante`.
- Rama: `ai/codex/emin-quitar-evento-redundante`.
- Worktree: `.worktrees/tds-alerts-dashboard/codex-emin-quitar-evento-redundante`.

## Cambio

Se elimina el renderer del bloque redundante y sus tres textos de interfaz
en ambos idiomas. Cuando no hay series de sensores EMIN vinculadas, esa
sección no agrega contenido. Si existen series, se conserva el render de
gráficos. Las evidencias de aceite y mantenimiento siguen su flujo anterior,
incluyendo las fechas históricas y los resúmenes de mantenciones corregidos.

Se ajustan las pruebas existentes para verificar la ausencia del bloque y
la conservación de la fecha, el tipo Multitécnica y el mantenimiento del caso
BULL-031. Los loaders, tipos publicados, datos y pipelines no se modifican.

## Validación

Dependencias locales del dashboard con FastAPI disponible localmente;
PYTHONPATH prioriza el entorno del dashboard. PYTHONDONTWRITEBYTECODE=1;
TMP y TEMP bajo `.coddi-local/t`.

| Comando | Resultado |
| --- | --- |
| `git -c safe.directory=<worktree anterior> fetch origin dev` | Correcto; base afbbb1b sin cambios nuevos. |
| `python -m pytest -q tests`, antes de editar | 1067 pasan, 0 fallan, 10 omitidas; salida 0. Registro: `.coddi-local/validation-before.txt`. |
| `python -m pytest -q tests/test_emin_alert_evidence.py tests/test_emin_poc_evidence.py tests/test_capstone_contract.py tests/test_i18n.py` | 136 pasan, 0 fallan; salida 0. Registro: `.coddi-local/validation-focused.txt`. |
| `python -m pytest -q tests`, después | 1067 pasan, 0 fallan, 10 omitidas; 72 advertencias, salida 0. Registro: `.coddi-local/validation-after.txt`. |
| `git diff --check` | Sin errores de espacios. |

## Handoff

Archivos: callbacks de alertas, dos catálogos de idioma, dos archivos de
pruebas y este documento. Commit local y resultado final en el handoff de
la tarea.

Las diez omisiones ya existían en el perfil offline. El cambio permanece
local hasta su publicación autorizada y posterior despliegue en la POC.
Se conservaron las demás tareas y los cambios existentes del workspace.
