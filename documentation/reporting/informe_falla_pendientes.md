# Informe preliminar de falla (ex Reporte RCA): estado, diferencias con el template y pendientes

Estado al 2026-10-15. Vista: Reportes > Informe preliminar de falla (`/reporting/rca`). Código: `src/rca/`,
`dashboard/pages/reporting_rca.py`, `dashboard/callbacks/rca_callbacks.py`, `dashboard/rca_files.py`.

## Origen

El análisis viene de la carpeta `rca/rca/` (no versionada en git y ya borrada; ver "Originales del colega"), escrita por fuera del dashboard:
`agent_v1.py` (score semanal), `agent_v2.py` (+ score diario), `informe_html.py` (informe HTML) y
`test.ipynb`, que los ejecuta en este orden:

1. Carga `unit_status_summary` y `risk_scores` (`cargar_status`, `cargar_risk`).
2. `armar_evidencia(unidad, fecha, status, risk)`: reglas sin IA.
3. `correr_agente(..., llm_fn)`: OpenAI con Structured Outputs (`MODELO = "gpt-6-luna"`, sin temperatura ni semilla) y controles.
4. `informe_html.guardar(res, version=2, cliente="[Cliente]")`: HTML imprimible.

El ejemplo de salida es `RCA_CA-88_2025-09-25.html` (CA-88, detención del 25-sep-2025).

## Paridad verificada contra `test.ipynb` (2026-10-15)

Mismo caso (CA-88, 2025-09-25), misma data local y la misma respuesta de IA inyectada a los dos lados:

| Paso | Resultado |
|---|---|
| Evidencia sin IA (`armar_evidencia`) | Idéntica |
| Esquema de salida de la IA | Idéntico |
| Controles (esquema, fuentes, hipótesis, inspección) | Idénticos |
| Gráfico SVG | Idéntico (solo se agregan atributos de color para WeasyPrint) |
| Datos enviados a la IA | Igual **más** `contexto_cliente` |
| Prompt | Igual **más** 3 cambios (ver abajo) |
| Informe | Igual salvo la limpieza listada abajo |

Desviaciones del pipeline original al 2026-10-15 (la paridad de arriba se midió antes del prompt 2.1):

- **Prompt 2.2** (`agent.PROMPT_VERSION`, ver "Cambios del 2026-10-15" abajo): sin Ishikawa, con
  `contexto_cliente` y con reglas de vocabulario para el cliente.
- **Perfil por cliente:** `EQUIPO`, `CLIENTE` y `FECHA_INICIO_BASE` pasaron a `config.PERFILES_CLIENTE`.
  Capstone mantiene sus valores; CDA usa un perfil genérico ("camión minero", sin corte de base).
- **Modos ausentes:** CDA no publica refrigerante ni turbo; se completan como `sin_datos` (el original fallaba).

No migrado del notebook: la sección 7 (elegir la detención desde la base sqlite de detenciones), la vista
rápida en texto y las celdas del test placebo (la función `evaluar_lote` sí está en `evidence.py`).

## Por qué el PDF no coincide con el template

1. **La data histórica cambió.** Las particiones de `predictive/golden/capstone/motor` se reescribieron el
   2026-10-07 con valores distintos para los mismos días (CA-88: turbo el 16-sep 26,7 → 46,3; refrigerante el
   23-sep 23 → 45,3; estado W37 "normal" → "anormal"). El template se generó con un snapshot anterior. La
   actualización incremental del 2026-10-15 agregó semanas nuevas, pero no tocó 2025. Hay que confirmar con el
   equipo del Predictivo si el pipeline recalcula el historial en cada corrida: afecta la reproducibilidad de
   cualquier informe.
2. **La IA no es determinista**, tampoco en el notebook: no hay temperatura fija ni semilla, y los modelos son distintos.
3. **Presentación:** el template es una página web; el dashboard genera un PDF A4 con WeasyPrint, que no soporta
   `repeat(auto-fit, …)`, así que las grillas usan columnas fijas (`assets/report.css`).

