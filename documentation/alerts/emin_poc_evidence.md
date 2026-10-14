# EMIN POC: evidencias de alertas Multitécnica

Revisión: 14 de octubre de 2026.

## Objetivo y base

Corregir las evidencias del detalle sin reclasificar el tipo publicado.
Caso reportado: `F-c166471923b2a4a5-1747641987`, BULL-031, Sistema de
Motor / Refrigerante, 19/05/2025 04:06 en la interfaz.

La referencia `origin/dev` se actualizó mediante `git fetch origin dev`
y permanece en `3ffc0a4e6d2e367c3e7061a4ac37a45db48d01fa`.
El worktree anterior está limpio. Se creó una nueva tarea con el flujo
`ai.ps1 task-new`, conservando las otras tareas y los cambios del checkout
principal y del meta-repo.

- Tarea: `tds-alerts-dashboard--codex--emin-poc-evidencias-reales`.
- Rama: `ai/codex/emin-poc-evidencias-reales`.
- Worktree: `.worktrees/tds-alerts-dashboard/codex-emin-poc-evidencias-reales`.
- Base: commit `3ffc0a4` de `origin/dev`.

## Reproducción y causas

Se accedió a la POC indicada por el usuario, se seleccionó EMIN y se abrió
el identificador exacto. La POC reproduce la captura: fuente Multitécnica,
etiqueta Telemetría + Tribología, ausencia de series de sensores, aviso de
muestra de aceite vacía y mantenimiento no atribuible.

Se confirmaron dos causas en el código y en los archivos del dashboard:

1. El loader convertía todo `Mixto` en `has_telemetry=True` y
   `has_tribology=True`. Eso seguía el contrato histórico Evento + Aceite y
   no representa todas las combinaciones actuales de EMIN. Una referencia de
   aceite vacía terminaba comparándose con las muestras y generaba el aviso
   «Reporte no encontrado para muestra:».
2. Los CSV históricos de 2025 usan numeración de semana con lunes inicial
   `%W`, que difiere de ISO. El archivo local `19-2025.csv` contiene una
   actividad de BULL-031 con fecha explícita `Domingo 18/05`, bajo
   `Sistema de Motor - Sistema de Enfriamiento`. Esa fecha es semana ISO 20.
   El resolver anterior exigía la semana ISO del nombre y descartaba la fila.

El CSV consolidado local de alertas no contiene el identificador exacto de la
POC. La reproducción del problema se verificó en el navegador y la mantención
histórica se comprobó en los archivos locales existentes. Las pruebas usan
fixtures del formato observado y no presentan identificadores de evento de
prueba como referencias recuperadas de producción.

## Corrección

- `Trigger_type` se conserva exactamente como se publica. EMIN resuelve las
  fuentes por sus referencias: TelemetryID y SourceType=Telemetry o el tipo
  unívoco Telemetria para el evento; TribologyID o su alias documentado
  OilReportNumber para la muestra. Mixto por sí solo no declara aceite.
- La etiqueta de evidencia y las secciones comparten los indicadores
  corregidos del loader EMIN. Las combinaciones válidas Evento + Aceite se
  mantienen si existen las referencias. La ausencia de alguna evidencia no
  cambia el tipo Multitécnica: se informa que no están disponibles todas
  las fuentes.
- El panel de aceite evita leer muestras cuando no hay referencia y no
  imprime identificadores vacíos. La búsqueda normaliza de igual manera
  referencias de CSV y números de muestra, incluyendo sufijos numéricos .0.
- Si faltan series de sensores, el detalle EMIN muestra la información de
  evento incluida en la alerta: referencia si existe, fecha y señal.
  Declara expresamente la ausencia de series. No fabrica curvas, eventos
  externos, identificadores ni campos extraídos del diagnóstico IA.
- Para mantenciones se consultan candidatos de nombres ISO y %W, generados
  desde los mismos cuatro lunes de la ventana. Pueden ser cinco nombres de
  archivo, pero el período de evidencia sigue siendo estrictamente
  `[lunes W-4 00:00, lunes W 00:00)`.
