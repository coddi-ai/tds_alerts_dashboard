# EMIN: tipo publicado y evidencia de mantenciones por sistema y ventana ISO

Fecha de revisión: 13 de octubre de 2026.

## Objetivo y sincronización

Retirar la reclasificación manual del dashboard. El tipo Multitécnica proviene
de los datos publicados: encontrar mantenciones no cambia `Trigger_type`.
Mostrar el contexto de mantenciones de las cuatro semanas ISO completas
anteriores a la alerta, con foco en el sistema y en el resumen semanal.

`git fetch origin dev` actualizó la referencia remota de `122113a` a
`280039de1069c05412efa5b5b996bd0756aa38e0`. El worktree anterior de este
chat permanece limpio en `64cb7f6`. No se actualizó mediante merge o rebase.

Se creó la tarea mediante el flujo aprobado `ai.ps1 task-new`:
- Tarea: `tds-alerts-dashboard--codex--emin-sistema-ventana-iso`.
- Rama: `ai/codex/emin-sistema-ventana-iso`.
- Worktree: `.worktrees/tds-alerts-dashboard/codex-emin-sistema-ventana-iso`.
- Base: `origin/dev`, commit `280039de1069c05412efa5b5b996bd0756aa38e0`.

Se revisaron AGENTS, estado Git, descriptor, claims y tareas activas antes de
editar. Se conservaron los cambios del meta-repo, del checkout principal y de
las demás tareas. No se leen secretos, no se cambian datos publicados ni
pipelines y no se ejecuta publicación, integración, merge, rebase o cherry-pick.

## Contrato y comportamiento

1. `Trigger_type` se conserva sin reclasificar ni filtrar las alertas. Los
   indicadores de telemetría y tribología mantienen el contrato publicado del
   loader. Las combinaciones Mixto existentes siguen siendo Mixto, con o sin
   mantenciones asociadas.
2. La semana de la alerta se calcula desde su `Timestamp` normalizado por el
   loader. Se consultan únicamente cuatro CSV `mantentions/golden/emin/WW-YYYY.csv`,
   identificados con el año **ISO**, sin depender de una sola referencia
   `Semana_Resumen_Mantencion` ni inferir una semana cuando falta la fecha.
3. Intervalo: `[lunes 00:00 de W-4, lunes 00:00 de W)`. Se excluyen toda la
   semana de la alerta y semanas más antiguas. Las actividades deben tener
   una fecha que pertenezca también a la semana ISO de su archivo.
4. Se exige la misma unidad, quitando espacios extremos, y el sistema de
   `sistema` frente a las claves de `Tasks_List`. Se normalizan mayúsculas,
   acentos, espacios, los prefijos `Sistema` / `Sistema de` y los alias
   bilingües enumerados en el contrato semanal.
   En `Sistema - Subsistema` se compara el sistema, sin atribuir un subsistema
   a otro sistema. No se usan búsquedas parciales ni menciones en el mensaje IA,
   el resumen o el componente para inventar una correspondencia.
5. `Equipo`, `Otros`, ausencia de sistema o `Desconocido` no prueban un sistema
   técnico. Las fechas ISO completas se validan antes de usarlas. Las etiquetas
   `Viernes 10/07` se resuelven únicamente dentro de la semana del archivo y
   verifican el día de semana; una etiqueta sin fecha suficiente no se infiere.
6. Las comparaciones conservan el reloj UTC-naive establecido para las alertas;
   la presentación general de fechas conserva su conversión existente. Los
   timestamps de actividad EMIN conservan la hora escrita, de acuerdo con el
   contrato de ingesta de mantenciones: se valida la fecha y se descarta su
   sufijo sin interpretarlo como un offset real ni convertirlo a UTC.
7. El detalle y el resumen de la alerta comparten el mismo resolver. Se
   muestran las actividades atribuibles al sistema y período. `Summary` se
   conserva como **resumen semanal de la unidad**, rotulado como contexto de
   todos los sistemas: la fuente no ofrece un resumen separado por sistema y
   puede mencionar antecedentes históricos. No se convierte ese texto en
   prueba adicional, diagnóstico por sistema o duración de detención.
