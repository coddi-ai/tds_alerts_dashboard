# Informe preliminar de falla: contexto, construcción y sección de detenciones (por construir)

Fecha: 2026-10-16. Pensado para quien diseñe la sección de **detenciones y mantenciones previas** del
informe, en particular un agente que ya analizó la data de mantenciones. Primero explica qué es el informe y
cómo se arma hoy; después, el hueco que queda por llenar y lo que necesitamos de ese análisis.

Estado del resto del informe y sus pendientes: [informe_falla_pendientes.md](informe_falla_pendientes.md).

---

## 1. Qué es el informe

Cuando una máquina de un cliente tiene una detención, el usuario abre **Reportes > Informe preliminar de falla**
en el dashboard, elige la **unidad** y la **fecha de la detención**, y opcionalmente escribe un relato (título,
descripción, hallazgos, acciones) y adjunta fotos. En uno o dos minutos recibe un PDF.

**Alcance:** reunir la información clave y los antecedentes de la máquina, el sistema o el componente, y
procesar la información disponible en el dashboard para dar una primera lectura del evento:
- qué mostraban los datos antes de la detención;
- la falla más probable y lo que la respalda o la contradice;
- qué revisar primero en la inspección;
- qué no se puede afirmar con los datos.

**No es un análisis de causa raíz definitivo:** la causa física se confirma en la inspección.

**Fuentes de hoy:**
- el Predictivo de motor (score semanal y diario de los 3 meses previos);
- el formulario y las fotos del usuario.

**Fuentes que faltan:** historial de detenciones y mantenciones (este documento), aceite, telemetría, alertas y
sistemas distintos del motor.

Clientes habilitados: **CDA** y **CAPSTONE** (servicio `reporting-informe-falla` en `config/client_services.json`).

## 2. Cómo se construye

```
Formulario (unidad, fecha, relato, fotos)
        │
        ▼
src/data/predictive_v2.py ── historial completo de unit_status_summary y risk_scores (motor)
        │
        ▼
src/informe_falla/service.validar_disponibilidad ── ¿hay datos en la ventana? si no, se avisa y no se genera
        │
        ▼
src/informe_falla/evidence.armar_evidencia ── reglas deterministas, SIN IA → "evidencia" (JSON)
        │
        ▼
src/informe_falla/agent.correr_agente ── la IA (gpt-6-luna, salida JSON con esquema estricto) redacta;
        │                       los controles revisan fuentes, hipótesis, pasos y vocabulario
        ▼
src/informe_falla/report_html.documento ── plantilla HTML; lo calculable sale de la evidencia, lo redactado de la IA
        │
        ▼
src/informe_falla/pdf.html_a_pdf (WeasyPrint) ── PDF A4 en outputs/informe_falla/<cliente>/IPF_*.pdf + registro JSON
```

Configuración (modelo, carpetas, caches): `src/informe_falla/config.py`. Método (ventanas, umbrales, modos, catálogo de
verificaciones): `src/informe_falla/catalog.py`.

**Principio clave:** todo lo que se puede calcular se calcula sin IA, y la IA solo redacta sobre ese paquete.
Además, la IA no puede inventar cifras: cada número que escribe debe existir en la evidencia, y cada hipótesis
cita las rutas de la evidencia que la respaldan (los controles lo verifican). Cualquier dato de detenciones que se
agregue debe entrar por la evidencia, ya procesado, para que la IA lo pueda citar.

### La evidencia (lo que recibe la IA)

| Clave | Contenido |
|---|---|
| `consulta` | unidad, fecha de la detención, semana ISO |
| `ventanas` | período analizado: las 13 semanas previas; el "último mes" se compara contra la base |
| `auditoria` | cobertura de datos, brechas, techo de confianza, advertencias |
| `trayectoria` | score semanal por modo de falla, semana a semana |
| `analisis_por_metrica.<modo>` | nivel (alto/medio/bajo/ninguno/sin_datos), semanas anómalas, comparación con la unidad y con la flota, componentes compatibles, verificaciones sugeridas |
| `diario` | lo mismo día a día (días anómalos, inicio del episodio, brechas con fechas exactas) |
| `ranking_modos`, `veredicto_reglas` | modos ordenados y veredicto determinista (SEÑAL CLARA / DÉBIL / SIN SEÑAL / DATOS INSUFICIENTES) |
| `acciones_previas` | pasos de inspección que valen para cualquier detención de motor |
| `contexto_cliente` | relato del formulario (sin verificar) |
| `cobertura_mantenciones`, `detenciones_previas`, `antecedentes_mantencion` | Intervenciones de mantención previas del sistema (`src/informe_falla/mantenciones.py`, sección 4) |

Modos de falla del motor: desgaste abrasivo, combustión, desbalance térmico, turbocargador, degradación del
aceite, contaminación por refrigerante, falla de lubricación, desgaste de cojinetes y blow-by. Cada modo tiene sus
componentes compatibles (`catalog.COMPONENTES_POR_MODO`), por ejemplo refrigerante: enfriador de aceite,
empaquetaduras de culata, bomba de agua, radiador y líneas de agua, termostatos.

