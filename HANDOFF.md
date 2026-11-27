# Handoff · panorama histórico EMIN

## Objetivo y resultado

Incluir en el panorama de flota el acumulado del puntaje medio semanal de todos los equipos, manteniendo el acumulado individual en el detalle. El cálculo vive en el productor; el dashboard lee `fleet[cutoff].cumulative_weekly_score` y solo construye el gráfico. La tarjeta usa el mismo estilo `unit-card`, encabezado y tema Plotly que el resto de la página, y queda antes de los tops para dar contexto a toda la flota.

El detalle del equipo ahora presenta los hitos mayores en orden histórico hasta el corte seleccionado, aunque sean anteriores al período usado por el top. El paquete conserva su horizonte de 52 semanas y el corte temporal se aplica para no mostrar evidencias posteriores.

## Datos y contrato

- Run real: `20261126T0000-0300-d34c89f02d3415ceca32d8e1aad334e1f6eb51d46826e6e7687db459d1e6b5e6`.
- Contrato: `coddi.emin.historical-dashboard.v3`, aceptado junto con v1 y v2.
- Corte más reciente: `2026-W48`, con datos hasta 25-11-2026; 50 equipos, 53 cortes semanales.
- En la última semana: 43/50 unidades observadas; promedio semanal 4,732558 y acumulado 169,373797. La serie mantiene brechas sin dato y muestra cobertura por semana.
- El espejo local se guarda en `data/fleet_history/golden/emin/2026-W48/`, preservando versiones anteriores. Esta carpeta está fuera de Git.

## Archivos

- `dashboard/components/emin_historical.py`: figura semanal de flota e hitos históricos.
- `dashboard/tabs/tab_emin_historical.py`: tarjeta del acumulado en el panorama.
- `dashboard/callbacks/emin_historical_callbacks.py`: conecta la figura al corte y al paquete seleccionado.
- `src/data/emin_historical.py`: acepta el contrato v3.
- `src/i18n/locales/es.json`, `src/i18n/locales/en.json`: texto de la tarjeta, cobertura y hitos.
- `tests/test_emin_historical.py`: cobertura, recorte ISO y persistencia de hitos anteriores.

## Validaciones

- `docker run --rm --network none --mount "type=bind,source=C:\Users\panch\Desktop\Coddi\.worktrees\tds-alerts-dashboard\codex-emin-historico-flota,target=/app,readonly" --workdir /app --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python tds-alerts-dashboard-emin-test:latest -m pytest -q -p no:cacheprovider tests/test_emin_historical.py`: **11 passed**, 1 advertencia deprecada de pytest/dash.
- Lectura del paquete local y creación real de Plotly: run v3 válido; 53 semanas de datos y 53 puntos de flota; última semana 2026-W48, 43/50 equipos y acumulado 169,373797.
- `git diff --check`: OK.

## Riesgos, decisiones y pendientes

El acumulado suma el promedio semanal de los equipos observados con igual peso por unidad; cambios de cobertura pueden alterar el promedio, por lo que la cobertura queda visible en el hover y en la explicación. Es una medida heurística, no una probabilidad de falla. El paquete disponible cubre aproximadamente 52 semanas. El contenedor local `emin-dashboard-local-iter` monta el código y datos de este worktree, pero la ruta protegida redirige a login sin una sesión autenticada; no se declara una auditoría visual autenticada. El endpoint local debe ser revisado con sesión iniciada.

Commit local de implementación: `22d4f71 feat: show EMIN fleet cumulative score`, rama `ai/codex/emin-historico-flota`. El handoff queda en un commit documental posterior. Push: no solicitado.

Siguiente acción: confirmar el gráfico en el panorama de flota en la sesión autenticada y, si la presentación se ve bien, integrar los commits locales de ambos repos por el flujo habitual.

## Comparación de acumulados por unidad contra la media de flota

### Objetivo y resultado

Se amplió la tarjeta del panorama a una curva por unidad, usando las series acumuladas ya publicadas por el productor, y una línea negra discontinua con el acumulado medio de flota. Los colores de las curvas reutilizan los estados de cambio reciente de Predictivo/EMIN. Las unidades críticas/prioritarias se dibujan con más peso y cinco reciben etiqueta al final de su curva. El hover identifica la unidad y sus puntajes; al hacer clic se abre su detalle histórico. Las brechas semanales siguen sin conectarse.