## Limpieza aplicada al informe (2026-10-15)

Se quitó del PDF lo que no aporta al cliente:

- Ishikawa (6M). Desde el prompt 2.1 la IA tampoco lo produce.
- Tarjeta y menciones de "detenciones previas (por integrar)": vuelven a mostrarse solas cuando
  `evidencia["detenciones_previas"]` exista.
- Aviso "Revisar antes de entregar al cliente" y el pie con el veredicto de las reglas y los controles
  (ambos se muestran en la vista del dashboard).
- Botón "Imprimir o guardar PDF".

Agregados respecto del template: los campos del formulario en "Información entregada por el cliente", el
anexo "10. Registro fotográfico" y la paginación A4.

## Cambios del 2026-10-15

- **Configuración en `src/rca/config.py`:** modelo, timeout, temperatura, semilla, carpeta de salida, caché de
  datos, hilos y vida de los trabajos, cada uno con su variable `RCA_*`. Además, los perfiles por cliente.
- **Modelo por defecto `gpt-6-luna`**, el que usaba el colega; solo para el RCA, Campbell AI no cambia.
  Temperatura y semilla quedan vacías (no se envían), como en el notebook.
- **Prompt 2.1 y 2.2:**
  - sin Ishikawa (regla y campo del esquema eliminados);
  - tabla de nombres en español de los modos;
  - fuentes como rutas exactas, sin comodines;
  - sección "Cómo escribir": sin jerga del paquete, fechas en vez de códigos de semana, nombres de modos en minúscula dentro de la frase y nada de nombres
    inventados;
  - los modos sin datos van a limitaciones.
- **El sistema elegido ya no se envía a la IA**, solo se muestra en el PDF.
- **Control nuevo `terminos_internos`:** detecta en los textos para el cliente identificadores de modos, rutas,
  "techo de confianza", "auditoría", códigos de semana, etc., y lo informa en la vista.
- **Registro del informe:** guarda `modelo`, `temperatura`, `semilla` y `prompt`.
- **"Otros modos" del informe:** se enumeran con comas y distinguen los modos sin datos de los sin cambios.

## Nombre, alcance y validador (2026-10-15)

- **Nombre:** "Informe preliminar de falla" en lugar de "Reporte RCA", en todo lo que ve el usuario:
  menú, títulos, PDF y prompt. N.º de informe `IPF-<unidad>-<AAAAMMDD>`; archivos `IPF_*.pdf`.
  Los identificadores internos no cambian: paquete `src/rca`, servicio `reporting-rca`, ruta `/reporting/rca`.
- **Alcance (prompt 2.3):** no es un análisis de causa raíz definitivo; indica la falla más probable, qué la
  respalda y qué confirmar en la inspección. El PDF lo dice bajo el título y al pie; "Causa raíz" pasó a "Causa".
- **Validador de datos** (`service.validar_disponibilidad` / `service.disponibilidad`): usa el criterio del método.
  Con score diario: al menos 7 de los 28 días previos con datos; sin score diario: al menos 2 de 4 semanas
  válidas. Si no alcanza, el informe sería "datos insuficientes".
  - **En la vista:** corre al elegir unidad y fecha. Muestra los días con datos y el rango disponible de la unidad,
    y deshabilita "Generar informe" si no alcanza.
  - **En el servicio:** se repite antes de llamar a la IA (`ERROR_INSUFFICIENT`), así nunca se paga una llamada
    sin datos.

## Plan para igualar el template (pendiente)

1. **Datos:** pedir al colega el snapshot o la fecha de la data que usó; si no existe, aceptar la data vigente.
   Guardar en el JSON de cada informe una huella de la data (mtime o hash de las particiones usadas).