8. El contexto se resuelve fuera de la caché del CSV de alertas, de modo que
   cambiar o borrar un archivo semanal se refleja sin reiniciar. La caché
   dentro de una carga distingue unidad, sistema y ventana, evitando que dos
   alertas del mismo equipo hereden evidencia de sistemas distintos.
9. El detalle explica explícitamente falta de datos, falta de correspondencia
   y casos no determinables. CDA y Capstone siguen usando su contrato anterior
   y no consultan el resolver EMIN.

Este comportamiento reemplaza la regla del documento histórico
`auditoria_correo_emin_dev.md` que promovía Evento + Mantenimiento a Mixto y
mostraba todas las actividades de la unidad. Ese documento describe la
publicación anterior; no es la regla vigente de este cambio.

## Validaciones

Se usan las dependencias locales del dashboard con prioridad en PYTHONPATH y
FastAPI del entorno local de Hermes; sin instalar paquetes. Se usa
`PYTHONDONTWRITEBYTECODE=1` y `TMP`/`TEMP` en `.coddi-local/t`.

| Comando | Resultado |
| --- | --- |
| `git fetch origin dev` | Correcto; referencia actualizada a 280039d. Requirió acceso de red y confianza limitada al worktree anterior mediante `git -c safe.directory=<worktree>`; no se cambió configuración global. |
| `python -m pytest -q tests`, antes de editar | 997 pasan, 0 fallan, 10 omitidas; 72 advertencias. Salida 0. Registro: `.coddi-local/validation-before.txt`. |
| `python -m pytest -q tests/test_emin_alert_evidence.py tests/test_w34_timestamps.py tests/test_w34_alerts_table.py tests/test_i18n.py` | 132 pasan, 0 fallan; salida 0. Registro: `.coddi-local/validation-focused.txt`. |
| `python -m pytest -q tests`, final | **1036 pasan, 0 fallan, 10 omitidas**; 71 advertencias, salida 0. Registro: `.coddi-local/validation-after.txt`. |
| `Get-Content -Raw -Encoding UTF8 .coddi-local/check_emin_scope.py \| python -`, con `DASHBOARD_DATA_ROOT` en el directorio local del dashboard | Correcto; lectura de 281 alertas, tipos publicados intactos, fechas y sistemas de todas las actividades mostradas comprobados. Resultado agregado: `.coddi-local/actual-emin-scope.json`. |
| `git diff --check` | Sin errores de espacios. |

Las pruebas cubren sistema coincidente y distinto, summary sin actividades
atribuibles, fecha inválida, el límite inferior exacto, la exclusión del lunes
de la semana de la alerta, datos antiguos y archivos mal etiquetados, cambio
de año ISO y semana 53, sufijos de ingesta EMIN, tipo publicado intacto,
combinaciones telemetría/aceite, actualización/borrado de archivos semanales,
coherencia de tabla/contador/resumen/detalle y ausencia de regresiones en los
otros clientes.

La lectura local contiene 281 alertas publicadas como Telemetría: se muestran
281 como Telemetría y el contador Mixto es cero. Una tiene mantenciones
atribuibles al sistema y al período; 104 tienen contexto no atribuible con
certeza, 82 no tienen registros para la unidad en la ventana, 77 tienen sistema
de alerta no técnico/no determinado y 17 no tienen actividades del sistema.
Las fechas de las tareas consultadas son válidas; la limitación es la
atribución del sistema, con alta presencia de `Equipo - Equipo` en la fuente.

## Handoff y límites

Archivos: resolver EMIN, loaders, callbacks de alertas, tabla/detalle de
mantenciones, ambos catálogos de idioma, pruebas EMIN y este documento.
Commit y estado final se registran en el handoff de la tarea.

Las diez omisiones del perfil offline ya existían. No se validan servicios
externos ni la plataforma desplegada. El contrato de la fuente semanal no
permite separar por sistema el resumen narrativo de la unidad ni acreditar
detenciones y su duración. Se conserva esa limitación visible en la interfaz.

Siguiente acción: revisar e integrar el commit local con el flujo humano del
repositorio; publicación y despliegue pendientes de autorización específica.