No se cambió ni recalculó el contrato del productor: el dashboard consume los acumulados individuales y de flota del paquete v3 existente. El promedio de flota permanece como referencia, no se interpreta como umbral de falla.

### Archivos

- `dashboard/components/emin_historical.py`: gráfica con 50 trazas unitarias y la media de flota.
- `dashboard/callbacks/emin_historical_callbacks.py`: navegación de una curva al detalle del equipo.
- `src/i18n/locales/es.json`, `src/i18n/locales/en.json`: leyenda y explicación del comparativo.
- `tests/test_emin_historical.py`: regresión para las líneas unitarias, la media discontinua, los cortes y la navegación.
- Commit local: `f71744e feat: compare EMIN cumulative unit curves`, rama `ai/codex/emin-historico-flota`.

### Validaciones

- Perfil offline exacto: `docker run --rm --network none --mount "type=bind,source=C:\Users\panch\Desktop\Coddi\.worktrees\tds-alerts-dashboard\codex-emin-historico-flota,target=/app,readonly" --workdir /app --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python tds-alerts-dashboard-emin-test:latest -m pytest -q -p no:cacheprovider tests/test_emin_historical.py`: **11 passed**, 1 advertencia deprecada de pytest/dash.
- Paquete real v3 `20261126T0000-0300-d34c89f02d3415ceca32d8e1aad334e1f6eb51d46826e6e7687db459d1e6b5e6`: la figura contiene 50 curvas por unidad, una media de flota y 53 semanas; cinco equipos prioritarios quedan rotulados.
- El contenedor local se reinició; quedó `healthy` y `/overview/emin-historical` devolvió HTTP 200. La ruta requiere login y no se validó visualmente con una sesión autenticada.
- `git diff --check` y parseo de los dos archivos de idioma: OK.

### Riesgos y siguiente acción

Los huecos de cobertura generan tramos discontinuos; la media semanal incluye las unidades observadas esa semana. Por ello los cambios de cobertura pueden modificar la media, y una trayectoria inferior a ella no certifica salud mecánica. El paquete abarca 53 semanas disponibles. Siguiente acción: revisar el comparativo en la ruta local con sesión iniciada y confirmar la lectura de colores/etiquetas.

## Zonas de comparación acumulada y período del panorama

### Resultado

El fondo ahora se divide alrededor de la media acumulada: verde bajo la media y rojo sobre ella. Cada unidad recibe su color según la última posición comparable en el corte elegido; en hover se ven la diferencia respecto a la media y las semanas observadas del equipo y de la flota. Las unidades prioritarias siguen destacadas y cinco quedan rotuladas. La referencia negra discontinua y las curvas individuales conservan todas las semanas y brechas. Se retiró Trimestral de los períodos del panorama y de sus tops; el período trimestral sigue disponible en el detalle individual.

La posición y diferencia ya vienen materializadas por el productor en el contrato v4; el dashboard solo selecciona series y las dibuja. La explicación visual advierte que la cobertura afecta la comparación.

### Paquete, validaciones y archivos

- Run real: `20261126T0000-0300-75bb60dba7c6a547875f0e90a96f4139c491852896ca50852c7995b7ff60e93b`, contrato v4, `synthetic=false`, 50 equipos y 53 semanas. Al último corte: 31 bajo la media y 19 sobre ella; 43/50 unidades observadas en la semana más reciente. El paquete está espejado en `data/fleet_history/golden/emin/2026-W48/` y la carpeta no se versiona.
- Perfil offline: `docker run --rm --network none --mount "type=bind,source=C:\Users\panch\Desktop\Coddi\.worktrees\tds-alerts-dashboard\codex-emin-historico-flota,target=/app,readonly" --workdir /app --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python tds-alerts-dashboard-emin-test:latest -m pytest -q -p no:cacheprovider tests/test_emin_historical.py`: **12 passed**, 1 advertencia deprecada de pytest/dash.
- Figura real desde el paquete v4: 50 curvas, 53 puntos para la media, bandas verdes/rojas, 31 líneas bajo la media y 19 sobre ella; cinco etiquetas prioritarias.
- Contenedor `emin-dashboard-local-iter` reiniciado, saludable; `/overview/emin-historical` devolvió HTTP 200. No hubo inspección autenticada en navegador.
- Archivos: `dashboard/components/emin_historical.py`, `dashboard/tabs/tab_emin_historical.py`, `dashboard/callbacks/emin_historical_callbacks.py`, `src/data/emin_historical.py`, locales ES/EN y `tests/test_emin_historical.py`.
- Commit local de implementación: `6cc6da8 feat: shade EMIN fleet mean comparisons`, rama `ai/codex/emin-historico-flota`.
- Productor del contrato v4: `f3e1029 feat: compare fleet cumulative scores`, rama `ai/codex/emin-periodic-variations`.
- Push no solicitado y no realizado.