- Las fechas de actividades se validan contra ambos calendarios permitidos
  para su archivo y se filtran por el intervalo real. DD/MM se resuelve
  únicamente dentro de esas semanas candidatas y se verifica el día escrito.
  Se conserva la semántica de reloj de EMIN. Se mantiene el filtro de sistema.
- La semana mostrada proviene de la fecha efectiva en calendario ISO.
  El caso recupera 18/05/2025 como semana ISO 20-2025. Se ordenan las
  actividades y se eliminan duplicados si coexisten los dos nombres.
- Se conserva el resumen semanal de la unidad como contexto, con su rótulo;
  las actividades detalladas pertenecen al sistema afectado. No se infieren
  detenciones, duración ni trabajos que la fuente no especifica.
- CDA y Capstone conservan sus indicadores de fuente anteriores. Se cubren
  sus contratos en las pruebas focalizadas y la suite global.

## Validación

Se utilizaron las dependencias locales del dashboard y FastAPI disponible
localmente, con prioridad del entorno del dashboard en PYTHONPATH.
`PYTHONDONTWRITEBYTECODE=1`; TMP y TEMP en `.coddi-local/t`.

| Comando o comprobación | Resultado |
| --- | --- |
| `git -c safe.directory=<worktree anterior> fetch origin dev` | Correcto; base 3ffc0a4, sin cambios remotos nuevos. |
| `python -m pytest -q tests`, antes | 1036 pasan, 0 fallan, 10 omitidas; 71 advertencias. Registro: `.coddi-local/validation-before.txt`. |
| `python -m pytest -q tests/test_emin_poc_evidence.py tests/test_emin_alert_evidence.py tests/test_capstone_contract.py tests/test_i18n.py` | 136 pasan, 0 fallan; 3 advertencias. Registro: `.coddi-local/validation-focused.txt`. |
| `python -m pytest -q tests`, final | **1067 pasan, 0 fallan, 10 omitidas**; 72 advertencias, salida 0. Registro: `.coddi-local/validation-after.txt`. |
| `Get-Content -Raw -Encoding UTF8 .coddi-local/verify_poc_case.py \| python -`, con DASHBOARD_DATA_ROOT local | Correcto; BULL-031, actividad 18/05, sistema de enfriamiento, resumen recuperado, ventana 21/04 a 19/05 exclusiva. Registro: `.coddi-local/bull031-verification.json`. |
| Navegador POC | Caso original reproducido con el mismo identificador. |
| Navegador local en 127.0.0.1:8067 | Componentes corregidos revisados visualmente con la mantención histórica real y los datos de la captura; la referencia de evento desconocida se deja sin informar. Captura: `.coddi-local/emin-poc-evidence-after.jpg`. |
| `git diff --check` | Sin errores de espacios. |

Los 31 casos adicionales cubren referencias vacías, tipo Mixto sin aceite,
alias de muestra, referencias numéricas, fuente no determinable, conservación
de tipo, eventos sin series, calendario histórico %W, fechas justo en los
límites, cambio de año con 53-2024, deduplicación y preservación de otros
clientes.

La lectura del consolidado local sigue mostrando sus 281 tipos originales:
todos Telemetría, cero referencias de aceite y una alerta con contexto de
mantenciones del sistema y período. No se cambian datos ni pipelines.

## Handoff y límites

Archivos: callbacks, resolver EMIN, loaders, dos catálogos de idioma, pruebas
EMIN, nuevas pruebas POC y este documento. Commit y resultado final se
registran en el handoff de la tarea.

La vista local reconstruye datos de la captura y utiliza el resumen semanal
real disponible localmente. No acredita disponer del CSV consolidado actual
del servidor ni de sus series. La captura visual es una revisión local y
está rotulada como tal. La POC sigue pendiente de recibir el cambio.

Las diez omisiones del perfil offline ya existían. Se conserva la
limitación del resumen semanal de unidad y de las fuentes externas sin
referencia. Se requiere publicación autorizada y verificación del despliegue
antes de declarar corregida la POC productiva.
