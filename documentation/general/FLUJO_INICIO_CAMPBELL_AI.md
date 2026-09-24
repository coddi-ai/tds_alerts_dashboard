# Flujo de entrada a Campbell AI, paso a paso

Que ocurre exactamente desde que se abre la pestana de Campbell AI hasta que el globo de
estado dice `Listo · <CLIENTE>`, con los hitos en que ese globo cambia de texto.

Existe para responder dos preguntas: **que hace hoy cada paso** despues del cambio a esquema
declarado, y **si es lo que queremos** (seccion final).

Convencion: cada paso indica el archivo y la linea donde vive.

---

## T0 — Montaje de la pestana

Nada se ha pedido todavia; solo se dibuja el layout.

| Componente | Estado inicial |
| --- | --- |
| Globo `campbell-ai-status` | texto `Inicializando…`, color gris ([layout.py:718](../../dashboard/campbell_ai/layout.py#L718)) |
| `dcc.Interval` `campbell-ai-init-poll` | 500 ms, **deshabilitado** ([layout.py:654](../../dashboard/campbell_ai/layout.py#L654)) |
| `dcc.Store` `campbell-ai-init-phase` | `None` ([layout.py:662](../../dashboard/campbell_ai/layout.py#L662)) |

> **Globo: `Inicializando…`** (gris)

---

## T1 — `begin`, en el navegador (instantaneo)

Callback *clientside* disparado por `client-selector` ([callbacks.py:1408](../../dashboard/campbell_ai/callbacks.py#L1408)).

1. Si el globo ya muestra un estado final, no toca nada (el servidor gano la carrera).
2. Anota `startedAt` para el cronometro.
3. Elige la etiqueta de respaldo con un hecho conocido en el navegador: si `sessionStorage`
   trae un `session_id`, el trabajo incluye recuperar la conversacion (`Recuperando`); si no,
   es una sesion nueva (`Inicializando`).
4. **Enciende el poll.**

> **Globo: `Inicializando…` o `Recuperando…`** (gris)

---

## T2 — `synchronize_chat`, en el servidor Dash (bloqueante)

Mismo disparador que T1, asi que corren en paralelo ([callbacks.py:609](../../dashboard/campbell_ai/callbacks.py#L609)).

1. Descarta estado de navegador que pertenece a otro usuario (`_stale_browser_state`).
2. Resuelve `username` y `company_id`.
3. Decide `reusable_session`: el `session_id` guardado **solo** si la empresa no cambio
   ([callbacks.py:793](../../dashboard/campbell_ai/callbacks.py#L793)).
4. Llama `client.initialize(...)` — HTTP POST a la API.

**Un callback de Dash es atomico: no puede emitir un estado intermedio.** Por eso todo lo que
el usuario ve entre T2 y T6 lo escribe el ciclo clientside + poll, no este callback.

---

## T3 — API: `POST /initialize` -> `service.initialize`

Es la parte instrumentada por fases ([service.py:125](../../src/campbell_ai/service.py#L125)).
Cada fase se anuncia con `progress.advance` **antes** de ejecutarse, y el poll de T4 la lee.

### `identity` -> globo `Validando acceso`

`resolve_dashboard_principal`: usuario, rol y clientes permitidos. Si no hay sesion previa,
acuna un id nuevo `campbell_<uuid4>`. Puro CPU.

### `validate` -> globo `Leyendo datos`

`await asyncio.to_thread(repository.validate_client, company)`.

**Aqui esta el cambio principal.** Para un cliente declarado en `dataset_columns.json`
([data.py:1032](../../src/campbell_ai/data.py#L1032)) — la copia generada dentro de la raiz de
datos si existe, la versionada en el repositorio como respaldo; ver
[campbell_ai_schema_refresh.md](../campbell_ai_schema_refresh.md):

- **no abre ningun archivo**: da por presente cada dataset y valida las columnas requeridas
  contra la lista declarada;
- el unico disco que queda son los `Path.resolve()` de `dataset_path` — memoizados, una vez
  por proceso — y un `stat` de `auxiliar/manifest.json` por generacion del archivo.

Medido con la data actualizada (cda, 12/12 datasets validos): **5,8 ms en frio, 0,3 ms en
caliente**. Antes esta fase abria los 12 archivos y contaba filas.

Si ningun dataset resulta valido, `data_ready` es falso y se corta con `CampbellDataError`.

### `session` -> globo `Abriendo sesion`

`runtime.initialize` -> `sessions.create_if_absent`: crea la entrada del hilo en el store de
sesiones (memoria o Redis).

### `rehydrate` -> globo `Buscando conversacion`

**Solo si se esta reusando una sesion.** Si el hilo vivo esta vacio, busca el respaldo en S3 y
lo restaura ([service.py:247](../../src/campbell_ai/service.py#L247)). Es la unica fase con un
round trip de red. Cuando se salta se registra como `0` en vez de omitirse, para poder afirmar
que S3 no se toco.

### `capabilities` -> globo `Preparando agentes`

`await asyncio.to_thread(repository.client_capabilities, company, validation)`. Cruza los
datasets validos con los servicios habilitados del cliente para decidir que analisis se pueden
ofrecer. **Recibe la validacion de la fase anterior** en vez de recalcularla (antes la pasada
completa se corria dos veces).

### Cierre

Suma `phase_ms`, lo guarda para `/diagnostics` (`record_initialize_phases`), emite la linea
`initialize phases company=… total=…ms …` y, en el `finally`, `progress.finish`: desde ese
momento el poll responde `active: false`. Devuelve session_id, datasets, capabilities,
`restored_messages` y `phase_ms`.

---

## T4 — El poll, en paralelo (una consulta por segundo)

El intervalo late a 500 ms y `poll_initialization_phase` ignora un tick de cada dos
([callbacks.py:1442](../../dashboard/campbell_ai/callbacks.py#L1442)).

1. `POST /initialize/progress`: una busqueda en un diccionario en memoria, sin servicio ni
   acceso a datos, timeout propio de 2 s. Es deliberadamente trivial porque compite con la
   llamada pesada sobre la que informa.
2. Si responde `active` con etiqueta, la escribe en el store; si no, escribe `None`.
3. `tick` (clientside) arma el texto: **la etiqueta del servidor si llego**, la de respaldo si
   no, mas los segundos transcurridos a partir del cuarto segundo. A los 180 s se rinde y
   escribe `Sin respuesta`.

> **Globo: la fase en curso + cronometro**, p. ej. `Leyendo datos… 7s`

`active: false` significa "este proceso no sabe de esa llamada" — terminada, nunca iniciada, o
atendida por otra replica. No es un error y el globo solo vuelve a su etiqueta generica.

---

## T5 — `client.history` (solo al refrescar la pagina)

De vuelta en `synchronize_chat`: si habia sesion reusable, una **segunda** llamada HTTP,
`POST /history`, trae los mensajes del hilo ([callbacks.py:802](../../dashboard/campbell_ai/callbacks.py#L802)).
Si vuelve vacia se conserva lo que el navegador ya tenia.

---

## T6 — `synchronize_chat` retorna

Escribe sus diez salidas de una vez: id de sesion, historial, empresa sellada, limpieza del
store de fallas y el globo.

> **Globo: `Listo · CDA`** (verde)

---

## T7 — Se apaga el ciclo y se resuelven las capacidades

1. `settle` (clientside) ve que el globo ya no dice un texto suyo y **deshabilita el poll**.
2. Escribir `campbell-ai-session-store` dispara `resolve_client_capabilities`, que hace una
   **tercera** llamada `POST /initialize` — ahora con el session_id en mano, asi que reusa el
   hilo — para quedarse solo con `capabilities`
   ([callbacks.py:1926](../../dashboard/campbell_ai/callbacks.py#L1926)).
3. `render_suggested_questions` dibuja las preguntas sugeridas compatibles con ese cliente.
4. Se repite cada 5 minutos (`CAPABILITIES_REFRESH_MS`), porque una fuente puede sincronizar o
   romperse mientras la pestana esta abierta.

---

## Resumen de hitos del globo

| Momento | Texto | Color |
| --- | --- | --- |
| T0 montaje | `Inicializando…` | gris |
| T1 arranque | `Inicializando…` / `Recuperando…` | gris |
| T3 fase `identity` | `Validando acceso…` | gris |
| T3 fase `validate` | `Leyendo datos…` | gris |
| T3 fase `session` | `Abriendo sesion…` | gris |
| T3 fase `rehydrate` (solo al refrescar) | `Buscando conversacion…` | gris |
| T3 fase `capabilities` | `Preparando agentes…` | gris |
| desde los 4 s | se agrega el cronometro: `… 7s` | gris |
| a los 180 s | `Sin respuesta` | amarillo |
| T6 fin | `Listo · CDA` | verde |
| cualquier fallo | mensaje del error | rojo |

---

## Que cambio respecto de la version anterior

1. **`validate` ya no lee datos.** Abria los 12 archivos del cliente y contaba filas — decenas
   de MB y ~93 operaciones de disco por apertura de chat. Hoy confia en
   `dataset_columns.json`.
2. **La comprobacion real contra el disco se movio fuera del camino critico**: un hilo de
   fondo por contenedor (`start_schema_verification`) lee todas las cabeceras una vez y
   publica las diferencias en `/diagnostics`.
3. **`capabilities` reutiliza la validacion** en vez de recalcularla.
4. **Las dos llamadas de archivo salieron del event loop** a un thread, que es lo que permite
   que el poll de T4 pueda contestar mientras `initialize` sigue en vuelo.
5. **El globo dejo de inventar etiquetas por reloj.** Una version anterior cambiaba el texto a
   los 8 y a los 25 segundos con nombres inventados; hoy las fases las nombra el servidor.

---

## Es esto lo que queremos

Lo que si cumple el objetivo: abrir un chat ya no lee la base de datos, y el usuario ve el
paso real en vez de un cronometro mudo.

Puntos abiertos, en orden de importancia:

1. **La etiqueta `Leyendo datos` quedo desactualizada.** Describe lo que la fase hacia, no lo
   que hace (hoy es "validar columnas declaradas"). Induce al error de creer que el tiempo se
   va leyendo archivos — que es exactamente la confusion que tuvimos con los 20 s del
   despliegue.
2. **Tres llamadas a `/initialize` por entrada** (T3, T7 y el refresh de 5 min). La de T7
   existe solo para leer `capabilities`, que la respuesta de T3 ya trae y la UI descarta.
3. **El `to_thread` de `validate` ya no compra nada** (0,3 ms de trabajo) y si expone la fase
   a la cola del executor por defecto — es la sospecha principal detras de las esperas largas
   en esa fase.
4. **`start_schema_verification` construye su propio repositorio**
   ([api.py:169](../../src/campbell_ai/api.py#L169)), asi que el `_path_cache` que calienta no
   le sirve al servicio: la primera sesion del proceso sigue pagando los `resolve()` sobre EFS.
5. **Un dataset declarado que no llego ya no se detecta al abrir.** Aparece al leerlo, con el
   error explicito de `_read_frame`, y en `/diagnostics`. Es la contrapartida que aceptamos a
   conciencia al asumir presencia.

Cuando cambien las tablas hay que regenerar y commitear el JSON
(`python -m src.campbell_ai.schema.build`) antes del despliegue: si queda desfasado,
`declared_columns` devuelve `None` y se vuelve a leer cabeceras, que es la regresion que ya
vivimos una vez.