### Riesgo y siguiente acción

La media de cada semana promedia las unidades observadas; una cobertura distinta puede cambiar la comparación, así que “bajo la media” no equivale a un diagnóstico saludable. Siguiente acción: revisar las zonas y leyendas desde una sesión autenticada. El contrato v4 tiene retrospectiva de las 53 semanas disponibles.

## Comparación histórica 0..t−1 contra semana de corte t

### Objetivo y resultado

La ficha emergente del gráfico de variación muestra la base histórica con su rango ISO, la semana de corte `t`, los dos puntajes, la variación, la cobertura de jornadas y los hitos mayores de `t`. El fondo y el texto de la ficha tienen contraste explícito, al estilo del popup de variación por unidad. En Histórico, los ejes nombran el promedio de semanas 0 a `t−1` y el puntaje promedio de semana de corte `t`. La serie acumulada también usa una ficha blanca de alto contraste con total, media, diferencia y cobertura.

El dashboard acepta v5, pero solo consume las comparaciones calculadas por el productor. El paquete real se regeneró y publicó en S3; la copia local de `data/fleet_history/golden/emin/2026-W48/` apunta al run `20261126T0000-0300-b13bd11bf3963b110979f6e5514d6366bb8fdb72183bf9221e5a8578e785db8f`.

### Archivos y validaciones

- `dashboard/components/emin_historical.py`: contenido/estilo de las fichas emergentes y nombres de ejes para Histórico.
- `src/data/emin_historical.py`: lectura compatible con contratos v1–v5.
- `src/i18n/locales/es.json`, `src/i18n/locales/en.json`: etiquetas del popup y descripción de la comparación.
- `python -m py_compile dashboard/components/emin_historical.py src/data/emin_historical.py` y parseo JSON ES/EN: OK.
- El cargador local leyó run v5 real, 18.200 filas, 53 semanas y corte `2026-11-25`. La comparación histórica tuvo 9 mejoradas, 19 estables, 15 empeoradas y 7 sin cobertura comparable.
- Inspección visual autenticada del navegador local: en la pestaña Histórico se vieron los ejes “Puntaje medio · semanas 0 a t−1” y “Puntaje medio · semana de corte t”, los 43/50 equipos comparables y la gráfica de acumulado. No se activó el hover con el controlador visual disponible; debe revisarse manualmente la ficha ya configurada.
- El log local de sincronización del dashboard reportó `BUCKET_NAME not found in .env file`; la vista cargó el paquete v5 desde el espejo local, y la publicación real del productor sí terminó con código 0.
- No se ejecutó la suite de pruebas en esta iteración. Cambios locales sin commit; sin push.

### Riesgos, decisiones y siguiente acción

La línea base pondera cada semana observada por igual y no rellena semanas ausentes. El popup muestra cobertura para contextualizar el promedio. Siguiente acción: pasar el cursor sobre una unidad en el navegador local y ajustar el largo del texto si la tarjeta rebasa el gráfico; después, ejecutar el perfil offline antes de cerrar con commit.

## Leyenda explícita del periodo evaluado

### Objetivo y resultado

Se añadió debajo de la gráfica de variación por condición, inmediatamente sobre la leyenda de estados, una leyenda que explicita los periodos comparados. En la vista semanal muestra los buckets exactos, por ejemplo `2026-W47 → 2026-W48`; en Histórico indica la base promedio desde la primera semana observada hasta `t−1` y la semana de corte `t`. Los modos mensual y trimestral reutilizan los buckets materializados por el productor. El popup de cada punto conserva además los periodos y coberturas de esa unidad.

### Archivos y validaciones

