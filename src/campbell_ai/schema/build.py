"""Regenerate `dataset_columns.json` from the data on disk, and publish it.

Run by hand, or from the API-machine refresh process, when the ETL genuinely changes the
columns exposed by one of the dashboard datasets:

    python -m src.campbell_ai.schema.build

The output can be committed so a schema change arrives as a reviewable diff instead of as
behaviour that shifted under the service. Deliberately records only format and column names -
no sizes, no timestamps - so regenerating on unchanged data produces no diff at all, and any
diff that does appear is a real schema change.

**It also publishes to S3**, to two different places for two different reasons:

- `MultiTechnique Alerts/auxiliar/dataset_columns.json` - *inside the data prefix*, because
  `S3Downloader.download_folder` preserves structure, so this key lands at
  `data/auxiliar/dataset_columns.json`, which is exactly the copy the service prefers. The
  declaration therefore travels with the data it describes: a deployment that syncs the data
  gets the matching schema for free, with no bootstrap step and no window where the two
  disagree. One key, overwritten - no `latest/` or `history/` folders here, because the sync
  would mirror those into the data root as junk.
- `campbellAI/schema/dataset_columns/history/<timestamp>/…` - the dated record, kept outside
  the data prefix precisely so it is *not* mirrored.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import dotenv
dotenv.load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.campbell_ai.data import DATASETS, DashboardDataRepository  # noqa: E402
from src.campbell_ai.schema import SCHEMA_FILE  # noqa: E402

# Clients to declare. A client absent from the file simply falls back to reading headers, so
# omitting one degrades performance rather than correctness.
CLIENTS = ("cda", "capstone", "emin", "enex")

# Where the dashboard data lives in the bucket. The schema is published beside it, under the
# same prefix `S3Downloader` mirrors into `data/`.
DEFAULT_DATA_S3_PREFIX = "MultiTechnique Alerts/auxiliar"

# The dated copies. Outside the data prefix on purpose: anything under the prefix above is
# downloaded into the data root on every sync.
DEFAULT_HISTORY_S3_PREFIX = "campbellAI/schema/dataset_columns"

SCHEMA_OBJECT_NAME = "dataset_columns.json"

NOTE = (
    "Generado por `python -m src.campbell_ai.schema.build`. Columnas declaradas por cliente: "
    "cuatro de los once datasets traen columnas distintas segun el cliente, asi que una lista "
    "compartida seria incorrecta para alguno. Un cliente o dataset ausente aqui no es un error: "
    "se lee la cabecera como antes."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenera src/campbell_ai/schema/dataset_columns.json desde los datos."
    )
    parser.add_argument(
        "--data-root",
        default=os.getenv("CAMPBELL_AI_SCHEMA_DATA_ROOT")
        or os.getenv("CAMPBELL_AI_DATA_ROOT")
        or "data",
        help=(
            "Raiz de datos a inspeccionar. Tambien puede venir de "
            "CAMPBELL_AI_SCHEMA_DATA_ROOT o CAMPBELL_AI_DATA_ROOT."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Donde escribir el documento. Por defecto el archivo versionado del repositorio, "
            "que es el que se revisa y commitea; el refresh periodico usa esto para escribir "
            "en su lugar la copia generada dentro de la raiz de datos."
        ),
    )
    parser.add_argument(
        "--backup-s3",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Publica el documento en el bucket despues de escribirlo. Activo por defecto: es "
            "lo que hace que el esquema viaje con la data que describe."
        ),
    )
    parser.add_argument(
        "--data-s3-prefix",
        default=os.getenv("CAMPBELL_AI_SCHEMA_DATA_S3_PREFIX", DEFAULT_DATA_S3_PREFIX),
        help=(
            "Prefijo del bucket donde vive la data del dashboard. El documento se publica "
            "ahi, asi que la sincronizacion lo deja en la raiz de datos."
        ),
    )
    parser.add_argument(
        "--history-s3-prefix",
        default=os.getenv("CAMPBELL_AI_SCHEMA_BACKUP_S3_PREFIX", DEFAULT_HISTORY_S3_PREFIX),
        help="Prefijo, fuera de la data, donde se guardan las copias fechadas.",
    )
    parser.add_argument(
        "--aws-region",
        default=os.getenv("CAMPBELL_AI_SCHEMA_BACKUP_AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Publica aunque el documento nuevo declare menos clientes que el anterior. Usalo "
            "solo si esa perdida es real y no una raiz de datos a medio sincronizar."
        ),
    )
    return parser.parse_args(argv)


def build(data_root: str | Path = "data") -> dict:
    repository = DashboardDataRepository(data_root)
    clients: dict[str, dict] = {}
    for client in CLIENTS:
        datasets: dict[str, dict] = {}
        for spec in DATASETS:
            try:
                path = repository.dataset_path(spec.key, client)
            except Exception:
                continue
            if not path.exists():
                continue
            try:
                columns = repository.read_columns(path)
            except Exception as exc:  # noqa: BLE001 - report and skip, do not guess
                print(f"  ! {client}/{spec.key}: {type(exc).__name__}: {exc}")
                continue
            datasets[spec.key] = {
                "format": path.suffix.lstrip(".").lower(),
                "columns": columns,
            }
        if datasets:
            clients[client] = datasets
            total = sum(len(d["columns"]) for d in datasets.values())
            print(f"  {client:10s} {len(datasets):2d} datasets, {total:4d} columnas")
    return {"note": NOTE, "clients": clients}


def _normalize_prefix(value: str, fallback: str) -> str:
    raw = value.replace("\\", "/").strip().strip("/")
    return raw or fallback


def backup_to_s3(
    schema_file: Path,
    *,
    data_prefix: str = DEFAULT_DATA_S3_PREFIX,
    history_prefix: str = DEFAULT_HISTORY_S3_PREFIX,
    region: str = "us-east-1",
    history: bool = True,
) -> list[str]:
    """Publish the document to the bucket. Returns the keys written, empty if it did not run.

    Missing credentials are a skip, not a failure: regenerating the file locally is useful on
    its own, and a developer without the deployment's keys should still be able to run this.
    """
    bucket = os.getenv("BUCKET_NAME", "").strip()
    if not bucket:
        print("  ! BUCKET_NAME no esta configurado; se omite el respaldo en S3")
        return []

    import boto3
    from botocore.config import Config

    access_key = os.getenv("ACCESS_KEY", "").strip() or None
    secret_key = os.getenv("SECRET_KEY", "").strip() or None
    config = Config(retries={"max_attempts": 3, "mode": "standard"})
    if access_key and secret_key:
        client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=config,
        )
    else:
        client = boto3.client("s3", region_name=region, config=config)

    keys = [f"{_normalize_prefix(data_prefix, DEFAULT_DATA_S3_PREFIX)}/{SCHEMA_OBJECT_NAME}"]
    if history:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = _normalize_prefix(history_prefix, DEFAULT_HISTORY_S3_PREFIX)
        keys.append(f"{base}/history/{stamp}/{SCHEMA_OBJECT_NAME}")

    body = schema_file.read_bytes()
    metadata = {
        "source": "campbell-ai-schema-build",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    written: list[str] = []
    for key in keys:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/json; charset=utf-8",
            Metadata=metadata,
        )
        print(f"  respaldado en s3://{bucket}/{key}")
        written.append(key)
    return written


def publishing_would_shrink(document: dict, previous: Path) -> list[str]:
    """Clients the previous document declared and this one does not.

    The guard exists because publishing reaches every deployment. Building against a data root
    that only partly synced produces a perfectly valid document that silently withdraws the
    analyses of whoever is missing, and the local write alone would never reveal it. Comparing
    against the document being replaced turns that into a refusal instead of a rollout.
    """
    try:
        before = json.loads(previous.read_text(encoding="utf-8")).get("clients", {})
    except Exception:  # noqa: BLE001 - no previous document is not a regression
        return []
    if not isinstance(before, dict):
        return []
    return sorted(set(before) - set(document.get("clients", {})))


def write_document(document: dict, schema_file: Path = SCHEMA_FILE) -> None:
    # Written beside the target and renamed over it: a reader that opens the file while this
    # runs gets either the old document or the new one, never half of one. The service reads
    # this file from another container, so a partial write would be a real failure mode.
    schema_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = schema_file.with_name(f"{schema_file.name}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    temporary.replace(schema_file)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = Path(args.output).expanduser() if args.output else SCHEMA_FILE
    print(f"Leyendo cabeceras reales para regenerar {target.name}")
    print(f"Raiz de datos: {Path(args.data_root).expanduser()}")
    document = build(args.data_root)
    if not document["clients"]:
        print("Sin datos legibles: no se escribe nada.")
        return 1

    # Checked before writing, so the refusal names the document that is still in place.
    perdidos = publishing_would_shrink(document, target)

    write_document(document, target)
    print(f"Escrito {target}")

    if not args.backup_s3:
        return 0
    if perdidos and not args.force:
        print(
            "  ! No se publica en S3: el documento nuevo no declara "
            f"{', '.join(perdidos)}, que el anterior si declaraba."
        )
        print("    Revisa que la raiz de datos este completa, o repite con --force.")
        return 1
    backup_to_s3(
        target,
        data_prefix=args.data_s3_prefix,
        history_prefix=args.history_s3_prefix,
        region=args.aws_region,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
