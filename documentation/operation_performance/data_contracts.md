# Operación y rendimiento (OP-PE) · contrato de datos del dashboard

Pestaña **Monitoreo > Operación y rendimiento** (`/monitoring/operacion-rendimiento`, servicio
`monitoring-operation-performance`). Compara cada camión de extracción contra **su curva del
fabricante** (rimpull en subida, retardo en bajada) para decidir quién está **conforme** y quién se
**revisa**, y por qué. En pantalla el IV se llama **índice de velocidad**.

**Dos pestañas**:

- **Flota** (la decisión): los **indicadores de la semana** (desempeño ligado a la operación, con su
  color contra las semanas anteriores); una tarjeta a todo el ancho con un selector de vista: el
  **scatter carga vs IV contra la curva** (vista principal; eje horizontal en un desplegable: payload
  medio o distancia en rampa; eje vertical siempre el IV contra la curva, con 1,00 marcado) o el
  **mapa de calor ¿Quién va a fondo de mina?** (una fila por unidad, mejor IV relativo arriba:
  decisión, carga —payload medido; distancia en rampa sin payload— e IV relativo, que es el que
  decide; el resto de las variables se agregan con un selector; sin zoom). Un clic en una unidad la
  elige y abre su evidencia. Debajo, el
  **mapa de exigencia y desempeño** (trazado GPS real sobre imagen satelital: banda por
  pendiente de cada tramo + color por IV de la flota en la rampa) junto a la potencia en la rampa
  elegida (en el desplegable, en cualquiera de los mapas o en la ficha de la unidad).
- **Evidencia por unidad** (el porqué), con **un solo selector de unidad arriba a la izquierda**: ficha
  de la unidad (sin causa probable), **semanas anteriores** (media móvil de 3 días) junto a la curva
  del fabricante con la unidad destacada, y el **mapa de la unidad en sus rampas** con la lista de sus
  rampas (de la más a la menos exigente) al lado. La pestaña abierta se mantiene al cambiar de semana
  o flota. **Fuera de la página en esta versión** (sus figuras siguen en
  `operation_performance_charts.py`): el ranking por unidad, la tabla de decisión, las vistas de estrés
  "desempeño según la carga" y "ranking de una variable", la causa probable y el mapa de velocidad
  unidad / flota por tramo. Los paneles
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
- **KPIs**, en este orden: minutos perdidos, índice de velocidad de la flota, horas de motor a carga
  alta, distancia subida cargado. Cada uno se compara con el promedio de hasta 4 semanas completas
  anteriores (misma flota, `kpi_baseline`); el chip (y el ícono) toman el color de ese cambio: verde =
  mejor, ámbar = peor, rojo = bastante peor, gris = parecido ("▲ 12 % vs S43–S46"). El número del IV
  de la flota toma además el color de su rango (bajo 0,97 rojo, bajo 1,00 ámbar, si no verde).
  Minutos y horas se comparan como **fracción del tiempo** (de subida a fondo; en rampa), porque crecen
  con cuánto operó la flota; el IV en % (±1 % parecido, −3 % rojo); minutos: ±5 %
  parecido, +20 % rojo; horas: ±5 %, +15 %. La distancia es volumen, no desempeño: muestra su cambio
  sin color. (No hay payload en Capstone, así que se ligan a distancia, viajes y tiempo):
  - *Minutos perdidos*: suma de `camiones.min_perdidos_flota`; leyenda = % del tiempo (`dur_s`) de las
    subidas cargadas a fondo.
  - *Horas de motor a carga alta*: suma de `dur_s` de las pasadas en rampa con
    `carga_motor_pct_media` ≥ 90 %; leyenda = % del tiempo en rampa, viajes y la unidad con más horas.
    **Viaje** = par distinto (`unidad`, `viaje`) con al menos una subida cargada
    (`sentido == "subida"`, `estado == "cargado"`, a fondo o no). La *pérdida por viaje*
    (min perdidos × 60 / viajes) queda en la tabla y en la ficha de la unidad.
  - *Índice de velocidad de la flota*: IV de la población base ponderado por `dist_m` (la mediana simple va en la leyenda).
  - *Distancia subida cargado*: suma de `dist_m` de las subidas cargadas; leyenda = horas y, con payload
    medido (CDA), kt movidas = suma por viaje de la mediana de `payload_t_media` de sus pasadas cargadas.