- `dashboard/components/emin_historical.py`: genera la leyenda de comparación a partir de `previous_bucket` / `current_bucket` (o el catálogo de corte histórico cuando aplica) y la coloca visible sobre la leyenda de estados.
- `src/i18n/locales/es.json`, `src/i18n/locales/en.json`: etiquetas localizadas para comparaciones periódicas e históricas.
- `python -m py_compile dashboard/components/emin_historical.py src/data/emin_historical.py`: OK.
- Parseo JSON de `src/i18n/locales/es.json` y `src/i18n/locales/en.json`: OK.
- `git diff --check`: OK.
- Inspección visual del dashboard local en `http://127.0.0.1:8050/overview/emin-historical`: la etiqueta se ve encima de la leyenda de estados y mostró `Comparación evaluada: 2026-W47 → 2026-W48` en Semanal.
- No se ejecutó la suite de pruebas. Cambios sin commit; sin push.

### Riesgos y siguiente acción

La etiqueta depende de que el paquete del productor traiga los buckets de comparación; para contratos históricos se usa el catálogo ISO como respaldo de la semana de corte. Revisar manualmente también los modos Mensual e Histórico con sus selectores para confirmar el texto correspondiente.

## Reajuste del panorama para lectura priorizada

### Objetivo y resumen

Se reorganizó la vista «Panorama de flota» para responder en este orden: qué equipos concentran mayor criticidad en el periodo elegido (Top 5), cómo evoluciona la condición de todas las unidades (gráfica de variación) y, después, cuál es su puntaje acumulado frente a la media. La selección semanal, mensual o histórica quedó en un bloque de periodo compartido por el Top 5 y la evolución. La tabla y agrupaciones permanecen más abajo como consulta complementaria.

### Archivos cambiados en esta iteración

- `dashboard/tabs/tab_emin_historical.py`: reorden de las secciones; periodo primero, criticidad Top 5 segundo, evolución de flota tercero y acumulado después.
- `dashboard/components/emin_historical.py`: en pantallas amplias distribuye el Top 5 en una fila y oculta hito/cobertura redundantes cuando no aportan dato.\n- `src/i18n/locales/es.json`, `src/i18n/locales/en.json`: títulos y ayudas del nuevo flujo y aclaración de que el Top 5 y la evolución comparten el periodo.
- `HANDOFF.md`: registro del objetivo, decisión y validaciones.

### Validaciones y estado

- `python -m py_compile dashboard/tabs/tab_emin_historical.py dashboard/components/emin_historical.py`: OK.
- Parseo JSON de los locales ES/EN: OK.
- `git diff --check`: OK.
- No se ejecutó la suite de pruebas. La inspección visual en navegador local, con el corte semanal y paquete de datos disponible, confirmó Top 5 → gráfica de toda la flota → puntaje acumulado; las cinco tarjetas quedaron en una fila amplia.
- Cambios locales sin commit ni push. Se conservan las modificaciones previas en `dashboard/components/emin_historical.py`, `src/data/emin_historical.py` y locales.

### Decisión, riesgo y siguiente acción

La página sigue mostrando la evolución para toda la flota, no solo para el Top 5; el Top 5 funciona como entrada rápida a los equipos prioritarios. La jerarquía y la carga visual se comprobaron en Semanal. Mensual e Histórico conservan los mismos controles y orden, pero no se recorrieron en esta pasada.

## Comparaciones y top sujetos al periodo de análisis

### Objetivo y resultado

Se alinearon Semana ISO y Periodo de análisis en una misma fila de filtros. El Top 5 obtiene sus equipos del ranking precomputado del periodo seleccionado y usa para su estado la variación del mismo periodo, sin reutilizar el movimiento diario. La gráfica de toda la flota sigue ese mismo selector. Los periodos son: Semanal (semana ISO seleccionada vs la anterior), Mensual (mes calendario seleccionado vs el anterior) e Histórico (semana ISO de corte vs promedio histórico de las semanas anteriores). En Histórico se conserva la base histórica calculada por el productor. Cada comparación expone sus buckets reales en la leyenda y en la ficha emergente.

El Top queda en una fila compacta en pantallas amplias: puntaje medio observado en Puntos de Riesgo, redondeado a una décima; componente principal; estado del periodo; cobertura solo cuando está incompleta. Se quitó la señal contada por jornadas observadas.

### Datos y validaciones