2. **IA reproducible:**
   - ~~modelo `gpt-6-luna`~~ (hecho);
   - ~~no enviar el sistema~~ (hecho);
   - probar `RCA_TEMPERATURE=0` y `RCA_SEED` (si el modelo los acepta);
   - decidir si `contexto_cliente` se queda en el prompt;
   - opcional: reutilizar el informe guardado si se pide el mismo caso con la misma huella de data.
3. **Visual:** elegir entre
   - (a) renderizar con Chromium/Playwright: igual a "Imprimir" del template en el navegador, pero suma más de 300 MB a la imagen;
   - (b) afinar el CSS de WeasyPrint: sección 1 en 5 columnas, evidencia 50/50.

   Opcional: ofrecer también la descarga del HTML.
4. **Prueba de regresión:** test que corra el agente original y el migrado sobre la misma data con una IA falsa
   y compare la evidencia y el HTML, mientras el original siga disponible.

## Mejoras propuestas (pendiente)

**Confiabilidad**
- Forzar en código que la confianza no supere `auditoria.techo_confianza` y marcar cuando el veredicto de la
  IA difiere del de reglas (hoy solo lo pide el prompt).
- Reintentar una vez cuando los controles fallan (p. ej. fuentes inexistentes).
- Validar el texto libre: toda cifra debe existir en la evidencia (como `campbell_ai/summary.sanitize_summary`).
  En una prueba la IA escribió una palabra inventada ("Sygnosys"); el prompt 2.2 lo prohíbe, pero no hay control.
- Mostrar en la vista la "revisión sin IA" (veredicto y modos destacados) antes de gastar la llamada.

**Contenido**
- Detenciones previas desde `mantentions/golden/<cliente>/Maintance_Labeler_Views/query_3_actions_all_equipment.parquet`
  (fecha confiable: `change_date`): llena la línea de tiempo y la sección 4.
- Elegir la detención desde eventos de mantención reales por unidad, en vez de escribir la fecha.
- Filtrar el selector de unidades a las que tienen Predictivo de motor.
- Conteo de modos por cliente (CDA tiene 7, no 9) y modelo de equipo en el perfil de CDA.
- Nuevas fuentes previstas por el colega: aceite (v3) y telemetría (v4), además de alertas.

**Operación**
- Guardar los PDF en S3 y listarlos en Reportabilidad (hoy viven en `outputs/rca/` del contenedor, montado
  como volumen en `docker-compose.yml`).
- Trabajos en segundo plano en almacenamiento compartido si gunicorn pasa a más de un worker.
- Test placebo automático: casos al azar, con un tope de casos con señal.

## Casos de prueba

Reemplazos en Sistema de Motor (`query_3`) evaluados con las reglas sin IA:

- Capstone: CA-50 2025-09-06 (turbo), CA-57 2025-09-13 (turbo), CA-32 2025-12-14 (bomba de inyección),
  CA-44 2026-04-30; contraste sin señal: CA-48 2025-09-23 (bomba de aceite).
- CDA: T_16 2026-01-01 (enfriador de aceite), T_17 2025-06-23, T_14 2025-04-20, T_13 2025-06-13;
  contraste sin señal: T_18 2025-05-22 (bomba de aceite).

## Originales del colega

`test.ipynb` se movió a `notebooks/test.ipynb` (carpeta en `.gitignore`: no se versiona) y se borraron
`rca/` y `RCA_CA-88_2025-09-25.html`. Nada del repo los usaba. Consecuencias:

- El notebook ya no corre tal cual: importa `agent_v2` e `informe_html`, que vivían en `rca/rca/`. Para
  reusarlo hay que apuntarlo a `src/rca` (`evidence.armar_evidencia`, `agent.correr_agente`, `report_html.documento`).
- La prueba de paridad (punto 4 del plan) solo es posible si el colega vuelve a entregar `agent_v2.py`,
  `agent_v1.py` e `informe_html.py`. La paridad del 2026-10-15 quedó registrada arriba.
