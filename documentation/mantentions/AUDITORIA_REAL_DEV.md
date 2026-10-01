# Auditoría real y handoff del informe EMIN en dev

Fecha: 2026-10-01. Tarea: `tds-alerts-dashboard--codex--auditoria-emin-dev-real`.

## Objetivo y estado

Aplicar los ajustes del informe EMIN a la rama `dev` local y auditarlos con
los datos reales disponibles. Los cambios están aplicados y la auditoría
específica es satisfactoria. El perfil completo se ejecutó y conserva nueve
fallos en Campbell AI: la validación global permanece pendiente.

## Rama, alcance y decisiones

- Worktree: `.worktrees/tds-alerts-dashboard/dev-integracion-mantenciones`.
- Rama `dev`, base `4bda5c34788afe9d4745e42b361ec4680a3fc471`; estaba limpia.
- Se registró una tarea secuencial exclusiva apuntando a este worktree existente.
  La herramienta de creación asigna inicialmente el checkout principal; el
  descriptor se vinculó al worktree de `dev` antes de editar, sin cambiar ramas.
- El origen de los ajustes es el worktree `codex-informe-confiabilidad-emin`.
  Su base contiene cambios posteriores a `dev`; se trasladaron únicamente los
  archivos del informe y sus dependencias de mantenciones, sin integrar toda esa
  historia. `ai.ps1 integrate` aplica tareas paralelas sobre el checkout principal;
  esta aplicación se hizo como trabajo secuencial autorizado directamente en `dev`.
- Se preservaron el checkout principal `test_violento`, los cambios del worktree
  de origen y los archivos de Alertas. No se modificaron datos de producción.
- Commits: ninguno. Cambios locales sin publicar.

## Cambios aplicados

Vistas canónicas de confiabilidad y horas, filtros por catálogo de Tribología,
presentación ejecutiva EMIN, eliminación de avisos técnicos en EMIN, Pareto de
acciones únicas por unidad apilado por sistema, Pareto independiente de horas,
prefijo 80% + tres unidades, expansión independiente y restablecimiento de unidad.

La auditoría real produjo tres correcciones adicionales:

1. CDA fallaba al cargar la vista de componentes con zonas horarias mixtas.
   Su lectura ahora usa UTC, manteniendo el contrato de reloj local de EMIN.
2. La leyenda de siete sistemas comprimía el área de dibujo y los rótulos se
   solapaban. Se reservó altura de 520 px y se redujeron los rótulos de ejes,
   conservando las barras, los colores y el cálculo acumulado.
3. «Mostrar todos» se reiniciaba cuando el render limpiaba la selección de la
   tabla. El callback EMIN evita reemitir una unidad que no cambió.

También se ajustó el espacio y tamaño de texto de las tarjetas a 390 px.

## Datos y conciliación

Fuentes reales locales: `CDA/Dashboard/tds_alerts_dashboard/data`, leídas mediante
`DASHBOARD_DATA_ROOT`. Los diez Parquet de EMIN están fechados el 2026-09-29;
contienen mayo–agosto de 2026. Esta auditoría no implica actualización de fuentes.

Se comprobaron 149 condiciones: cuatro meses EMIN, catorce meses CDA y doce
meses Capstone; acciones únicas por unidad frente a query 3, horas por unidad
frente a query 8, denominador completo, corte 80% + 3, curvas sin marcadores,
expansión a 100%, sistemas aislados/vacíos, filtros de flota/unidad y contrato
anterior de otros clientes. Todas pasaron. Los hashes de 26 archivos de
mantenciones y catálogo de aceite permanecieron iguales antes/después.

| Mes EMIN | Acciones únicas | Horas-equipo sin redondear | Unidades acciones inicial/todas | Unidades horas inicial/todas |
| --- | ---: | ---: | ---: | ---: |
| 2026-05 | 6 | 7,543056 | 6 / 6 | 6 / 6 |
| 2026-06 | 189 | 663,691111 | 73 / 107 | 27 / 113 |
| 2026-07 | 2.956 | 9.816,952500 | 224 / 529 | 110 / 534 |
| 2026-08 | 455 | 1.362,775833 | 119 / 207 | 39 / 211 |

Agosto: las cards muestran 98,4% de disponibilidad, 1.362,8 h de downtime,
275,6 h de MTBF y 2,4 h de MTTR. La curva compacta termina en 80,659% de
acciones y 81,282% de horas; solo la expansión completa termina en 100%.
Las unidades con horas pueden diferir de las que tienen acciones ese mes.