- Paquete local v5 leído desde Docker: run `20261126T0000-0300-b13bd11bf3963b110979f6e5514d6366bb8fdb72183bf9221e5a8578e785db8f`, corte más reciente `2026-11-25` / `2026-W48`.
- Verificación del contrato en el corte más reciente: Semanal `2026-W47 → 2026-W48`; Mensual `2026-10 → 2026-11`; Histórico `2025-W52–2026-W46 → 2026-W48`. Cada selector trae ranking Top y comparaciones para 50 unidades.
- `python -m py_compile dashboard/tabs/tab_emin_historical.py dashboard/components/emin_historical.py src/data/emin_historical.py`: OK.
- Parseo JSON ES/EN: OK.
- `git diff --check`: OK.
- `Invoke-WebRequest -Uri http://127.0.0.1:8050/overview/emin-historical -UseBasicParsing -TimeoutSec 10`: HTTP 200.
- La lectura de accesibilidad del navegador observó Semana ISO y Periodo de análisis en la fila superior. El usuario detuvo el control del navegador con Escape mientras la vista se recargaba; los callbacks aún no habían poblado el contenido. No se confirma una auditoría visual completa ni se afirma que la interacción haya sido verificada en pantalla.
- No se ejecutó la suite de pruebas. Cambios locales sin commit ni push.

### Decisión, riesgo y siguiente acción

Las comparaciones y el ranking se consumen del contrato v5; el dashboard no recalcula promedios. Los puntajes son heurísticos y dependen de cobertura. Siguiente acción: reabrir la pestaña local y revisar las tarjetas y cambios de estado al alternar Semanal, Mensual e Histórico; después cerrar el trabajo local.

## Rediseño del informe histórico EMIN Beta

### Objetivo y entrega

La portada usa el último corte disponible y explica la condición frente a todo el historial de la unidad. En escritorio conserva el dispersograma al estilo de Predictivo, con una etiqueta permanente por equipo. En móvil muestra las dos observaciones por unidad en filas comparables. La tabla única al pie contiene la flota, aportes, coberturas y extremos del ranking histórico. Se puede filtrar por grupo y volver al mismo filtro desde el detalle.

El detalle abre con hechos y referencias de origen. Incluye hitos históricos por semana, muestras de aceite por condición y compartimento, y una tabla de registros con un acceso a las muestras en rojo. Se conservan los resúmenes mensuales como tales. La metodología completa se abre desde el panorama. La vista muestra un aviso de sincronización si lee una publicación previa a la Beta.

### Archivos y validación

- `dashboard/components/emin_beta.py`, `dashboard/tabs/tab_emin_historical.py`, `dashboard/callbacks/emin_historical_callbacks.py`, `dashboard/assets/emin_beta.css`, `dashboard/assets/emin_history.js`, `src/data/emin_historical.py`, locales y pruebas EMIN.
- `docker run --rm --network none --mount "type=bind,source=C:\Users\panch\Desktop\Coddi\.worktrees\tds-alerts-dashboard\codex-emin-historico-flota,target=/app,readonly" --workdir /app --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python tds-alerts-dashboard-emin-test:latest -m pytest -q -p no:cacheprovider tests/test_emin_historical.py`: 15 aprobadas, una advertencia de deprecación de pytest/Dash. Compilación Python, parseo ES/EN y `git diff --check`: OK.
- La copia local usa el run S3 `20261126T0000-0300-c9112738878429bd6c507aa1659988d6afc67f731a94f35e36d4d4a4d2d04223`, verificado para los cuatro archivos y el puntero. El corte `2026-W48` contiene datos hasta el 25-11-2026 y registros desde el 11-11-2014. Hay 50 unidades, con 16 que empeoraron, 17 que se mantuvieron, 11 que mejoraron y 6 sin comparación.
- Playwright con Edge en servidor local de auditoría y datos reales. A 1.440 px se observaron 44 nombres separados al menos 16 px y 50 filas. A 390 px se observaron los 44 rótulos, sin desbordamiento de página, con desplazamiento dentro de la tabla. Se recorrió Frenos → CT-187 → muestras en rojo → panorama y se conservó Frenos. Se verificó también el puesto 1 de CT-226 y la ausencia de dato en la semana de corte de CT-190 en la publicación final. La prueba offline cubre el detalle de una unidad sin muestras, ausente del paquete real.
- En la publicación final, CT-230 figuró como empeorado (+10,2 puntos) y el acceso a muestras en rojo de CT-187 devolvió seis registros, todos con condición Anormal y referencia al Golden de aceite.
- El dashboard habitual en `http://127.0.0.1:8050/overview/emin-historical` respondió HTTP 200 tras el reinicio. La auditoría automatizada se hizo en un servidor separado de vista local, con los callbacks y el espejo reales y un usuario de prueba restringido a EMIN.

