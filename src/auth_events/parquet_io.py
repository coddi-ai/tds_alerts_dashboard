"""Daily parquet files: one fixed schema, deterministic bytes (same rows -> same file)."""

import io
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from src.auth_events.events import EVENT_COLUMNS, parse_timestamp

SCHEMA = pa.schema([
    ("schema_version", pa.int64()),
    ("event_id", pa.string()),
    ("event_type", pa.string()),
    ("timestamp_utc", pa.timestamp("ms", tz="UTC")),
    ("username", pa.string()),
    ("user_type", pa.string()),
    ("client_id", pa.string()),
    ("environment", pa.string()),
    ("source", pa.string()),
])


def sort_key(event: dict):
    return (event["timestamp_utc"], event["event_id"])


def events_to_parquet_bytes(events: list[dict]) -> bytes:
    """Events (already validated, timestamp_utc as ISO string) -> parquet, sorted by time."""
    ordered = sorted(events, key=sort_key)
    columns = {}
    for name in EVENT_COLUMNS:
        if name == "timestamp_utc":
            columns[name] = [parse_timestamp(e[name]).astimezone(timezone.utc) for e in ordered]
        else:
            columns[name] = [e[name] for e in ordered]
    table = pa.table(columns, schema=SCHEMA)
    sink = io.BytesIO()
    pq.write_table(table, sink, compression="snappy", write_statistics=False, use_dictionary=False)
    return sink.getvalue()


def parquet_bytes_to_events(data: bytes) -> list[dict]:
    """Parquet -> events with `timestamp_utc` back to the ISO-8601 string form."""
    table = pq.read_table(io.BytesIO(data))
    rows = table.to_pylist()
    events = []
    for row in rows:
        moment: datetime = row["timestamp_utc"]
        row["timestamp_utc"] = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
        events.append({name: row.get(name) for name in EVENT_COLUMNS})
    return events
