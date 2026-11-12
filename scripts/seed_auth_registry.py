"""Upload the initial reference registry (config/auth_registry/*.json) to the auth store.

    python scripts/seed_auth_registry.py            # refuses to overwrite existing files
    python scripts/seed_auth_registry.py --overwrite

The registry is maintained by hand afterwards (edit the JSON and upload it again).
Storage comes from BUCKET_NAME / ACCESS_KEY / SECRET_KEY (S3) or AUTH_EVENTS_LOCAL_DIR.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.auth_events import settings  # noqa: E402
from src.auth_events.registry import parse_registry  # noqa: E402
from src.auth_events.storage import ObjectNotFound, get_storage  # noqa: E402

SEED_DIR = ROOT / "config" / "auth_registry"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--overwrite", action="store_true", help="replace files that already exist")
    args = parser.parse_args(argv)

    storage = get_storage()
    if storage is None:
        print("No storage configured (set BUCKET_NAME or AUTH_EVENTS_LOCAL_DIR).", file=sys.stderr)
        return 2

    files = {
        settings.REGISTRY_CLIENTS_KEY: (SEED_DIR / "clients.json").read_bytes(),
        settings.REGISTRY_USERS_KEY: (SEED_DIR / "users.json").read_bytes(),
    }
    parse_registry(files[settings.REGISTRY_CLIENTS_KEY], files[settings.REGISTRY_USERS_KEY])  # validate first

    for key, body in files.items():
        try:
            storage.get(key)
            if not args.overwrite:
                print(f"{key} already exists; left untouched (use --overwrite to replace it).")
                continue
        except ObjectNotFound:
            pass
        storage.put(key, body, "application/json")
        print(f"uploaded {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
