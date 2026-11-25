# Operación y rendimiento (OP-PE) · contrato de datos del dashboard

Pestaña **Monitoreo > Operación y rendimiento** (`/monitoring/operacion-rendimiento`, servicio
`monitoring-operation-performance`). Compara cada camión de extracción contra **su curva del
fabricante** (rimpull en subida, retardo en bajada) para decidir quién está **conforme** y quién se
**revisa**, y por qué. En pantalla el IV se llama **índice de velocidad**.

Es **una sola página** que se lee de arriba abajo: indicadores de la semana → ranking de desempeño en
subida por unidad junto a la **unidad en análisis** (clic en una barra para elegirla) → **mapa
satelital** con el trazado GPS real de las rampas, coloreado por pendiente, desempeño de la flota o
la unidad contra la flota → curva del fabricante con la unidad destacada (y hasta 5 unidades del mismo
modelo para comparar, en su propio selector) y potencia en la rampa
elegida (en el desplegable, en el mapa o en la ficha de la unidad) → tabla de decisión. Los paneles
de diagnóstico, tendencia, bajada y calidad de datos de la especificación **quedan fuera de la página
por ahora**; sus figuras siguen en `operation_performance_charts.py` por si se reincorporan.

El cálculo lo hace el pipeline semanal del repositorio OP-PE (bronce → plata → oro). El dashboard
**no recalcula el método**: lee, filtra y agrega las tablas oro y la tabla de calidad de plata.

| Cliente | Camión | Carga |
|---|---|---|
| CDA | Cat 789C | Medida en cada ciclo (`payload_t_media`) |
| Capstone | Komatsu 830E-5 (CA-30 a CA-65) y 830E-AC (CA-80 a CA-93, "830E-1 MCRS") | No hay: carga nominal de ficha |

## Dónde está la data

El gestor de descargas (`src/data/s3_downloader.py`) sincroniza todo `MultiTechnique Alerts/`, así que
la data llega a:

```
data/operation-performance/<cliente>/gold/WeekNNYearYYYY/*.parquet        paneles
data/operation-performance/<cliente>/silver/WeekNNYearYYYY/tramos.parquet   posición GPS cada 100 m (mapa)
data/operation-performance/<cliente>/silver/WeekNNYearYYYY/calidad.parquet  calidad de datos (fuera de la página)
```

- `<cliente>` en minúsculas (`cda`, `capstone`). La raíz respeta `DASHBOARD_DATA_ROOT`.
- La carpeta de semana es la semana ISO en hora de Chile (lunes a domingo).
- **Una semana está completa solo si tiene `manifest.json`** (el pipeline lo escribe al final). Las
  semanas sin manifiesto no se listan.
- El pipeline reescribe las 2 últimas semanas cada vez; la lectura se cachea por (mtime, tamaño), así
  que un archivo reescrito se vuelve a leer y uno intacto no.
- De plata se usa `tramos.parquet` (solo `pasada_id`, `tramo`, `lat`, `lon`, `pend_pct`, `v_kmh`, para el
  mapa) y `calidad.parquet`. `senales.parquet` (75–115 MB) **no** se usa.

## Tablas

| Tabla | Capa | Una fila por | Llave | Paneles |
|---|---|---|---|---|
| `camiones` | oro | camión de la semana | `unidad` | KPIs, ranking, decisión, minutos perdidos; color por decisión |
| `pasadas_eval` | oro | pasada en rampa (≥ 300 m, \|pend.\| ≥ 4 %) | `pasada_id` | KPIs, causa, curva, potencia en la rampa, retardo |
| `camion_dia` | oro | camión y día | `unidad` + `dia` | Tendencia (todas las semanas juntas) |
| `rampas` | oro | rampa | `rampa_id` | Mapa, nombre de la rampa |
| `curvas` | oro | punto de curva | `modelo` + `curva` | Curva del fabricante |
| `frenos` | oro, **solo CDA** | camión y estado | `unidad` + `estado` | Temperatura de frenos |
| `potencia` | oro, **solo Capstone** | camión y día | `unidad` + `dia` | Potencia sostenida del motor |
| `escape` | oro, **solo Capstone** | camión y cilindro | `unidad` + `cilindro` | Escape por cilindro |
| `tramos` | **plata** | tramo de 100 m de una secuencia | `pasada_id` + `tramo` | Mapa: trazado real y pendiente por tramo |
| `calidad` | **plata** | camión y día | `unidad` + `dia` | Calidad de datos (fuera de la página) |

Los paneles propios de un cliente aparecen solo si su tabla existe (no hay configuración por cliente).