### Riesgo y estado

La existencia de registros desde 2014 expresa el alcance del paquete. Cada unidad y fuente conserva su propia cobertura. La vista se ejecuta localmente. Cambios de código sin commit y sin publicación de Git.

## Scatterplot en escritorio y móvil

El panorama usa una sola figura de dispersión en todos los tamaños. Los ejes comparan el promedio histórico anterior con la semana de corte. Las tres zonas de color y las etiquetas con línea guía se mantienen. En móvil, se ajustaron los márgenes para ampliar el área útil sin provocar desplazamiento horizontal.

Se modificaron el componente `emin_beta.py`, su CSS y los locales ES/EN. El cambio está cargado en el dashboard local y queda sin commit.

- `docker run --rm --network none --mount "type=bind,source=C:\Users\panch\Desktop\Coddi\.worktrees\tds-alerts-dashboard\codex-emin-historico-flota,target=/app,readonly" --workdir /app --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python tds-alerts-dashboard-emin-test:latest -m pytest -q -p no:cacheprovider tests/test_emin_historical.py`: 15 aprobadas y una advertencia de deprecación preexistente.
- Playwright con Edge y el paquete real sincronizado comprobó un solo scatterplot, 44 puntos, 44 etiquetas y ningún rótulo recortado horizontalmente a 320, 390 y 1.440 px. La ruta local devolvió HTTP 200 después del reinicio.
- `git diff --check`: OK.

## Scatterplot con cuatro zonas y detalle desde 2024

### Objetivo y entrega

El panorama compara semana ISO de corte en X con base histórica en Y. Los cuatro cuadrantes usan el umbral relativo publicado en el paquete. Los nombres se dibujan dentro del área del gráfico junto a sus puntos y se recolocan al cambiar el tamaño. La tabla al pie conserva sus puestos y filtro por grupo.

El detalle muestra abiertos el gráfico y la tabla de hitos, y el gráfico y la tabla de tribología. Ambas tablas dedicadas están paginadas. Tribología permite mostrar solo las muestras Anormales. Los hitos conservan evidencia, procedencia y granularidad mensual. La metodología visible explica el inicio de 2024, el puntaje y la diferencia entre el cuadrante y la variación de la tabla.

### Validación y estado

- Paquete corregido en S3 y en el espejo local. Run `20261126T0000-0300-4354f2d48ed807acadaea49eaa919ffc8f5622609cb6ca7f706cfc16fe254b70`, corte parcial del 25-11-2026, horizonte desde el 01-01-2024. El umbral fue de 4,5 puntos. Saludables 26, mejoraron recientemente 0, críticos sostenidos 11, empeoraron recientemente 7 y sin comparación 6.
- `docker run --rm --network none --mount "type=bind,source=C:\Users\panch\Desktop\Coddi\.worktrees\tds-alerts-dashboard\codex-emin-historico-flota,target=/app,readonly" --workdir /app --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python tds-alerts-dashboard-emin-test:latest -m pytest -q -p no:cacheprovider tests/test_emin_historical.py`: 16 pruebas aprobadas. `node --check dashboard/assets/emin_scatter_labels.js` y `git diff --check`: OK.
- Playwright Edge local con datos reales. A 320, 390 y 1.440 px se vieron los cuatro cuadrantes y 44 nombres dentro del gráfico, sin etiquetas superpuestas ni desplazamiento horizontal. Se recorrió Seguridad / Frenos → CT-187 → hitos y tribología → volver. Se vieron los dos gráficos, se avanzó de los registros 1–30 a 31–60 de 563 hitos, y el filtro de aceite dejó seis muestras Anormales. El filtro de flota se conservó.
- Archivos de la vista Beta, callbacks, activos CSS/JS, lector del paquete, locales y pruebas. La interfaz corre en el dashboard local. Cambios sin commit. La integración permanente del productor y la interfaz Beta queda como siguiente acción de despliegue.

## Portada centrada en registros de la operación

