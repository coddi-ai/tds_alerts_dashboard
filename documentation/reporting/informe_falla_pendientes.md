# Informe preliminar de falla: estado y pendientes

Actualizado: 2026-10-16.

**Vista:** Reportes > Informe preliminar de falla (`/reporting/informe-falla`).

**Código:**
- `src/informe_falla/`;
- `dashboard/pages/reporting_informe_falla.py`;
- `dashboard/callbacks/informe_falla_callbacks.py`;
- `dashboard/informe_falla_files.py`.

**Documentación relacionada:**
- [informe_preliminar_contexto_y_detenciones.md](informe_preliminar_contexto_y_detenciones.md): qué es el informe y
  cómo se construye.
- [plan_detenciones_previas_informe.md](plan_detenciones_previas_informe.md): integración de las mantenciones.

## Qué es

Cuando una máquina tiene una detención, el informe reúne la información clave y los antecedentes de la máquina,
el sistema o el componente, y procesa lo que ya está en el dashboard para dar una primera lectura del evento:
- qué mostraban los datos antes de la detención;
- la falla más probable y qué la respalda o la contradice;
- qué revisar primero en la inspección;
- qué no se puede afirmar con los datos.

**No es un análisis de causa raíz definitivo:** la causa se confirma en la inspección.

## Estado actual

| Pieza | Estado |
|---|---|
| Predictivo de motor (score semanal y diario, 13 semanas) | Listo. Reglas del método original, sin IA |
| Mantenciones previas del sistema (tabla, línea de tiempo, recurrencia, rellenos) | Listo para motor. CDA, con clasificación por texto |
| Formulario (relato y fotos) | Listo |
| Validador de datos (bloquea si no hay datos suficientes del Predictivo) | Listo |
| Redacción con IA (`gpt-6-luna`, prompt 2.5) y controles | Listo |
| PDF A4 (WeasyPrint) e historial por cliente | Listo. Se guarda en `outputs/informe_falla/` |
| Configuración (`INFORME_FALLA_*`) | `src/informe_falla/config.py` |

## Pendientes, por pasos

Ordenados por prioridad. Cada paso se puede tomar por separado.

### Paso 1: confiabilidad del texto de la IA
1. Forzar en código que la confianza no supere el techo de la auditoría y marcar cuando el veredicto de la IA
   difiere del de las reglas. Hoy solo lo pide el prompt.
2. Reintentar una vez cuando fallan los controles (fuentes inexistentes, términos internos, afirmaciones prohibidas).
3. Validar que toda cifra escrita por la IA exista en la evidencia (como `campbell_ai/summary.sanitize_summary`).
4. Evitar notas de inspección que repiten el paso del catálogo. Hoy se filtran en la plantilla; podrían
   eliminarse desde el prompt.

### Paso 2: reproducibilidad
1. Guardar en el registro de cada informe una huella de la data usada (fecha o hash de las particiones).
2. Probar `INFORME_FALLA_TEMPERATURE=0` y `INFORME_FALLA_SEED`, si el modelo los acepta.
3. Opcional: reutilizar el informe guardado si se pide el mismo caso con la misma data.
4. Confirmar con el equipo del Predictivo si el historial se recalcula en cada corrida. El 2026-10-07 cambiaron
   los valores de septiembre de 2025 y por eso el informe ya no coincide con el ejemplo original.

### Paso 3: mantenciones (fases pendientes del plan)
1. Revisar a mano los informes de CA-47 y CA-88 (fase 1e).
2. Backtest: comparar el modo más probable del informe con el subsistema registrado en la detención. Solo cuentan
   las detenciones que tienen Predictivo (fase 1f).
3. Validar con mantenimiento la equivalencia entre modos y subsistemas (`catalog.SUBSISTEMAS_POR_MODO`, hoy
   "propuesta sin validar") y las palabras clave de componentes.