- **Ficha de la unidad**: cada cifra (`unit_figures`) se compara con el promedio de la misma unidad en
  hasta 4 semanas anteriores en que tuvo datos (`unit_baseline`), con un chip en la escala de severidad.
  Con juicio: IV relativo e IV contra la curva (mayor es mejor; ±0,01 parecido, −0,03 rojo), minutos
  perdidos (como fracción de su tiempo subiendo a fondo) y pérdida por viaje (menor es mejor; ±5 %
  parecido, +20 % rojo). Sin juicio (solo la flecha y el cambio): subidas, viajes, horas y carga de
  motor (en puntos), porque dicen cuánto operó, no cómo rindió. **Dos colores distintos**: el
  **número** toma el color de su propio rango (`kpi_level`): un IV (relativo, contra la curva o el de
  la flota) bajo 0,97 rojo, entre 0,97 y 1,00 ámbar, desde 1,00 verde; la pérdida por viaje y la
  fracción de tiempo perdida contra la mediana de su flota (≥ 1,2× ámbar, ≥ 1,5× rojo, ≤ 1× verde);
  las cifras de volumen no tienen rango. El **chip** toma solo el color de su cambio contra las semanas
  anteriores. Los IV muestran su cambio en % con un decimal (±1 % parecido, −3 % rojo); un cambio que
  redondea a 0 se muestra "0 %" (sin flecha). Sin semanas anteriores no hay chip, pero el número mantiene su color.
- **Por unidad** (`unit_operation`, tabla de fondo de mina y ficha): viajes, km y horas subiendo
  cargado, carga de motor mediana en la población base (`carga_motor_pct_media`) y pérdida por viaje
  (s). Carga alta con IV bajo apunta al motor/propulsión; carga baja con IV bajo, a operación o derrateo.
- **Estrés operacional** (`unit_stress`: scatter y mapa de calor de la pestaña Flota; las figuras de
  desempeño según la carga y de ranking de una variable quedan fuera de la página). Por unidad, solo las
  señales que el cliente tiene: viajes, km en rampa (toda pasada), carga (payload medio por viaje en
  CDA; **`masa_aparente_t`** mediana de las subidas cargadas en Capstone, una estimación del pipeline
  desde potencia, pendiente y velocidad), horas de motor ≥ 90 %, carga de motor en subida y rpm (y
  potencia en Capstone) ponderadas por tiempo, litros por km subido cargado y pendiente mediana de sus
  rutas. *Índice de estrés* = promedio de cada valor / mediana de su flota. "Desempeño según la carga"
  corta las subidas cargadas en 6 grupos de igual tamaño (cuantiles de la flota; una por valor si hay
  ≤ 6 valores distintos) y compara la mediana de la unidad (≥ 3 subidas en el grupo) con la de la flota.
- **Semanas anteriores**: `camion_dia` de cada semana completa hasta la elegida. Línea de la unidad =
  media móvil de 3 días calendario de su `iv_rel_p50` diario, cada día ponderado por sus `pasadas`;
  línea de la flota = media móvil de 3 días de la mediana diaria de su flota. Los ejes marcan cada
  semana; la leyenda cuenta las decisiones semanales (`camiones`).
- **IV por tramo** (mapa de la unidad): velocidad del tramo / velocidad que da la curva de propulsión
  del modelo para la fuerza `gvw_t × (pend_pct del tramo + RR) / 100`, con RR = `tr_pct − pend_pct` de
  la pasada (1,5 %). La velocidad esperada es la mayor velocidad a la que la curva aún entrega esa
  fuerza, interpolada (reproduce `v_esp_kmh` del pipeline con error < 0,5 %). Por tramo, mediana de
  las subidas de la unidad (≥ 3); también la carga de motor, rpm y potencia (Capstone) del tramo.
- **Rampas de la unidad**: sus rampas con ≥ 3 subidas cargadas a fondo y trazado en el mapa, por
  pendiente mediana de la flota descendente; cada una con su color de exigencia, largo, IV de la
  unidad, IV relativo y la marca "pierde" con IV relativo < 0,97.
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
  pasaron por ahí (≥ 3 y ≥ 20 % de las de la rampa). Mapa de la flota: banda bajo el trazado por
  pendiente media de cada par de tramos consecutivos (< 6 %, 6–8 %, 8–10 %, ≥ 10 %; más ancha y oscura
  = más exigente) y, encima, el trazado coloreado por la mediana del IV contra la curva en la rampa
  (también en la etiqueta: `S1F8C8 · 0,98`); la leyenda nombra las 3 rampas de mayor pendiente
  mediana. Mapa de la unidad: cada rampa con el color y ancho de su banda de exigencia (pendiente
  mediana) y, encima, los tramos de la unidad coloreados por su IV por tramo (rojo < 1 < azul) o por
  carga de motor / rpm / potencia; con una rampa elegida solo esa lleva datos y la vista se ajusta a
  ella. Sin tramos suficientes muestra un mensaje, nunca otro color. Mapa base satelital de Esri World Imagery (o calles de OpenStreetMap); ambos requieren internet.
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