El panorama prioriza tres registros verificables de la semana de corte entre equipos críticos o que empeoraron. Las muestras de aceite anormales y los eventos de severidad alta o crítica se muestran primero. Cada acceso lleva al mismo registro en Historial por equipo. La tabla de flota antepone la evidencia de la semana a los puntos. El detalle da acceso directo a las tablas de fallas, cambios, detenciones y muestras de aceite. La búsqueda de todos los registros queda plegada. Se conservan los cuatro cuadrantes, el horizonte desde enero de 2024 y el contrato de datos.

Cambios en `dashboard/components/emin_beta.py`, callbacks, pestaña, CSS, JS, locales ES/EN y pruebas. Estado local sin commit.

- `docker run --rm --network none --mount "type=bind,source=C:\Users\panch\Desktop\Coddi\.worktrees\tds-alerts-dashboard\codex-emin-historico-flota,target=/app,readonly" --workdir /app --env PYTHONDONTWRITEBYTECODE=1 --entrypoint python tds-alerts-dashboard-emin-test:latest -m pytest -q -p no:cacheprovider tests/test_emin_historical.py` dio 17 aprobadas y una advertencia de deprecación preexistente. `node --check dashboard/assets/emin_history.js` y `git diff --check` aprobaron.
- Playwright Edge sobre la vista de auditoría con el paquete real W48 citado arriba. A 320, 390 y 1440 px se vieron 44 nombres sin desplazamiento horizontal de la página. CT-230, CT-218 y CT-215 encabezaron la revisión. El acceso de CT-230 abrió el evento de antivuelco del 25-11-2026 con severidad alta y fuente EMIN. Frenos → CT-187 → aceite anormal devolvió seis muestras y se conservó el filtro al volver.
- La ruta local habitual devolvió HTTP 200 tras reiniciar. El corte es parcial y seis unidades carecen de una comparación suficiente. La integración en un entorno compartido sigue pendiente.

## Segunda revisión de la lectura del panorama

El resumen enumera primero los críticos sostenidos y los que empeoraron recientemente. Los números coinciden con las zonas del scatterplot. El texto explicita las fechas de cada eje y el tooltip muestra el hecho operativo y la fecha del registro.

Con la publicación real W48, Playwright Edge comprobó la semana del 23 al 25-11-2026 frente al historial del 01-01-2024 al 22-11-2026, el evento de antivuelco en el tooltip de CT-230, 44 nombres a 320 y 1440 px sin desbordamiento horizontal, 50 filas en la tabla y la apertura de la metodología. El mismo comando offline anterior dio 17 pruebas aprobadas. La ruta local devolvió HTTP 200 después de reiniciar. Cambios locales sin commit.

## Cierre de la experiencia EMIN Beta

La navegación identifica Beta. La tabla informa cuántos equipos coinciden y marca los extremos de cinco filas con su puesto publicado. El historial destaca solamente el registro abierto desde la flota y mantiene las tablas de hitos y aceite, con sus gráficos.

El perfil offline descrito arriba pasó 17 pruebas, incluidos el filtro vacío, el puesto conservado, la unidad sin muestras y el enlace exacto. Playwright Edge confirmó 50 filas, 5 marcas por extremo, 44 nombres a 320, 390 y 1440 px, el registro de antivuelco de CT-230 y las seis muestras anormales de CT-187 con filtro conservado al volver. El paquete local 20261126T0000-0300-b081d2dcdb6b4f4600a142eac60efc6f38b53cf9e103c36d77f6385a7fc30a00 agrega el ejemplo de puestos empatados, con los demás contenidos del modelo idénticos al corte W48 de S3. Integrar las ramas y publicar la documentación actualizada en el entorno compartido sigue pendiente.

## Cobertura y hallazgo semanal

La vista muestra cobertura verificada o preliminar y el nivel relativo por separado de la variación de la tabla. El productor elige el hallazgo semanal y su referencia. El lector admite el contrato previo y valida el nuevo bloque opcional. El espejo local usa el run c6187ae8 del corte real W48. Se mantiene el ranking vigente. Queda pendiente revisar la disponibilidad y cobertura en origen antes de integrar una escala distinta.

- Perfil offline descrito arriba en el dashboard y `git diff --check`.
- En W48 se verificó CT-197 con nivel relativo bajo y subida de señal y CT-230 con el registro de antivuelco del 25-11-2026. Cambios locales sin commit ni publicación remota.