El primer intento de conciliación aplicó incorrectamente `source_system=EMIN`
al extracto de acciones alojado en la carpeta EMIN. Ese campo no identifica
todo su universo; se corrigió el auditor para usar el extracto completo de ese
cliente. No se cambiaron las acciones para hacer coincidir el resultado.

## Auditoría del navegador

Se montaron el shell, CSS, layout y callbacks reales del informe de `dev` en
`127.0.0.1:8067`, con los repositorios reales en modo Parquet. La autenticación
quedó aislada en el arnés local: no se importaron usuarios ni credenciales.
No se arrancaron servicios externos ni otros módulos del dashboard.

- EMIN agosto: expansión de acciones 119 → 207 y horas 39 → 211; cards iguales.
- Julio, flota `bulldozer`, BULL-023: detalle y ranking de componentes reales;
  «Restablecer unidad» devuelve Todas y conserva julio y bulldozer.
- 390×844: sin desbordamiento horizontal; títulos y valores de cards legibles.
- 768×1024: sin desbordamiento; sidebar plegado, apertura como panel de 260 px.
- 1440×900: leyenda, barras, curva y umbral legibles; se guardó captura de ambos Paretos.
- CDA enero 2026: carga, cards y Paretos de Motor/Tren de Fuerza visibles.
- Capstone junio 2026: mantiene acciones por equipo/sistema y ausencia de KPIs
  de tiempo cuando no existen sus fuentes. Los botones EMIN están ocultos.

Evidencias locales ignoradas por Git, dentro de `.coddi-local/`:
`emin-real-paretos-desktop.jpg`, `emin-real-390.jpg`, `cda-real.jpg`,
`capstone-real.jpg`, `audit-real-results.json`, `audit-real.log`.
Scripts reproducibles: `audit_real.py` y `real_report_app.py`.

## Archivos cambiados

- `dashboard/assets/custom_layout.css`
- `dashboard/callbacks/mantenciones_general_callbacks.py`
- `dashboard/callbacks/sidebar_callbacks.py`
- `dashboard/tabs/tab_mantenciones_general.py`
- `src/data/loaders.py`
- `src/data/maintenance_repository.py`
- `tests/test_mantenciones_productive.py`
- `documentation/mantentions/PRODUCTIVE_VIEW.md`
- `documentation/mantentions/data_contract_v2.md`
- Este informe.

## Validaciones exactas

Se usó el Python 3.11 del entorno local preparado en el worktree de origen.
El entorno offline no reproduce todos los pins del despliegue.

- `python -m pytest -q tests` — primer perfil: 9 failed, 805 passed, 9 skipped.
- `python -m pytest -q tests` — último perfil tras los arreglos funcionales:
  **9 failed, 840 passed, 9 skipped**, 67 warnings, 64,68 s;
  `.coddi-local/pytest-dev-final.log`.
- `python -m pytest -q tests/test_mantenciones_productive.py --tb=short` —
  66 passed, 5 warnings; también incluidas en el perfil completo final.
- `python .coddi-local/audit_real.py` — exit 0, 149 comprobaciones correctas.
- `git -c core.excludesFile=.gitignore -c core.safecrlf=false diff --check` — exit 0.
- `python -m compileall -q dashboard/callbacks/mantenciones_general_callbacks.py dashboard/callbacks/sidebar_callbacks.py dashboard/tabs/tab_mantenciones_general.py src/data/loaders.py src/data/maintenance_repository.py` — exit 0.

Los nueve fallos globales corresponden a cinco fixtures de Campbell AI fechados
en julio fuera de la ventana relativa de 60 días, tres pruebas que requieren
`data/oil/essays_elements.xlsx` ausente en este worktree y un orden de
conversaciones con timestamps iguales. No se modificaron esas pruebas.

## Riesgos, pendientes y siguiente acción

No se validaron autenticación, otros módulos, zoom 200%, pipelines ni fuentes
remotas. Agosto es un extracto histórico parcial; la nota de estimación se mantiene.
Las cantidades grandes todavía producen barras finas al expandir toda la flota,
pero los datos, los tooltips y el filtro por unidad permanecen disponibles.

Trabajo del informe y auditoría específica terminado; validación global pendiente.
Sin preguntas abiertas sobre los cambios solicitados. Siguiente acción: revisar
el diff local de `dev` y resolver los nueve fallos de Campbell AI en su alcance
antes de una publicación o integración que exija la suite completa verde.