4. Vista a nivel record con inicio, fin, duración y categoría en el repo de vistas, para clasificar bien CDA.
5. Contrastar las reglas de texto de `mantenciones.py` con las originales de `reproceso_analisis/antecedentes.py`.
6. Pedir que las vistas de Capstone incluyan **CA-65 y CA-80 a CA-93**: hoy esas 15 unidades del Predictivo no
   tienen registros de mantención, incluida CA-88.
7. Decidir si "Componente afectado" se llena desde el registro de la detención (rotulado y sin pasarlo a la IA).

### Paso 4: más fuentes del dashboard
1. **Aceite** (`data/oil/golden/<cliente>/classified.parquet`): última muestra y tendencia antes de la detención
   (Fe, Cu, Pb, Al, Si, Na, K, viscosidad, agua, refrigerante, combustible, hollín). CA-88 tiene 97 muestras de motor.
2. **Telemetría y alertas** del período previo.
3. **Horómetro y horas del componente**: hay horas en la data de aceite (`machineHours`, `componentHours`) y en
   `cleaned_component_hours.parquet`.
4. Otros sistemas además del motor.

### Paso 5: experiencia en la vista
1. Mostrar la "revisión sin IA" (veredicto y modos destacados) antes de gastar la llamada.
2. Elegir la detención desde los eventos de mantención reales de la unidad, en vez de escribir la fecha.
3. Filtrar el selector a unidades con Predictivo de motor.
4. Perfil de CDA con el modelo de equipo y conteo de modos por cliente (CDA tiene 7, no 9).

### Paso 6: operación
1. Guardar los PDF en S3 y listarlos en Reportabilidad.
2. Trabajos en segundo plano en almacenamiento compartido si gunicorn pasa a más de un worker.
3. Test placebo automático: casos al azar, con un tope de casos con señal.
4. Visual: decidir entre Chromium (fiel al HTML, más de 300 MB extra) o seguir afinando el CSS de WeasyPrint.
   Opcional: descarga en HTML.

### Paso 7: plantilla de jefatura
Evaluar qué secciones de "Informe Preliminar de Falla – Motor Camión Minero (Plantilla).docx" se suman con la
data disponible (ver la revisión del 2026-10-16 en la conversación del equipo): cronología, historial del
componente, evidencia y preservación, clasificación y consecuencia, acciones y firmas.

## Casos de prueba

Con Predictivo y mantenciones (Capstone):
- **CA-31 @ 2025-10-12:** cobertura completa, 6 correctivas, recurrencia en Combustible.
- **CA-47 @ 2026-02-16.**
- **CA-88 @ 2025-09-25:** sin registros de mantención; el informe lo declara.

Bloqueados por el validador por falta de Predictivo: CA-30, CA-35, CA-37 y CA-57 en las fechas del plan.

Con señal del Predictivo, según las reglas:
- **Capstone:** CA-50 @ 2025-09-06, CA-57 @ 2025-09-13, CA-32 @ 2025-12-14.
- **CDA:** T_16 @ 2026-01-01, T_17 @ 2025-06-23, T_14 @ 2025-04-20.

## Historia (resumen)

- **Origen:** el método viene de un notebook y unos scripts de un colega (score semanal y diario más IA). Se
  migraron a `src/informe_falla/`. El 2026-10-15 se verificó que, con la misma data, la evidencia, el esquema, los
  controles y el gráfico eran idénticos al original. Los originales ya no están en el repo; el notebook quedó en
  `notebooks/test.ipynb` (sin versionar) y ya no corre tal cual.
- **Cambios respecto del original:**
  - nombre y alcance de "informe preliminar";
  - sin Ishikawa;
  - reglas de vocabulario y control de términos internos;
  - perfil por cliente;
  - validador de datos;
  - mantenciones previas;
  - campos del formulario y anexo de fotos;
  - PDF A4.
- **Nombres:** hasta el 2026-10-16 todo se llamaba "RCA". Ese día se renombraron el código, los archivos, el
  servicio (`reporting-informe-falla`), la ruta y las variables de entorno (`INFORME_FALLA_*`), y los informes
  antiguos pasaron a `IPF_*`.
