# TDS Alerts Dashboard

<div align="center">

**Sistema integral de monitoreo de condición de flotas mineras**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Dash](https://img.shields.io/badge/Dash-2.0+-green.svg)](https://dash.plotly.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

[Módulos](#-módulos) • [Instalación](#-instalación) • [Docker](#-docker) • [Datos](#-datos) • [Configuración](#-configuración)

</div>

---

## 🎯 Propósito

Dashboard multi-técnica que consolida **análisis de aceite**, **alertas operacionales**, **modelos predictivos** y **estado general de equipos** en una interfaz unificada. Soporta múltiples clientes con datos aislados.

---

## ✨ Módulos

### Activos

| Módulo | Descripción | Datos Clave |
|--------|-------------|-------------|
| 🛡️ **Menace Control** | Condición general de máquinas | Estado de flota, criticidad, tendencias |
| 🕐 **Update Data** | Frescura de datos | Hora de última actualización por fuente |
| 🚨 **Alerts** | Alertas enriquecidas | Telemetría + aceite + GPS + diagnóstico |
| 🧪 **Oil** | Análisis tribológico | Muestras, límites Stewart, clasificación AI |
| 🔮 **Predictive** | Modelos predictivos por componente | Ranking 0-100 por modo de falla (motor, transmisión) |
| 🤖 **Campbell AI** v1.1.3 | Asistente de mantenimiento basado en agentes | Consulta las mismas fuentes y permisos; gráficos interactivos, historial por usuario respaldado en S3 |

### Integraciones Futuras

| Módulo | Descripción |
|--------|-------------|
| 📡 **Telemetry** | Monitoreo de sensores y señales operacionales |
| 🔧 **Mantentions** | Estudio de registros de mantenimiento |
| 📊 **Reportability** | Reportes generados con AI sobre los datos |

---

## 🚀 Instalación

### Requisitos Previos

- Python 3.9+
- Docker 20.10+ y Docker Compose 2.0+
- Git

### Instalación Local

```bash
# Clonar repositorio
git clone <repository-url>
cd alerts_dashboard_production

# Crear entorno virtual
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Instalar dependencias


# Ejecutar
python -m dashboard.app
```

El dashboard estará disponible en: **http://localhost:8050**

---

## 🐳 Docker

### Docker Compose (Recomendado)

```bash
# Configurar entorno
cp .env.example .env
# Editar .env con SECRET_KEY y tokens necesarios

# Construir y ejecutar
docker-compose up -d

# Ver logs
docker-compose logs -f

# Detener
docker-compose down
```

### Docker Directo

```bash
docker build -t tds-dashboard .
docker run -d -p 8050:8050 --env-file .env -v ./data:/data:ro tds-dashboard
```

El dashboard estará disponible en: **http://localhost:8050**

**Credenciales por defecto:** `admin` / `admin123` (cambiar en producción)

### Mailing (resúmenes de alertas por correo)

Servicio `src/mailing/` (ver `documentation/mailling/01_mailing_service_backend.md`). Corre dentro
del mismo proceso del dashboard; no requiere infraestructura nueva ni un job externo.

| Variable (`.env`) | Para qué | Default |
|---|---|---|
| `LAMBDA_FUNCTION_NAME` | ARN de la Lambda que envía los correos (cuenta y región distintas a las de la app; la región se toma del ARN). **No se loguea ni se muestra** | — (obligatoria) |
| `DEPLOY_STATUS` | Entorno. `POC` = producción; cualquier otro valor (o ausente) = no producción. Solo cambia la selección por defecto de la pantalla Mailing (en no producción solo viene marcado Coddi Técnico), el aviso de confirmación y el campo `environment` de los logs. **No** cambia quién puede ser seleccionado ni quién recibe el envío automático | — |
| `MAILING_SCHEDULER_ENABLED` | En **producción**, `false` apaga el envío automático en esa máquina (Emin diario, Capstone miércoles, 12:00 `America/Santiago`). Los horarios están en el código (`MAILING_SCHEDULES`) y no se pueden cambiar por `.env`. **Fuera de producción el envío automático nunca corre**, con o sin esta variable | `true` (solo aplica en producción) |
| `SYNC_DATA` | Interruptor general de la sincronización con S3. Con `false` tampoco se sincroniza antes del envío automático | `true` |
| `MAILING_STATE_DIR` | Marcadores que garantizan un solo envío por (cliente, día); debe sobrevivir reinicios | `logs/mailing` (volumen montado) |
| `MAILING_RETRY_DELAYS` | Esperas (s) entre reintentos de un envío programado; la cantidad = nº de reintentos | `30,120,300` |
| `MAILING_MANUAL_COOLDOWN_SECONDS` | Ventana anti doble clic tras un envío manual exitoso | `5` |
| `MAILING_SCHEDULER_GRACE_MINUTES` | Cuánto después de las 12:00 aún se considera "a tiempo" (no hay envío de recuperación) | `15` |

Despliegue: (1) `LAMBDA_FUNCTION_NAME` y `DEPLOY_STATUS=POC` en el `.env` del
servidor (el envío usa `lambda:Invoke` del AWS SDK con el rol de ejecución; ese rol necesita `lambda:InvokeFunction` sobre el ARN y la política de la Lambda destino debe permitir al rol); (2) reconstruir la imagen (`requests` y `tzdata` se agregaron a `requirements.txt`);
(3) `docker-compose up -d`. Destinatarios y horarios se editan en `src/mailing/config.py`.
Con varios workers no hay duplicados: el primero que crea el marcador envía y los demás lo omiten.
Un envío manual no altera el envío automático.

**Emin en prueba.** Mientras `SCHEDULED_TECHNICAL_ONLY_CLIENTS` (en `src/mailing/config.py`) contenga `emin`, el envío automático de Emin llega solo a Coddi Técnico (`tds@` y `warren@coddi.ai`); Capstone envía a su audiencia real. Para poner Emin en producción real basta dejarlo vacío (`frozenset()`). No afecta el envío manual.

**Datos frescos.** Antes de armar cada correo automático se ejecuta la misma sincronización con S3 que la app corre al arrancar (`src.data.s3_downloader.main`), una vez por fecha y por proceso. Si falla (sin `BUCKET_NAME`, sin red, volumen de datos de solo lectura) se registra una advertencia y el correo se arma con los datos que hay en disco. El envío manual no sincroniza.

**El envío automático solo corre en producción.** El scheduler arranca únicamente cuando `DEPLOY_STATUS` es `POC` (o `production`); en un computador local, un servidor de desarrollo o de pruebas **no arranca** y nunca envía correos automáticos, aunque la máquina esté encendida a las 12:00 (el log dice `mailing scheduler not started: the environment is not production`). **Si en producción falta `DEPLOY_STATUS=POC`, el envío automático tampoco corre.** El horario se evalúa en hora de Chile sin importar la zona horaria del sistema operativo. El envío manual desde la pantalla Mailing funciona en todos los entornos. El marcador de "ya enviado" es por máquina; en producción `MAILING_SCHEDULER_ENABLED=false` apaga el envío automático de esa máquina. Cada intento queda en el log con `environment` y `host`.

---

## 📊 Datos

### Arquitectura

```
data/{técnica}/{capa}/{cliente}/{archivo}
```

| Técnica | Capa | Contenido |
|---------|------|-----------|
| `oil` | `golden` | Clasificaciones, límites Stewart, estado máquinas |
| `alerts` | `golden` | Alertas consolidadas con diagnóstico |
| `predictive` | `golden` | Rankings por componente (motor.csv, transmision.csv) |
| `telemetry` | `golden` | Alertas de sensores y reglas |
| `auxiliar` | `cda` | Datos auxiliares por cliente |

### Actualizar Datos

```bash
# Copiar nuevos archivos a data/{técnica}/golden/{cliente}/
# Reiniciar para cargar
docker-compose restart
```

---

## 🔧 Configuración

### Variables de Entorno

```bash
# .env
SECRET_KEY=your-secret-key-min-32-chars
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8050
DEBUG_MODE=False
CLIENTS=CDA,EMIN
MAPBOX_TOKEN=pk.xxx          # Opcional, para mapas GPS
OPENAI_API_KEY=sk-xxx        # Requerido para Campbell AI
```

Campbell AI's operational settings (feature flags, timeouts, model names, the internal
service token) live as `ENV` defaults in the `Dockerfile` instead of `.env` — none of them
are actually secrets. `OPENAI_API_KEY` is the only Campbell AI value that stays in `.env`. See
[src/campbell_ai/README.md](src/campbell_ai/README.md#configuración-local) for the full list
and how to override one without rebuilding the image.

### Iniciar API Campbell AI

```powershell
python -m dotenv run -- python -m uvicorn src.campbell_ai.api:app `
  --host 127.0.0.1 `
  --port 8000 `
  --reload
```

Campbell AI respalda cada interacción en la carpeta `campbellAI/` del bucket ya configurado
(`BUCKET_NAME`, `ACCESS_KEY`, `SECRET_KEY`) y mantiene un espejo en `logs/campbell_ai_backup`. Sin
bucket configurado sigue funcionando solo con el espejo local. Detalle en
[src/campbell_ai/README.md](src/campbell_ai/README.md).

### Credenciales

Editar `config/users.py`:
```python
USERS = {
    "admin": "your-secure-password",
}
```

---

## 🏗️ Estructura del Proyecto

```
├── dashboard/              # Aplicación Dash
│   ├── callbacks/          # Callbacks interactivos por sección
│   ├── components/         # Componentes UI reutilizables
│   ├── tabs/              # Módulos de contenido por sección
│   └── assets/            # CSS y recursos estáticos
├── config/                # Configuración (settings, users)
├── src/                   # Procesamiento de datos
│   ├── data/              # Loaders y transformers
│   └── utils/             # Utilidades
├── data/                  # Datos por técnica/capa/cliente
├── documentation/         # Contratos de datos
├── notebooks/             # Notebooks de exploración
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## 🔍 Troubleshooting

| Problema | Solución |
|----------|----------|
| Dashboard no inicia | `docker-compose logs` para ver errores |
| No muestra datos | Verificar archivos en `data/{técnica}/golden/{cliente}/` |
| Error de login | Verificar `config/users.py` y SECRET_KEY en `.env` |
| Puerto ocupado | Cambiar `DASHBOARD_PORT` en `.env` |

---

## 📋 Documentación

- [Campbell AI](src/campbell_ai/README.md) — agentes, API interna, persistencia y concurrencia
- [Campbell AI — changelog de la migración](documentation/general/campbell_ai_migration_changelog.md) — historial de cambios organizado en épicas, insumo para Jira
- [Oil Data Contracts](documentation/oil/DATA_CONTRACTS.md)
- [Telemetry Data Contracts](documentation/telemetry/data_contracts.md)
- [Alerts Data Contracts](documentation/alerts/data_contracts.md)
- [Mantentions Data Contracts](documentation/mantentions/data_contracts.md)

