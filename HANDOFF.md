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