Validación final: el perfil offline dio 17 pruebas aprobadas. Playwright Edge confirmó en la tabla la comparación preliminar, señal relativa baja y empeoramiento de CT-197. El enlace de CT-230 mostró el registro exacto. La ruta habitual respondió HTTP 200.

## Cruce con feedback del panorama y detalle

El scatter destaca la fila de la unidad sin cambiar el filtro. El ranking histórico tiene su propio encabezado. El paquete indica si cada grupo tuvo señales en el corte o solo antes, vincula el registro semanal del grupo y muestra recurrencia y una intervención intermedia únicamente cuando coincide el componente publicado. Los dos gráficos de detalle filtran su tabla por semana ISO y permiten restaurarla.

Perfil offline anterior 17 pruebas aprobadas, node --check dashboard/assets/emin_scatter_labels.js y git diff --check correctos. Playwright Edge sobre W48 comprobó scatter a CT-187, Frenos con 13 coincidencias actuales y 19 históricas, aceite W20, hitos W43 (1 fila, luego 30 al limpiar) y conservación de Frenos al volver. Paquete espejo f0951bc8. Estado local sin commit ni publicación. La adopción de la escala experimental sigue a la espera de cobertura certificada y revisión operativa.

## Cobertura visible y semanas con hallazgos graves

El panorama muestra la cobertura del conjunto. La tabla de ranking agrega semanas con hallazgos graves registrados, su última semana y el desglose por tipo al pasar el cursor. Conserva la lectura de paquetes anteriores. El espejo determinista de W48 usa el run 9e834905 sin alterar la posición o el puntaje vigente de ninguna unidad. Perfil Docker offline anterior: 17 pruebas aprobadas. Cambios locales sin publicación.

## Hallazgos semanales por gravedad y fecha

Flota presenta tres tarjetas y acceso a las restantes, ordenadas como publica el productor. Se muestra la severidad junto al evento y se preserva el enlace al registro aun para equipos fuera del top histórico. La vista local usa el paquete real W48 77e8112a. Playwright confirmó tres tarjetas iniciales, siete adicionales, ancho móvil sin desbordamiento y enlace del puesto 32 (CT-197) al antivuelco del 24-11-2026. Perfil offline anterior: 17 pruebas aprobadas. Cambios locales sin publicar.

## Explicación del puntaje histórico en el detalle

Sección plegable de aportes por dominio con evidencia fechada cuando el productor puede vincularla a una contribución aplicada. No vuelve a calcular puntos. El espejo local usa el corte real W48, run 7e3b200a. Playwright comprobó en CT-230 Rodado 3,6, Seguridad 3,2, Tribología 0,2 y Motor 0,1 con ejemplos de evento y aceite, sin desplazar el hallazgo semanal de antivuelco. Sin desbordamiento a 390 px. El perfil offline dio 17 pruebas aprobadas. Cambios locales.

## Filtro semanal accesible en el detalle

Hitos y aceite permiten filtrar por semana desde un selector nativo junto a la tabla. El selector y el gráfico comparten la selección. Se puede volver a todas las semanas con teclado y cambiar de equipo sin arrastrar otra selección. Se conserva el filtro de muestras anormales. Perfil offline anterior: 17 pruebas aprobadas. Playwright Edge y el paquete real W48 verificaron en CT-187 la selección por flecha de 2026-W44, el retorno a todas con Inicio y el clic en el gráfico que sincronizó 2025-W20 y mostró tres muestras. El selector de hitos mostró 84 opciones, incluida Todas. Cambios locales. Fórmula y paquete de datos conservados.

## Auditoría de cierre del feedback

Sobre el paquete real 7e3b200a, Playwright confirmó 50 unidades, 5 marcas de cada extremo, cuatro cuadrantes y 44 nombres a 320, 390 y 1440 px sin desplazamiento horizontal. Se abrió la metodología, se aplicó Frenos (13 señales en W48 y 19 históricas), se abrió CT-187 con seis muestras anormales y selector semanal disponible, se verificó la ausencia de acumulado y se volvió conservando el filtro. Perfil Docker offline anterior: 17 pruebas aprobadas. node --check dashboard/assets/emin_history.js, node --check dashboard/assets/emin_scatter_labels.js y git diff --check aprobaron. Cierre técnico local; publicación pendiente.
