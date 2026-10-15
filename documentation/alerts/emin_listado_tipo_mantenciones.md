# EMIN: identificación de fuentes y visibilidad de mantenciones

## Objetivo y cambios

El listado ocultaba Fuente y usaba un borde morado en cada celda para indicar
Multitécnica. Ahora muestra Fuente junto a Unidad, con el nombre y color del
catálogo compartido. Las filas Multitécnica tienen un fondo tenue y un único
borde al comienzo de la fila. La tipografía sigue la de la interfaz.

El tipo sigue siendo el publicado en `Trigger_type`: la disponibilidad de
mantenciones, sensores o muestras no promueve ni degrada una alerta. No se
añaden filtros de evidencia.

Al seleccionar una fila, las actividades de mantención quedan desplegadas
inicialmente bajo su resumen semanal. Se mantienen el sistema, la unidad y la
ventana de cuatro semanas ISO completas anteriores. El resumen semanal de la
unidad conserva su identificación como contexto de todos los sistemas.

## Comprobación de la POC el 14/10/2026

URL revisada mediante la interfaz autenticada:
https://poc.tds.coddi.ai/alerts-dashboard/monitoring/alerts

La evidencia de mantenciones ya aparece en Vista Detallada en estos casos:

- `F-48622bc26990c309-1786093136`, CT-178, 07/08/2026 04:58, EBS:
  Fuente Multitécnica y evidencia Telemetría + Mantenimiento. Ventana
  `[2026-07-06, 2026-08-03)`. Muestra semana 29-2026, resumen semanal de la
  unidad y actividad del 15/07/2026 en Sistema de Frenado - Control:
  intervención correctiva del ABS, con operación específica no informada.
- `F-c166471923b2a4a5-1747641987`, BULL-031, 19/05/2025 04:06:
  Fuente Multitécnica y evidencia Telemetría + Mantenimiento. Ventana
  `[2025-04-21, 2025-05-19)`. Muestra semana ISO 20-2025, resumen y actividades
  del 18/05/2025 en Sistema de Motor - Sistema de Enfriamiento.

No se comprobó la totalidad de alertas ni el contenido del servidor por acceso
directo. El listado corregido y el despliegue inicial de actividades se revisan
localmente; su publicación y comprobación en la POC quedan pendientes.

## Validación

- Antes de editar: `python -m pytest -q tests`: 1067 passed, 10 skipped.
- Pruebas dirigidas: `python -m pytest -q tests/test_w34_alerts_table.py tests/test_w34_alerts_source.py tests/test_emin_poc_evidence.py`:
  55 passed. La primera ejecución tuvo 5 errores de acceso al directorio
  temporal de Windows; con TEMP/TMP dentro de `.coddi-local/t` pasó completa.
- Suite completa final: `python -m pytest -q tests`: 1068 passed, 10 skipped,
  73 warnings, en 38,74 segundos (TEMP/TMP en `.coddi-local/t`).
  Los avisos incluyen la deprecación de DataTable y pruebas existentes que
  retornan valores; no se redujo el perfil de validación.
- Revisión visual local del listado y selección de una fila, usando metadatos
  reconstruidos de BULL-031 y mantenciones del CSV local `19-2025.csv`.
  Se verifica la etiqueta explícita, contraste con Telemetría, borde único,
  resumen semanal y actividades desplegadas. La captura local se identifica
  como revisión, sin presentarla como producción.

## Límites y siguiente acción

No se modifica el ETL, los datos de entrada, el contrato de tribología ni la
resolución de mantenciones. No se ejecutan AWS, S3, bases reales ni pipelines.
Después de publicar el cambio, comprobar el listado y la selección de CT-178
en la misma URL. Las capturas de auditoría y registros de ejecución permanecen
locales, fuera del commit.

## Mejora posterior: filtro de Multitécnica para EMIN

En Vista Detallada, el control que decía «Con Tribología» cambia para EMIN a
«Con Multitécnica», con opciones «Sí» y «No». Sí selecciona `Trigger_type ==
"Mixto"`; No selecciona los demás tipos. La existencia de una muestra de aceite
o una mantención no cambia este resultado. Al limpiar el control se recuperan
todas las alertas que cumplan los otros filtros. CDA y Capstone conservan el
filtro de presencia de tribología.

La etiqueta y las opciones se actualizan al cambiar de cliente. Se conserva el
identificador interno del control para no romper sus conexiones existentes.
Se incorpora la traducción correspondiente al inglés.

Validación de esta mejora:

- Perfil offline antes de editar: `python -m pytest -q tests`: 1068 passed,
  10 skipped, 73 warnings.
- Pruebas dirigidas: `python -m pytest -q tests/test_w34_alerts_filters.py tests/test_w34_callback_registration.py tests/test_i18n.py`:
  58 passed, 6 warnings.
- Perfil offline final: `python -m pytest -q tests`: 1076 passed, 10 skipped,
  73 warnings, 53,95 segundos. TEMP/TMP dentro de `.coddi-local/t`.
- Interfaz local con datos de ejemplo: Sí devuelve solo la alerta Mixto;
  No devuelve Telemetria y Tribologia; limpiar restaura las tres opciones.
  Se comprobó visualmente el texto del filtro y sus dos opciones. Captura local:
  `.coddi-local/filtro-multitecnica-local.jpg`.

La mejora queda validada localmente y pendiente de publicación junto con el
ajuste del listado anterior. No se ha modificado la POC en esta revisión.
