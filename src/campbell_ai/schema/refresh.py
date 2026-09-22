"""Weekly refresh process for Campbell AI's declared dataset schema.

Regenerates `<data_root>/auxiliar/dataset_columns.json` - the copy the service prefers - from
the data actually on disk, and backs it up to S3. It deliberately does *not* touch the copy
committed under `src/campbell_ai/schema/`: that one is the reviewed record of the schema and
belongs to git, and a deployment process rewriting a versioned file would leave the checkout
dirty and the service running a declaration nobody approved.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
from datetime import datetime, time as day_time, timedelta, timezone
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo

from src.campbell_ai.schema import generated_schema_file
from src.campbell_ai.schema.build import (
    DEFAULT_DATA_S3_PREFIX,
    DEFAULT_HISTORY_S3_PREFIX,
    backup_to_s3,
    build,
    write_document,
)

logger = logging.getLogger("campbell_ai.schema.refresh")

DEFAULT_WEEKDAY = "monday"
DEFAULT_RUN_TIME = "08:00"
DEFAULT_TIMEZONE = "America/Santiago"
DEFAULT_S3_PREFIX = DEFAULT_HISTORY_S3_PREFIX
_STOP = Event()
_WEEKDAYS = {
    "monday": 0,
    "lunes": 0,
    "tuesday": 1,
    "martes": 1,
    "wednesday": 2,
    "miercoles": 2,
    "thursday": 3,
    "jueves": 3,
    "friday": 4,
    "viernes": 4,
    "saturday": 5,
    "sabado": 5,
    "sunday": 6,
    "domingo": 6,
}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _default_data_root() -> str:
    return (
        os.getenv("CAMPBELL_AI_SCHEMA_DATA_ROOT")
        or os.getenv("CAMPBELL_AI_DATA_ROOT")
        or "data"
    )


def _parse_weekday(value: str) -> int:
    normalized = value.strip().lower()
    if normalized.isdigit():
        number = int(normalized)
        if 0 <= number <= 6:
            return number
    if normalized in _WEEKDAYS:
        return _WEEKDAYS[normalized]
    raise ValueError("weekday debe ser monday/lunes o un numero 0..6")


def _parse_time(value: str) -> day_time:
    parts = value.strip().split(":")
    if len(parts) not in {2, 3}:
        raise ValueError("time debe tener formato HH:MM o HH:MM:SS")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    return day_time(hour=hour, minute=minute, second=second)


def _next_run(now: datetime, weekday: int, run_time: day_time) -> datetime:
    candidate = now.replace(
        hour=run_time.hour,
        minute=run_time.minute,
        second=run_time.second,
        microsecond=0,
    )
    days_until = (weekday - now.weekday()) % 7
    candidate += timedelta(days=days_until)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresca semanalmente dataset_columns.json en la maquina de la API."
    )
    parser.add_argument("--data-root", default=_default_data_root())
    parser.add_argument(
        "--weekday",
        default=_env_str("CAMPBELL_AI_SCHEMA_REFRESH_WEEKDAY", DEFAULT_WEEKDAY),
        help="Dia de ejecucion: monday/lunes o numero 0..6.",
    )
    parser.add_argument(
        "--time",
        default=_env_str("CAMPBELL_AI_SCHEMA_REFRESH_TIME", DEFAULT_RUN_TIME),
        help="Hora local de ejecucion, formato HH:MM.",
    )
    parser.add_argument(
        "--timezone",
        default=_env_str("CAMPBELL_AI_SCHEMA_REFRESH_TIMEZONE", DEFAULT_TIMEZONE),
        help="Zona horaria IANA para calcular la manana local.",
    )
    parser.add_argument(
        "--s3-prefix",
        default=_env_str("CAMPBELL_AI_SCHEMA_BACKUP_S3_PREFIX", DEFAULT_S3_PREFIX),
        help="Prefijo, fuera de la data, donde se guardan las copias fechadas.",
    )
    parser.add_argument(
        "--data-s3-prefix",
        default=_env_str("CAMPBELL_AI_SCHEMA_DATA_S3_PREFIX", DEFAULT_DATA_S3_PREFIX),
        help=(
            "Prefijo del bucket donde vive la data del dashboard. El documento se publica "
            "ahi, asi que la sincronizacion lo deja en la raiz de datos de cada despliegue."
        ),
    )
    parser.add_argument(
        "--backup-s3",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("CAMPBELL_AI_SCHEMA_BACKUP_S3", True),
        help="Sube el JSON generado a S3 despues de escribirlo localmente.",
    )
    parser.add_argument(
        "--aws-region",
        default=_env_str(
            "CAMPBELL_AI_SCHEMA_BACKUP_AWS_REGION",
            _env_str("AWS_DEFAULT_REGION", "us-east-1"),
        ),
    )
    parser.add_argument(
        "--output",
        default=_env_str("CAMPBELL_AI_SCHEMA_OUTPUT", ""),
        help=(
            "Donde escribir el documento generado. Por defecto "
            "<data_root>/auxiliar/dataset_columns.json, que es el que el servicio prefiere "
            "sobre la copia versionada del repositorio."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecuta un refresh y termina.",
    )
    parser.add_argument(
        "--run-on-start",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("CAMPBELL_AI_SCHEMA_REFRESH_RUN_ON_START", False),
        help="Controla si el proceso refresca inmediatamente al iniciar.",
    )
    return parser.parse_args(argv)


def refresh_once(
    data_root: str | Path,
    *,
    backup_s3: bool = True,
    s3_prefix: str = DEFAULT_S3_PREFIX,
    data_s3_prefix: str = DEFAULT_DATA_S3_PREFIX,
    aws_region: str = "us-east-1",
    output: str | Path | None = None,
) -> bool:
    """Regenerate the declaration that the service actually reads.

    Writes the *generated* copy inside the data root, never the committed one. Those are two
    different things on purpose: the committed file is the reviewed record of the schema and
    belongs to git, so a process that rewrote it in the deployment would leave the running
    service on a declaration nobody approved and the checkout permanently dirty.

    The local write alone would not survive: the next data sync mirrors the bucket into the
    data root and would put the previous document back. Publishing is what makes the refresh
    stick, and what lets every other deployment pick it up.
    """
    target = Path(output).expanduser() if output else generated_schema_file()
    logger.info("Regenerando %s desde %s", target, Path(data_root).expanduser())
    document = build(data_root)
    if not document["clients"]:
        # Nothing legible under the data root. Leaving the previous document in place is the
        # safe direction: the service keeps a declaration that worked instead of losing one.
        logger.warning("Sin datos legibles: no se actualiza %s", target)
        return False
    write_document(document, target)
    logger.info("Schema actualizado en %s", target)
    if backup_s3:
        return bool(
            backup_to_s3(
                target,
                data_prefix=data_s3_prefix,
                history_prefix=s3_prefix,
                region=aws_region,
            )
        )
    return True


def _install_signal_handlers() -> None:
    def stop(_signum: int, _frame: object) -> None:
        logger.info("Deteniendo refresh de schema")
        _STOP.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("CAMPBELL_AI_SCHEMA_REFRESH_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args(argv)
    weekday = _parse_weekday(args.weekday)
    run_time = _parse_time(args.time)
    tz = ZoneInfo(args.timezone)

    _install_signal_handlers()
    logger.info(
        "Refresh semanal de schema iniciado: data_root=%s weekday=%s time=%s timezone=%s run_on_start=%s",
        args.data_root,
        args.weekday,
        args.time,
        args.timezone,
        args.run_on_start,
    )

    if args.once:
        ok = refresh_once(
            args.data_root,
            backup_s3=args.backup_s3,
            s3_prefix=args.s3_prefix,
            data_s3_prefix=args.data_s3_prefix,
            aws_region=args.aws_region,
            output=args.output or None,
        )
        return 0 if ok else 1

    if args.run_on_start:
        try:
            refresh_once(
                args.data_root,
                backup_s3=args.backup_s3,
                s3_prefix=args.s3_prefix,
                data_s3_prefix=args.data_s3_prefix,
                aws_region=args.aws_region,
                output=args.output or None,
            )
        except Exception:  # noqa: BLE001 - keep the daemon alive after a startup miss
            logger.exception("Fallo el refresh inicial de schema; se reintentara en el ciclo")

    while not _STOP.is_set():
        now = datetime.now(tz)
        next_run = _next_run(now, weekday, run_time)
        delay = max(0.0, (next_run - now).total_seconds())
        logger.info("Proximo refresh de schema: %s", next_run.isoformat())
        if _STOP.wait(delay):
            break
        try:
            refresh_once(
                args.data_root,
                backup_s3=args.backup_s3,
                s3_prefix=args.s3_prefix,
                data_s3_prefix=args.data_s3_prefix,
                aws_region=args.aws_region,
                output=args.output or None,
            )
        except Exception:  # noqa: BLE001 - keep the process alive for the next window
            logger.exception("Fallo el refresh de schema; se reintentara en el proximo ciclo")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