Relaciones: `pasadas_eval.unidad → camiones.unidad`; `pasadas_eval.rampa_id → rampas.rampa_id`
(estable entre semanas; `S…` subida, `B…` bajada); `pasadas_eval.modelo → curvas.modelo` con
`tipo == "propulsión"`. `camion_dia` no trae la semana: se agrega desde el nombre de la carpeta, y si
un día aparece en dos semanas se queda la más nueva.

## Reglas que aplica el dashboard

- **Subida cargada a fondo** (población con la que se decide cada camión):
  `sentido == "subida"`, `capacidad == True`, `estado == "cargado"`.
- **Decisión** (`camiones.decision`, ya viene calculada), por la mediana del IV relativo:
  Conforme ≥ 1,00 · Seguimiento 0,97–1,00 · Revisar < 0,97 · Sin datos suficientes con menos de
  10 subidas a fondo. El pipeline escribe la mejor decisión como "Fondo de mina"; `load_week` la
  renombra a **Conforme** al leer, así que todo el dashboard usa un solo nombre. Colores: escala única de severidad (`shared/severity.py`: bajo / atención / alto,
  neutro para Sin datos).
- **KPIs**: camiones evaluados (decisión ≠ Sin datos suficientes), IV mediano (mediana de `iv` en la
  población base), camiones a revisar, suma de `min_perdidos_flota`.
- **Rampa principal**: el `rampa_id` con más subidas cargadas a fondo (selector con todas las rampas de subida).
- **Causa probable**: pasadas con `bajo_flota == True` y `causa` no nula, contadas por camión y causa.
  Las causas que no apuntan al motor ("Sin causa…", "Fuera del motor…") van en gris.
- **Escape**: las celdas con `sensor_sospechoso` (> ±150 °C) quedan fuera de la escala (±60 °C) y se
  marcan con ×; camiones ordenados por su mayor desvío sin contar sospechosos.
- **Dispersión** (curva, retardo): muestra aleatoria fija de 4.000 pasadas como máximo.
- **Orden de las unidades** en los selectores y en las cajas por rampa: letras y luego el número de
  menor a mayor (`CA-9` antes que `CA-30`; `11` antes que `101`).
- **Unidad en análisis**: abre en la peor unidad en Revisar (o la de menor IV relativo firme). La rampa
  inicial es la rampa donde esa unidad pierde más (mediana de su IV relativo, con ≥ 3 subidas).
- **Mapa**: las 30 rampas de subida con más subidas cargadas a fondo. Sus tramos de 100 m
  (`tramos.pasada_id` → `pasadas_eval`) se alinean por posición dentro de la subida (`k` = 0 los
  primeros 100 m); cada punto es la mediana de posición, pendiente y velocidad de las subidas que
  pasaron por ahí (≥ 3 y ≥ 20 % de las de la rampa). Colores: *pendiente* = exigencia del tramo;
  *desempeño de la flota* = mediana del IV contra la curva en la rampa; *unidad vs flota* = velocidad
  mediana de la unidad en el tramo / la de la flota en el mismo tramo (≥ 3 subidas de la unidad).
  Mapa base satelital de Esri World Imagery (o calles de OpenStreetMap); ambos requieren internet.
  Las etiquetas de rampa llevan un marcador transparente: un trazo `Scattermap` solo de texto hace que
  MapLibre rechace la capa (`text-offset` NaN) y el mapa deja de responder a los selectores.

Glosario: **IV** (*índice de velocidad* en pantalla) = v real / v esperada por la curva (1 = rinde lo que dice la curva). **IV relativo** =
IV / mediana de la flota en la misma rampa (es el que decide). **HP en pendiente** = peso bruto (kg) ×
(pendiente + RR) × v (km/h) / 273,75, con RR = 1,5 %.

## Código

| Archivo | Qué hace |
|---|---|
| `src/data/operation_performance.py` | Semanas, lectura cacheada, filtro de flota, historia y reglas (sin Dash) |
| `dashboard/components/operation_performance_charts.py` | Una figura por panel |
| `dashboard/components/operation_performance_views.py` | Tarjetas de panel, KPIs, tabla de decisión, estados vacíos |
| `dashboard/tabs/tab_operation_performance.py` | Layout de la página |
| `dashboard/callbacks/operation_performance_callbacks.py` | Callbacks |
| `tests/test_operation_performance.py` | Reglas, figuras, layout, callbacks y registro |

Acceso por cliente: `config/client_services.json` (habilitado para CDA y CAPSTONE). Fuentes del
popover: `op_pe_gold` y `op_pe_quality` (`config/service_data_sources.py`, `src/data/catalog.py`).
