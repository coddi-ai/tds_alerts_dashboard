"""Build the golden layer of the General tab (Resumen de Flota), one file per client.

    data/{alerts,telemetry,oil,predictive,...}/golden/{client}/...   (read)
 -> data/general/golden/{client}/fleet_status.parquet                (written, one row per unit)

This is the only code that reads the raw sources of that view and the only code that decides its states
(see ``src/data/fleet_status.py`` for what a run does: each technique's Estado, "no alerts" = Normal, the
merge of ``CT-184`` / ``CT_184``, the unit's overall Estado). The dashboard just reads the file.

Each client is built on its own. A client whose build fails keeps the file of its last successful run -
the file is written beside the target, checked, and swapped in with one atomic replace, so a failed run
never leaves a partial or empty file - and the others are not held back by it.

Exit status: 0 every client built (or had nothing to show), 1 at least one client failed.

The app runs this every day at 10:30 America/Santiago (``src/data/partition_scheduler.py``, 30 minutes after
the 10:00 source update; ``FLEET_STATUS_TIME`` / ``FLEET_STATUS_SCHEDULER_ENABLED``) and once at start-up for
any client that has no file yet (``--only-missing``): the data folder is mirrored from S3 on every start, which
removes files S3 does not have, so a freshly deployed container starts without them. By hand:

    python scripts/build_fleet_status.py                  # every client
    python scripts/build_fleet_status.py --client capstone
    python scripts/build_fleet_status.py --only-missing

Environment: ``DASHBOARD_DATA_ROOT`` (data root).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

logger = logging.getLogger("build_fleet_status")


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(REPOSITORY_ROOT / ".env")
    except ImportError:
        pass


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--client", dest="clients", action="append", metavar="CLIENT",
                        help="build only this client (repeatable); default: every known client")
    parser.add_argument("--only-missing", action="store_true",
                        help="build only the clients that have no file yet (start-up catch-up)")
    return parser.parse_args(argv)


def run(clients=None, only_missing: bool = False, root=None) -> int:
    """Build every client in `clients` (default: all the known ones). Returns the exit status."""
    from config.settings import get_settings
    from src.data import fleet_status

    names = [c.lower() for c in (clients or get_settings().clients)]
    if only_missing:
        names = fleet_status.missing_clients(names, root)
        if not names:
            logger.info("Every client already has its fleet status file: nothing to do")
            return 0

    failed = []
    for client in names:
        started = time.monotonic()
        try:
            path = fleet_status.refresh_client(client, root)
        except Exception:  # noqa: BLE001 - one client's failure must not stop the others, nor touch its old file
            logger.exception("ERROR %s: the fleet status could not be built; the previous file (if any) stays", client)
            failed.append(client)
            continue
        if path is None:
            logger.info("%s: no technique to show, nothing written", client)
        else:
            logger.info("%s: fleet status written to %s in %.1fs", client, path, time.monotonic() - started)

    if failed:
        logger.error("ERROR fleet status failed for: %s", ", ".join(failed))
        return 1
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=os.getenv("FLEET_STATUS_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _load_env()
    args = parse_args(argv)
    return run(args.clients, args.only_missing)


if __name__ == "__main__":
    raise SystemExit(main())