## 3. El template (PDF) y de dónde sale cada parte

| Sección | Fuente | Estado |
|---|---|---|
| Encabezado: unidad, fecha, N.º `IPF-<unidad>-<AAAAMMDD>`, nota de alcance | Formulario | Listo |
| **Resumen**: causa más probable, qué mostró el Predictivo, recomendación principal, confianza | IA | Listo |
| Información entregada por el cliente / Fuentes consultadas | Formulario / fijo | Listo. "Fuentes" agrega "Historial de detenciones previas" cuando exista |
| 1. Identificación del evento: unidad, fecha, período, último dato, **componente afectado** | Evidencia | "Componente afectado" dice hoy "No informado: se infiere del Predictivo" |
| 2. Estado de la unidad antes de la detención | IA + cálculo | Listo |
| 3. Línea de tiempo | Evidencia | Señales y brechas listas; **detenciones previas: POR CONSTRUIR** |
| 4. Evidencia: gráfico del modo principal, otros modos, **detenciones previas (3 meses)** | Evidencia | Gráfico y otros modos listos; **tarjeta de detenciones: POR CONSTRUIR** (hoy oculta) |
| 5. Hipótesis evaluadas | IA | Listo. Las detenciones previas podrían sumar argumentos a favor o en contra |
| 6. Análisis de causa (cadena causal) | IA | Listo. El paso "¿Por qué no se detectó antes?" podría usar el historial |
| 7. Causa probable (física y contribuyentes) | IA | Listo |
| 8. Recomendaciones (inspección del catálogo + prevención) | IA | Listo |
| 9. Limitaciones | IA | Listo |
| 10. Registro fotográfico | Formulario | Listo |

### Lo que ya está preparado para las detenciones

La plantilla ya tiene los ganchos. Se activan solos cuando la evidencia trae `detenciones_previas`:

- **`evidencia["detenciones_previas"]`**:
  - `None` → historial no integrado: la tarjeta y las menciones se ocultan (estado actual);
  - `[]` → integrado, sin detenciones en el período: se muestra "Sin detenciones previas en el período analizado.";
  - lista → tabla en la sección 4 y puntos grises en la línea de tiempo.
- **Formato que lee hoy la plantilla** (`report_html._tabla_previas` y `_linea_de_tiempo`), una entrada por detención:
  ```json
  {"fecha": "2025-08-14", "tipo": "Correctiva", "componentes": "Bomba de agua, termostato"}
  ```
  `fecha` es obligatoria (ISO). `tipo` y `componentes` son texto libre opcional y se muestran tal cual.
- La IA recibe la evidencia completa, así que **verá `detenciones_previas` sin cambiar código**. Lo que falta es
  decirle en el prompt qué significa y cómo usarlas (sección 4).

## 4. Sección de detenciones (fase 1 implementada el 2026-10-16)

> **Actualización:** el análisis de mantenciones respondió con
> [plan_detenciones_previas_informe.md](plan_detenciones_previas_informe.md), y su fase 1 ya está implementada en
> `src/informe_falla/mantenciones.py` (ver "Estado de la implementación" en ese plan). Lo que sigue es el planteamiento
> original, conservado como contexto.

### Objetivo

Agregar al informe los **antecedentes de mantención y detención de la unidad** antes de la fecha del evento, para
que el informe:
1. muestre en la línea de tiempo y en la sección 4 qué intervenciones y detenciones hubo;
2. permita a la IA contrastar las hipótesis. Por ejemplo: "se reemplazó el enfriador de aceite hace 3 semanas" pesa
   a favor o en contra de "contaminación por refrigerante"; una falla repetida del mismo componente apunta a una
   causa no resuelta;
3. alimente el paso "¿Por qué no se detectó antes?" y las limitaciones.

### Data que conocemos (puntos de partida)

1. **Acciones de mantención:** `data/mantentions/golden/<cliente>/Maintance_Labeler_Views/query_3_actions_all_equipment.parquet`.
   - **Columnas:** `action_id, job_id, record_id, machine_id, machine_code, event_ts, change_date,
     action_type_name, job_system_name, job_subsystem_name, action_system_name, action_subsystem_name,
     component_names, component_count, target_level, action_detail_raw, action_detail_clean,
     action_detail_source, action_detail_version, source_system, record_original_text`.
   - **`action_type_name`:** Relleno, Inspección, Reemplazo, Ajuste.
   - **Cobertura (medida el 2026-10-15):**

     | Cliente | Filas | Desde | Hasta | Sistema de Motor |
     |---|---|---|---|---|
     | Capstone | 946 | 2025-07-13 | 2026-06-02 | 909 |
     | CDA | 11.131 | 2024-12-01 | 2026-01-22 | ~1.940 |

   - **Fecha confiable:** `change_date`.
   - **Prueba hecha:** se tomaron los reemplazos en "Sistema de Motor" como candidatos a evento y se agruparon por
     unidad (reemplazos a ≤ 7 días se cuentan como un evento). Dio 84 eventos en Capstone y 188 en CDA. Muchos son
     cambios de filtros (preventiva).
