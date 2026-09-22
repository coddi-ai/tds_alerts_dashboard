"""Weekly refresh of Campbell AI's declared dataset schema.

Regenerates `<data_root>/auxiliar/dataset_columns.json` - the copy the service prefers - from
the data actually on disk, and publishes it to S3. It deliberately does *not* touch the copy
committed under `src/campbell_ai/schema/`: that one is the reviewed record of the schema and
belongs to git, and a deployment process rewriting a versioned file would leave the checkout
dirty and the service running a declaration nobody approved.

**Runs as a thread inside the API process**, started from the API's startup hook next to the
janitor and the log archiver - `SchemaRefresher` below. It is not its own container and must
not become one: a second image is a second thing to build, ship and keep in step, for a job
that wakes up once a week and runs for a second.

`main()` remains for running a single refresh by hand:

    python -m src.campbell_ai.schema.refresh --once
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import tempfile
import threading
from datetime import datetime, time as day_time, timedelta, timezone
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo

from src.campbell_ai.schema import _data_root as schema_data_root, generated_schema_file
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
    """The same root `generated_schema_file()` resolves, never a relative path.

    These two have to agree: this process reads the data under X and writes the declaration to
    `<X>/auxiliar/`. Resolving them separately worked only while the current directory happened
    to be the project root - true under `uvicorn` in the container, and not something to
    depend on now that this runs inside the API rather than as its own entrypoint.
    """
    return str(schema_data_root())


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

    # Where the bytes to publish are read from. Normally the target itself.
    source = target
    try:
        write_document(document, target)
        logger.info("Schema actualizado en %s", target)
    except OSError as exc:
        # Expected, not exceptional: this now runs inside the API process, and the API mounts
        # its data root read-only. Publishing is the step that matters - the document reaches
        # every deployment through the data sync - so a read-only root must not stop it.
        source = Path(tempfile.gettempdir()) / "campbell_ai_dataset_columns.json"
        write_document(document, source)
        logger.info(
            "La raiz de datos no es escribible (%s); se publica igual desde %s",
            type(exc).__name__,
            source,
        )

    if backup_s3:
        return bool(
            backup_to_s3(
                source,
                data_prefix=data_s3_prefix,
                history_prefix=s3_prefix,
                region=aws_region,
            )
        )
    return True


class SchemaRefresher:
    """The weekly refresh, as a thread inside the process that serves the API.

    It used to be its own container. That was wrong for this deployment: a second image means
    a second thing to build, ship and keep in step, for a job that wakes up once a week and
    runs for a second. It is the same shape as the janitor and the log archiver, which already
    live here for the same reason - one image, one process, threads that sleep.

    Daemon thread, and every failure is swallowed and retried on the next window: a refresh
    that could not run is a schema one cycle older, while a refresh that killed the API would
    be an outage.
    """

    def __init__(
        self,
        *,
        data_root: str | Path,
        weekday: int,
        run_time: day_time,
        timezone: str,
        backup_s3: bool = True,
        s3_prefix: str = DEFAULT_S3_PREFIX,
        data_s3_prefix: str = DEFAULT_DATA_S3_PREFIX,
        aws_region: str = "us-east-1",
        run_on_start: bool = False,
    ) -> None:
        self.data_root = data_root
        self.weekday = weekday
        self.run_time = run_time
        self.timezone = timezone
        self.backup_s3 = backup_s3
        self.s3_prefix = s3_prefix
        self.data_s3_prefix = data_s3_prefix
        self.aws_region = aws_region
        self.run_on_start = run_on_start
        self._tz = ZoneInfo(timezone)
        self._stop = Event()
        self._thread: "threading.Thread | None" = None
        self._last_run: str = ""
        self._last_result: str = "never"
        self._next_run: str = ""

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> "SchemaRefresher":
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="campbell-schema-refresh", daemon=True
        )
        self._thread.start()
        logger.info(
            "schema refresh started weekday=%s time=%s timezone=%s run_on_start=%s",
            self.weekday,
            self.run_time.isoformat(),
            self.timezone,
            self.run_on_start,
        )
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    # -- work ----------------------------------------------------------------

    def run_cycle(self) -> bool:
        """One refresh. Never raises: the caller is a thread that has to survive it."""
        try:
            ok = refresh_once(
                self.data_root,
                backup_s3=self.backup_s3,
                s3_prefix=self.s3_prefix,
                data_s3_prefix=self.data_s3_prefix,
                aws_region=self.aws_region,
            )
            self._last_result = "ok" if ok else "sin cambios publicados"
            return ok
        except Exception as exc:  # noqa: BLE001 - a failed refresh must not kill the API
            self._last_result = f"error: {type(exc).__name__}: {exc}"
            logger.exception("Fallo el refresh del esquema; se reintentara en el proximo ciclo")
            return False
        finally:
            self._last_run = datetime.now(self._tz).isoformat()

    def _run(self) -> None:
        if self.run_on_start:
            self.run_cycle()
        while not self._stop.is_set():
            now = datetime.now(self._tz)
            following = _next_run(now, self.weekday, self.run_time)
            self._next_run = following.isoformat()
            logger.info("Proximo refresh de schema: %s", self._next_run)
            if self._stop.wait(max(0.0, (following - now).total_seconds())):
                break
            self.run_cycle()

    def stats(self) -> dict[str, object]:
        """What this refresher has done and when it wakes up next, for `/diagnostics`."""
        return {
            "running": bool(self._thread is not None and self._thread.is_alive()),
            "weekday": self.weekday,
            "time": self.run_time.isoformat(),
            "timezone": self.timezone,
            "next_run": self._next_run or None,
            "last_run": self._last_run or None,
            "last_result": self._last_result,
            "backup_s3": self.backup_s3,
        }


_REFRESHER: "SchemaRefresher | None" = None
_REFRESHER_LOCK = threading.Lock()


def start_schema_refresh() -> "SchemaRefresher | None":
    """Start the weekly refresh in this process. None when disabled or misconfigured.

    Called from the API startup hook, beside the janitor and the log archiver. Disabled with
    ``CAMPBELL_AI_SCHEMA_REFRESH_ENABLED=false`` for a deployment that would rather regenerate
    the document from somewhere else.
    """
    global _REFRESHER
    with _REFRESHER_LOCK:
        if _REFRESHER is not None:
            return _REFRESHER
        if not _env_bool("CAMPBELL_AI_SCHEMA_REFRESH_ENABLED", True):
            logger.info("schema refresh disabled by CAMPBELL_AI_SCHEMA_REFRESH_ENABLED")
            return None
        try:
            refresher = SchemaRefresher(
                data_root=_default_data_root(),
                weekday=_parse_weekday(
                    _env_str("CAMPBELL_AI_SCHEMA_REFRESH_WEEKDAY", DEFAULT_WEEKDAY)
                ),
                run_time=_parse_time(
                    _env_str("CAMPBELL_AI_SCHEMA_REFRESH_TIME", DEFAULT_RUN_TIME)
                ),
                timezone=_env_str("CAMPBELL_AI_SCHEMA_REFRESH_TIMEZONE", DEFAULT_TIMEZONE),
                backup_s3=_env_bool("CAMPBELL_AI_SCHEMA_BACKUP_S3", True),
                s3_prefix=_env_str("CAMPBELL_AI_SCHEMA_BACKUP_S3_PREFIX", DEFAULT_S3_PREFIX),
                data_s3_prefix=_env_str(
                    "CAMPBELL_AI_SCHEMA_DATA_S3_PREFIX", DEFAULT_DATA_S3_PREFIX
                ),
                aws_region=_env_str(
                    "CAMPBELL_AI_SCHEMA_BACKUP_AWS_REGION",
                    _env_str("AWS_DEFAULT_REGION", "us-east-1"),
                ),
                run_on_start=_env_bool("CAMPBELL_AI_SCHEMA_REFRESH_RUN_ON_START", False),
            )
        except Exception:  # noqa: BLE001 - a bad schedule must not stop the API from starting
            logger.warning(
                "Configuracion invalida del refresh de esquema; queda apagado", exc_info=True
            )
            return None
        _REFRESHER = refresher.start()
        return _REFRESHER


def get_schema_refresher() -> "SchemaRefresher | None":
    return _REFRESHER


def stop_schema_refresh() -> None:
    """Stop and forget the refresher, so a container stop is not waiting on it."""
    global _REFRESHER
    with _REFRESHER_LOCK:
        if _REFRESHER is not None:
            _REFRESHER.stop()
        _REFRESHER = None


def _install_signal_handlers() -> None:
    def stop(_signum: int, _frame: object) -> None:
        logger.info("Deteniendo refresh de schema")
        _STOP.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main(argv: list[str] | None = None) -> int:
    """Run a refresh by hand. The scheduled one lives in the API process, not here.

    `--once` is the useful mode: regenerate now, after a schema change, instead of waiting for
    the weekly window. Without it this blocks on the same `SchemaRefresher` the API runs, which
    is only worth doing to observe the schedule.
    """
    logging.basicConfig(
        level=os.getenv("CAMPBELL_AI_SCHEMA_REFRESH_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args(argv)

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

    # The same object the API starts, driven from the foreground. One scheduler, one place
    # where the weekday arithmetic and the failure handling live.
    _install_signal_handlers()
    refresher = SchemaRefresher(
        data_root=args.data_root,
        weekday=_parse_weekday(args.weekday),
        run_time=_parse_time(args.time),
        timezone=args.timezone,
        backup_s3=args.backup_s3,
        s3_prefix=args.s3_prefix,
        data_s3_prefix=args.data_s3_prefix,
        aws_region=args.aws_region,
        run_on_start=args.run_on_start,
    ).start()
    try:
        _STOP.wait()
    finally:
        refresher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
