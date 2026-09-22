# Refresh semanal de `dataset_columns.json`

`dataset_columns.json` es el snapshot de columnas que Campbell AI usa para no abrir todos los
datasets al iniciar una sesion.

## Dos copias y una regla de precedencia

| Copia | Ruta | Quien la escribe | Rol |
| --- | --- | --- | --- |
| **Generada** | `<data_root>/auxiliar/dataset_columns.json` (`/app/data/auxiliar/…` en Compose) | el refresh semanal | **manda**: se deriva de la data real y nunca esta mas de un ciclo atras del ETL |
| **Versionada** | `src/campbell_ai/schema/dataset_columns.json` | una persona, con `build.py`, y se commitea | respaldo, y registro revisable de como cambio el esquema entre versiones |

El servicio prefiere la generada. Si no esta, o no parsea, cae a la versionada — nunca a leer
todas las cabeceras otra vez. Con ninguna de las dos usable vuelve al comportamiento antiguo de
leer cabeceras, que es correcto pero lento.

`/diagnostics` informa cual esta en uso en `schema.source` (`generated` | `packaged` | `none`)
y las dos rutas candidatas. Es el dato que distingue "la declaracion dice X" de "una copia
generada vieja esta tapando el arreglo que commiteaste".

`data/` esta en `.gitignore`, asi que la copia generada nunca entra al repositorio.

## El proceso

Corre como un **hilo dentro del proceso de la API**, arrancado desde el hook de startup junto
al janitor y al archivador de logs (`SchemaRefresher` en `refresh.py`). No es un contenedor
aparte y no debe volver a serlo: una segunda imagen es una segunda cosa que construir,
desplegar y mantener en sincronia, para un trabajo que despierta una vez por semana y corre un
segundo. El compose tiene los dos servicios de siempre, `dashboard` y `campbell-api`.

No hace deteccion de cambios: despierta en el horario configurado, regenera y publica. Por
defecto los lunes a las 08:00 en `America/Santiago`.

```bash
CAMPBELL_AI_SCHEMA_REFRESH_ENABLED=true
CAMPBELL_AI_SCHEMA_REFRESH_WEEKDAY=monday
CAMPBELL_AI_SCHEMA_REFRESH_TIME=08:00
CAMPBELL_AI_SCHEMA_REFRESH_TIMEZONE=America/Santiago
CAMPBELL_AI_SCHEMA_BACKUP_S3=true
CAMPBELL_AI_SCHEMA_DATA_S3_PREFIX=MultiTechnique Alerts/auxiliar
CAMPBELL_AI_SCHEMA_BACKUP_S3_PREFIX=campbellAI/schema/dataset_columns
```

El respaldo usa las mismas credenciales S3 del despliegue: `BUCKET_NAME`, `ACCESS_KEY` y
`SECRET_KEY`.

Flujo:

1. Lee los datos montados en `CAMPBELL_AI_SCHEMA_DATA_ROOT` (`/app/data` en Compose).
2. Regenera el documento leyendo la cabecera real de cada dataset.
3. Intenta escribirlo en `<data_root>/auxiliar/dataset_columns.json`, de forma atomica: se
   escribe al lado y se renombra encima, asi que un lector ve el documento viejo o el nuevo,
   nunca la mitad de uno.
4. Lo publica en S3, en dos lugares distintos por razones distintas (ver mas abajo).

**Si la raiz de datos es de solo lectura, publica igual.** Es el caso normal: `campbell-api`
monta `./data:/app/data:ro`. La escritura local falla, se registra como INFO, el documento se
arma en un temporal y desde ahi se publica — que es el paso que importa, porque el documento
llega a cada despliegue por la sincronizacion de datos.

**No toca la copia versionada.** El montaje de `./src` es de solo lectura.

Su estado esta en `/diagnostics` bajo `schema.refresh`: si el hilo esta vivo, cuando despierta
(`next_run`), cuando corrio por ultima vez y con que resultado.

## Las dos claves de S3

| Clave | Para que |
| --- | --- |
| `MultiTechnique Alerts/auxiliar/dataset_columns.json` | **dentro del prefijo de la data.** `S3Downloader.download_folder` preserva estructura, asi que esta clave aterriza en `data/auxiliar/dataset_columns.json` de cada despliegue — justo la copia que el servicio prefiere. El esquema viaja con la data que describe: un despliegue que sincroniza la data obtiene el esquema que le corresponde, sin paso de arranque y sin ventana en que ambos discrepen. Una sola clave, sobrescrita. |
| `campbellAI/schema/dataset_columns/history/<timestamp>/dataset_columns.json` | la copia fechada, **fuera** del prefijo de la data justamente para que la sincronizacion no la espeje: un `history/` dentro de la data se descargaria como basura en `data/auxiliar/history/…`. |

Nadie *lee* estas claves desde el codigo: la primera entra al despliegue por la sincronizacion
de datos, la segunda es historial para mirar a mano.

Y por eso el refresh publica ademas de escribir en local: la escritura local por si sola no
sobrevive, porque la siguiente sincronizacion espeja el bucket sobre la raiz de datos y
repondria el documento anterior.

### La guardia contra publicar una raiz a medio sincronizar

Publicar alcanza a todos los despliegues. Un documento construido sobre una raiz de datos que
solo llego a medias es perfectamente valido y retira en silencio los analisis de quien falte, y
la escritura local nunca lo revelaria. Por eso `build.py` compara contra el documento que
reemplaza: si el nuevo declara **menos clientes** que el anterior, escribe en local pero **no
publica**, y sale con codigo 1 diciendo cuales faltan. Si la perdida es real, `--force`.

Si bajo la raiz de datos no hay nada legible, no escribe: deja el documento anterior en su
lugar. Perder la declaracion es peor que tenerla una semana vieja.

## Cuando cambian las tablas

1. Regenerar **sin publicar**, y revisar el diff:

```bash
python -m src.campbell_ai.schema.build --data-root data --no-backup-s3
git diff src/campbell_ai/schema/dataset_columns.json
```

2. Commitear. Ese diff es el registro de que cambio en el esquema.
3. Publicar, ahora que el diff esta revisado:

```bash
python -m src.campbell_ai.schema.build --data-root data
```

Esto reescribe el mismo documento y lo sube al bucket. Desde ese momento cualquier despliegue
que sincronice la data recibe el esquema nuevo, sin esperar al lunes.

4. Desplegar el commit.

Si prefieres que sea el despliegue quien regenere y publique, en vez del paso 3:

```bash
docker compose exec campbell-api python -m src.campbell_ai.schema.refresh --once
```

Sin el paso 3 ni ese comando, la copia generada — que es la que manda — sigue describiendo la
data anterior hasta el lunes.

Para inspeccionar sin escribir nada compartido:

```bash
python -m src.campbell_ai.schema.build --data-root data --no-backup-s3 --output /tmp/salida.json
```

## Propagacion a la API

La API relee los candidatos como maximo una vez por minuto (`_FRESHNESS_INTERVAL_SECONDS`), no
en cada consulta: `declared_columns` se llama una vez por dataset dentro de `validate_client`, y
un `stat` por llamada devolveria parte de los round trips que la declaracion existe para quitar.

En la practica: un refresh surte efecto dentro del minuto siguiente, **sin reiniciar la API**.