2. **Resúmenes semanales:** `data/mantentions/golden/<cliente>/NN-YYYY.csv` (`UnitId, Tasks_List, Summary`). El
   nombre del archivo **no** sirve como fecha (en Capstone va desfasado una semana).
3. **Base de detenciones** que usaba el notebook original (sqlite, tablas `records(record_id, machine_id,
   start_date, end_date, clean_text)` y `machines(machine_id, machine_code)`). **No está en el repo.** El
   `record_id` de `query_3` podría ser la llave hacia esos registros: confirmar.

### Restricciones conocidas

- Las vistas del labeler vienen **atrasadas desde el origen**: al 2026-09-23, 244 días en CDA y 113 en Capstone.
  Resincronizar no lo corrige.
- **Taxonomías de sistema distintas** entre fuentes ("Transmisión" vs "Tren de Fuerza", "Frenos" vs "Sistema de
  Frenado"). No inventar equivalencias: definirlas con el dominio.
- **Nombres de unidad:** `T_09` y `T_9` son la misma unidad. Normalizar con `src.data.report_health.unit_key`.
- **Sin fugas de información:** solo pueden entrar eventos **anteriores** a la fecha de la detención. El método
  excluye por diseño todo lo posterior.

### Lo que necesitamos del análisis de mantenciones

1. **Qué es una "detención"** en esta data: ¿hay un registro de detención con inicio y fin (`records`), o hay que
   inferirla de las acciones? ¿Cómo distinguir correctiva de preventiva o programada?
2. **Fuente y llave recomendadas** para traer los eventos de una unidad antes de una fecha (`query_3`, `records` u
   otra), y la cobertura real por cliente.
3. **Ventana:** ¿los mismos 3 meses del Predictivo, o más (fallas repetidas pueden estar más atrás)?
4. **Campos que valen la pena** por evento: fecha de inicio y fin, duración, tipo, sistema y subsistema,
   componentes, descripción limpia. ¿Se puede asociar a un modo de falla del Predictivo vía componentes?
5. **Filtros:** qué excluir (rellenos, inspecciones de rutina, cambios de filtro preventivos) para no llenar la
   línea de tiempo de ruido.
6. **La detención misma:** si hay un registro de la detención que se está analizando, ¿conviene usarlo? Por
   ejemplo, para llenar "Componente afectado". Ojo: el método está diseñado para no usar lo encontrado en la
   detención, así que es una decisión explícita.
7. **Casos de prueba** con historial conocido para validar la sección.

### Propuesta de contrato (a confirmar con ese análisis)

Una función nueva, sin IA, en `src/informe_falla/` (por ejemplo `detenciones.py`):

```python
def detenciones_previas(cliente: str, unidad: str, fecha: str, semanas: int = 13) -> list | None:
    """Eventos de mantencion/detencion de la unidad ANTES de `fecha`. None si no hay fuente para el cliente."""
```

Cada evento, como mínimo, con lo que ya lee la plantilla (`fecha`, `tipo`, `componentes`) y, si la data lo permite:

```json
{
  "fecha": "2025-08-14",
  "fin": "2025-08-15",
  "tipo": "Correctiva",
  "sistema": "Sistema de Motor",
  "subsistema": "Refrigeración",
  "componentes": "Bomba de agua, termostato",
  "descripcion": "Cambio de bomba de agua por fuga",
  "modos_relacionados": ["coolant_contamination_risk"],
  "fuente": "query_3:<action_id>"
}
```

Integración, una vez definido lo anterior:

1. `service.generar_informe` llama a la función y pone el resultado en `evid["detenciones_previas"]`.
2. **Prompt** (`agent.prompt_informe`): agregar qué son, que se pueden citar en "fuentes" como
   `detenciones_previas[fecha=2025-08-14]`, y cómo usarlas (repetición de fallas, intervenciones recientes sobre
   componentes compatibles), sin confundirlas con la detención analizada.
3. **Plantilla:** si se agregan campos, extender `_tabla_previas` (columnas) y `_linea_de_tiempo` (texto del evento).
4. **Validador:** decidir si la falta de historial bloquea el informe o solo se informa en limitaciones.
   Propuesta: no bloquea.
5. **Pruebas:** con eventos sintéticos, incluido uno posterior a la fecha, que no debe aparecer.

---

Archivos de referencia:
- `src/informe_falla/evidence.py`: evidencia y método.
- `src/informe_falla/agent.py`: prompt, esquema y controles.
- `src/informe_falla/report_html.py`: plantilla.
- `src/informe_falla/service.py`: orquestación y validador.
- `src/informe_falla/catalog.py` y `src/informe_falla/config.py`: método y configuración.
