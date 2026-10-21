"""Offline translation script (scripts/translate_text_fields.py).

Everything runs against a tiny synthetic data tree with a fake LLM and a fake S3 client: no network,
no OpenAI key. The guarantees under test are the ones the work was specified with - demo mode
translates 20 rows per file and never touches S3, full mode replaces existing S3 keys, original
columns come out unchanged, and a bad translation is retried and then left blank.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("translate_text_fields", ROOT / "scripts" / "translate_text_fields.py")
tt = importlib.util.module_from_spec(_spec)
sys.modules["translate_text_fields"] = tt
_spec.loader.exec_module(tt)

N_ROWS = 30
N_OLD = 5  # the first rows are two years old: outside the default one-year window
N_RECENT = N_ROWS - N_OLD
NOW = pd.Timestamp.now(tz="UTC").tz_localize(None)
RECENT, OLD = NOW - pd.Timedelta(days=10), NOW - pd.Timedelta(days=730)


def fake_llm(system, text):
    """Pretend translation that keeps labels, identifiers and structure."""
    return "EN: " + text, 10, 5


@pytest.fixture(autouse=True)
def _no_env_file(monkeypatch):
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / "data"
    # Oil (parquet, one client)
    oil = root / "oil" / "golden" / "cda"
    oil.mkdir(parents=True)
    pd.DataFrame({
        "unitId": [f"T_{i}" for i in range(N_ROWS)],
        "severity_score": list(range(N_ROWS)),
        "sampleDate": [OLD if i < N_OLD else RECENT for i in range(N_ROWS)],
        "ai_recommendation": [f"Diagnóstico: Desgaste {i}.\nAcción: Cambiar aceite en T_{i}." for i in range(N_ROWS)],
    }).to_parquet(oil / "classified.parquet", index=False, compression="zstd")
    # Alerts (CSV with BOM + CRLF, like the Capstone export; embedded newlines inside the message)
    alerts = root / "alerts" / "golden" / "capstone"
    alerts.mkdir(parents=True)
    frame = pd.DataFrame({
        "FusionID": [f"f{i}" for i in range(N_ROWS)],
        "Timestamp": [((OLD if i < N_OLD else RECENT).strftime("%Y-%m-%dT%H:%M:%S") + "-04:00") for i in range(N_ROWS)],
        "mensaje_ia": [f"DIAGNÓSTICO: Falla {i}.\nCAUSA PROBABLE: Desgaste.\nACCIONES RECOMENDADAS: Revisar." for i in range(N_ROWS)],
        "nota": [""] * N_ROWS,
    })
    frame.to_csv(alerts / "consolidated_alerts.csv", index=False, encoding="utf-8-sig", lineterminator="\r\n")
    # Predictive: two weekly partitions, only the newest one is read by the dashboard
    for week in (41, 42):
        part = root / "predictive" / "golden" / "capstone" / "motor" / "unit_failure_analisis" / "year=2026" / f"week={week}"
        part.mkdir(parents=True)
        pd.DataFrame({
            "Unit": ["CA-1", "CA-2"],
            "Fecha": [RECENT, RECENT],
            "diagnostico": ["Turbo en monitoreo.", None],
            "causa_probable": ["Restricción de admisión.", None],
            "acciones": ['["Inmediato: revisar filtros.", "Próximo PM: tomar muestras."]', None],
            "modos_ordenados": ['{"turbocharger_risk": 0.9}', None],
        }).to_parquet(part / "unit_failure_analisis.parquet", index=False)
    return root


def run(data_root, *extra, llm=fake_llm):
    out = data_root.parent / "out"
    code = tt.main(["--data-root", str(data_root), "--output-dir", str(out), *extra], llm=llm)
    return code, out


# ── Mapping / discovery ─────────────────────────────────────────────────────────

def test_discovery_expands_the_mapping_and_reads_only_the_latest_partition(data_root):
    jobs = tt.discover_jobs(data_root, tt.load_mapping())
    assert sorted(j.rel_path for j in jobs) == [
        "alerts/golden/capstone/consolidated_alerts.csv",
        "oil/golden/cda/classified.parquet",
        "predictive/golden/capstone/motor/unit_failure_analisis/year=2026/week=42/unit_failure_analisis.parquet",
    ]
    assert {j.client for j in tt.discover_jobs(data_root, tt.load_mapping(), clients=["CDA"])} == {"cda"}
    assert {j.target_id for j in tt.discover_jobs(data_root, tt.load_mapping(), targets=["alerts_consolidated"])} == {
        "alerts_consolidated"}


def test_mapping_columns_are_the_ones_the_dashboard_reads():
    mapping = {t["id"]: t["columns"] for t in tt.load_mapping()["targets"]}
    assert mapping["oil_classified"] == ["ai_recommendation"]
    assert mapping["oil_machine_status"] == ["machine_ai_recommendation"]
    assert mapping["alerts_consolidated"] == ["mensaje_ia"]
    assert mapping["predictive_unit_failure_analisis"] == ["diagnostico", "causa_probable", "acciones"]
    assert mapping["predictive_mode_failure_analisis"] == ["diagnostico", "probable_cause", "recommended_actions"]
    assert mapping["telemetry_ai_unit_comments"] == ["description", "explaining", "recommended_action"]
    assert mapping["telemetry_ai_system_comments"] == ["description", "explaining", "recommended_action"]
    assert mapping["telemetry_ai_signal_comments"] == ["description", "explaining"]


# ── Demo mode ───────────────────────────────────────────────────────────────────

def test_demo_translates_20_rows_per_file_and_never_touches_s3(data_root, monkeypatch):
    import boto3

    def forbidden(*a, **k):
        raise AssertionError("demo mode must not create an S3 client")

    monkeypatch.setattr(boto3, "client", forbidden)
    monkeypatch.setattr(tt, "upload_results", forbidden)
    code, out = run(data_root, "--demo")
    assert code == 0

    oil = pd.read_parquet(out / "demo" / "oil" / "golden" / "cda" / "classified.parquet")
    assert oil["ai_recommendation_eng"].notna().sum() == 20
    assert len(oil) == N_ROWS
    csv = pd.read_csv(out / "demo" / "alerts" / "golden" / "capstone" / "consolidated_alerts.csv",
                      dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert (csv["mensaje_ia_eng"] != "").sum() == 20 and len(csv) == N_ROWS
    report = json.loads((out / "demo" / "report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "demo" and report["uploads"] == []
    assert (out / "demo" / "demo_review.csv").exists()
    # the source data is untouched
    assert "ai_recommendation_eng" not in pd.read_parquet(data_root / "oil" / "golden" / "cda" / "classified.parquet")


def test_demo_sample_is_reproducible_and_a_subset(data_root):
    _, out_a = run(data_root, "--demo", "--seed", "3")
    first = pd.read_parquet(out_a / "demo" / "oil" / "golden" / "cda" / "classified.parquet")["ai_recommendation_eng"].notna()
    _, out_b = run(data_root, "--demo", "--seed", "3")
    second = pd.read_parquet(out_b / "demo" / "oil" / "golden" / "cda" / "classified.parquet")["ai_recommendation_eng"].notna()
    assert first.tolist() == second.tolist()


def test_files_without_enough_rows_are_translated_whole_in_demo(data_root):
    _, out = run(data_root, "--demo")
    pred = pd.read_parquet(out / "demo" / "predictive" / "golden" / "capstone" / "motor" / "unit_failure_analisis"
                           / "year=2026" / "week=42" / "unit_failure_analisis.parquet")
    assert pred["diagnostico_eng"].iloc[0] == "EN: Turbo en monitoreo." and pred["diagnostico_eng"].isna().iloc[1]


# ── Output fidelity ─────────────────────────────────────────────────────────────

def test_original_columns_and_file_format_are_preserved(data_root):
    _, out = run(data_root, "--demo")
    src_csv = data_root / "alerts" / "golden" / "capstone" / "consolidated_alerts.csv"
    new_csv = out / "demo" / "alerts" / "golden" / "capstone" / "consolidated_alerts.csv"
    raw = new_csv.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw  # BOM and CRLF kept
    a = pd.read_csv(src_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    b = pd.read_csv(new_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert b[list(a.columns)].equals(a) and list(b.columns) == list(a.columns) + ["mensaje_ia_eng"]

    src_pq = data_root / "oil" / "golden" / "cda" / "classified.parquet"
    new_pq = out / "demo" / "oil" / "golden" / "cda" / "classified.parquet"
    assert pq.read_schema(new_pq).field("severity_score").type == pq.read_schema(src_pq).field("severity_score").type
    assert pq.ParquetFile(new_pq).metadata.row_group(0).column(0).compression == "ZSTD"
    assert pd.read_parquet(new_pq)[["unitId", "severity_score", "sampleDate", "ai_recommendation"]].equals(pd.read_parquet(src_pq))


def test_json_columns_stay_valid_json_with_translated_items(data_root):
    _, out = run(data_root, "--demo")
    pred = pd.read_parquet(out / "demo" / "predictive" / "golden" / "capstone" / "motor" / "unit_failure_analisis"
                           / "year=2026" / "week=42" / "unit_failure_analisis.parquet")
    assert json.loads(pred["acciones_eng"].iloc[0]) == [
        "EN: Inmediato: revisar filtros.", "EN: Próximo PM: tomar muestras."]
    assert pred["acciones"].iloc[0].startswith('["Inmediato')  # Spanish untouched


def test_rows_outside_the_run_keep_an_existing_translation(data_root):
    run(data_root, "--in-place", "--no-upload", "--all-dates")  # first: translate everything locally, no upload
    path = data_root / "oil" / "golden" / "cda" / "classified.parquet"
    before = pd.read_parquet(path)["ai_recommendation_eng"].tolist()
    assert all(v and v.startswith("EN: ") for v in before)
    _, out = run(data_root, "--demo")
    after = pd.read_parquet(out / "demo" / "oil" / "golden" / "cda" / "classified.parquet")["ai_recommendation_eng"].tolist()
    assert after == before


# ── Date window ─────────────────────────────────────────────────────────────────

def _eng_flags(data_root, out_dir=None):
    path = (out_dir or data_root) / "oil" / "golden" / "cda" / "classified.parquet"
    return pd.read_parquet(path)["ai_recommendation_eng"].notna().tolist()


def test_only_rows_from_the_last_year_are_translated_by_default(data_root):
    _, out = run(data_root, "--in-place", "--no-upload")
    assert _eng_flags(data_root) == [False] * N_OLD + [True] * N_RECENT
    csv = pd.read_csv(data_root / "alerts" / "golden" / "capstone" / "consolidated_alerts.csv",
                      dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert (csv["mensaje_ia_eng"] != "").tolist() == [False] * N_OLD + [True] * N_RECENT
    report = json.loads((out / "full" / "report.json").read_text(encoding="utf-8"))
    assert report["rows_dated_since"] == str((pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365)).date())


def test_all_dates_translates_old_rows_too(data_root):
    run(data_root, "--in-place", "--no-upload", "--all-dates")
    assert all(_eng_flags(data_root))


def test_since_days_sets_the_window(data_root):
    run(data_root, "--in-place", "--no-upload", "--since-days", "5")
    assert "ai_recommendation_eng" not in pd.read_parquet(data_root / "oil" / "golden" / "cda" / "classified.parquet")
    run(data_root, "--in-place", "--no-upload", "--since-days", "800")
    assert all(_eng_flags(data_root))


def test_demo_samples_only_rows_inside_the_window(data_root):
    for seed in range(5):
        _, out = run(data_root, "--demo", "--demo-rows", "8", "--seed", str(seed))
        flags = _eng_flags(data_root, out / "demo")
        assert sum(flags) == 8 and not any(flags[:N_OLD])


# ── Validation, retries, cache ──────────────────────────────────────────────────

@pytest.mark.parametrize("source,result,fragment", [
    ("DIAGNÓSTICO: falla.\nCAUSA PROBABLE: x.", "DIAGNOSIS: failure.\nCAUSA PROBABLE: x.", "labels"),
    ("Revisar la unidad T_11 hoy.", "Check the unit today.", "identifiers"),
    ("Revisar EngCoolTemp en la unidad con falla.", "Check engine coolant temperature on the faulty unit.", "identifiers"),
    ("Texto", "", "empty"),
    ("Sin mecanismo de deterioro identificado. No se requiere hipotesis tecnica.",
     "Sin mecanismo de deterioro identificado. No se requiere hipotesis tecnica.", "unchanged"),
    ("Un texto bastante largo que debe conservar su tamaño aproximado al traducirse.", "Ok", "length"),
])
def test_validation_rejects_bad_translations(source, result, fragment):
    assert fragment in tt.validate_translation(source, result)


def test_labels_are_masked_for_the_model_and_restored_exactly():
    text = "DIAGNÓSTICO DIRECTO:\nFalla en T_11.\n\nCAUSA PROBABLE :  Desgaste.\nAcción: Revisar."
    masked, labels = tt.mask_labels(text)
    assert "DIAGN" not in masked and "[[1]]" in masked and "[[3]]" in masked
    assert tt.unmask_labels(masked, labels) == text


def test_the_model_never_sees_the_labels(data_root):
    seen = []

    def spy(system, text):
        seen.append(text)
        return fake_llm(system, text)

    run(data_root, "--demo", llm=spy)
    assert seen and not any("DIAGN" in t or "ACCIONES" in t or "Acción:" in t for t in seen)


def test_validation_accepts_a_faithful_translation():
    src = "Diagnóstico: Revisar T_11 (EngCoolTemp 1,0 ppm).\nAcción: Cambiar aceite."
    assert tt.validate_translation(src, "Diagnóstico: Check T_11 (EngCoolTemp 1.0 ppm).\nAcción: Change the oil.") is None


def test_a_rejected_translation_is_retried_and_then_left_blank(data_root):
    calls = {"n": 0}

    def flaky(system, text):
        calls["n"] += 1
        if "Falla 7." in text:  # never acceptable: drops the section labels
            return "DIAGNOSIS: Failure 0.\nPROBABLE CAUSE: Wear.\nRECOMMENDED ACTIONS: Inspect.", 1, 1
        return fake_llm(system, text)

    code, out = run(data_root, "--in-place", "--no-upload", llm=flaky)
    assert code == 1  # failures are reported through the exit code
    csv = pd.read_csv(data_root / "alerts" / "golden" / "capstone" / "consolidated_alerts.csv",
                      dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert csv.loc[7, "mensaje_ia_eng"] == "" and csv.loc[8, "mensaje_ia_eng"].startswith("EN: ")
    report = json.loads((out / "full" / "report.json").read_text(encoding="utf-8"))
    assert len(report["failures"]) == 1 and "labels" in report["failures"][0]["reason"]


def test_second_run_is_served_from_the_cache(data_root):
    calls = {"n": 0}

    def counting(system, text):
        calls["n"] += 1
        return fake_llm(system, text)

    run(data_root, "--demo", llm=counting)
    first = calls["n"]
    assert first > 0
    run(data_root, "--demo", llm=counting)
    assert calls["n"] == first


# ── Full mode and S3 ────────────────────────────────────────────────────────────

class FakeS3:
    """In-memory bucket: get_object returns body + ETag, put_object honours IfMatch."""

    def __init__(self, objects):
        self.objects = objects  # key -> {"body": bytes, "etag": str, "type": str}
        self.puts = []
        self.gets = []
        self.after_get = None  # hook: simulate the pipeline publishing while we translate

    def get_object(self, Bucket, Key):
        from botocore.exceptions import ClientError

        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "nf"}}, "GetObject")
        self.gets.append(Key)
        obj = dict(self.objects[Key])
        if self.after_get:
            self.after_get(self, Key)

        class Body:
            def iter_chunks(self_inner):
                yield obj["body"]

        return {"Body": Body(), "ETag": obj["etag"], "ContentType": obj["type"]}

    def put_object(self, Bucket, Key, Body, IfMatch=None, ContentType=None):
        from botocore.exceptions import ClientError

        if IfMatch is not None and self.objects[Key]["etag"] != IfMatch:
            raise ClientError({"Error": {"Code": "PreconditionFailed", "Message": "412"}}, "PutObject")
        self.puts.append((Key, Body.read(), ContentType))
        self.objects[Key] = {"body": self.puts[-1][1], "etag": "new-" + str(len(self.puts)), "type": ContentType}


PREFIX = "MultiTechnique Alerts/"
OIL_KEY = PREFIX + "oil/golden/cda/classified.parquet"
ALERTS_KEY = PREFIX + "alerts/golden/capstone/consolidated_alerts.csv"
PRED_KEY = (PREFIX + "predictive/golden/capstone/motor/unit_failure_analisis/year=2026/week=42/"
            "unit_failure_analisis.parquet")


def _published_oil_with_one_more_row(data_root):
    """The S3 version of the oil file: the pipeline has added a row since `data/` was synced."""
    import io

    frame = pd.read_parquet(data_root / "oil" / "golden" / "cda" / "classified.parquet")
    extra = frame.iloc[[-1]].copy()
    extra["unitId"], extra["ai_recommendation"] = "T_NEW", "Diagnóstico: Nuevo.\nAcción: Revisar T_NEW."
    buffer = io.BytesIO()
    pd.concat([frame, extra], ignore_index=True).to_parquet(buffer, index=False)
    return buffer.getvalue()


@pytest.fixture
def fake_s3(monkeypatch, data_root):
    import boto3

    monkeypatch.setenv("BUCKET_NAME", "bkt")
    monkeypatch.setenv("ACCESS_KEY", "a")
    monkeypatch.setenv("SECRET_KEY", "b")
    alerts = (data_root / "alerts" / "golden" / "capstone" / "consolidated_alerts.csv").read_bytes()
    s3 = FakeS3({
        OIL_KEY: {"body": _published_oil_with_one_more_row(data_root), "etag": "oil-1", "type": "application/octet-stream"},
        ALERTS_KEY: {"body": alerts, "etag": "alerts-1", "type": "text/csv"},
        # the predictive key does not exist in the bucket
    })
    monkeypatch.setattr(boto3, "client", lambda *a, **k: s3)
    return s3


def test_full_mode_translates_the_current_s3_file_and_replaces_it(data_root, fake_s3):
    code, out = run(data_root, "--yes")
    puts = {key: (body, ctype) for key, body, ctype in fake_s3.puts}
    assert set(puts) == {OIL_KEY, ALERTS_KEY}  # existing keys only
    assert puts[ALERTS_KEY][1] == "text/csv"  # content type kept

    import io

    uploaded = pd.read_parquet(io.BytesIO(puts[OIL_KEY][0]))
    assert "T_NEW" in uploaded["unitId"].tolist()  # translated what S3 holds, not the stale local copy
    assert uploaded["ai_recommendation_eng"].notna().sum() == N_RECENT + 1

    outcomes = {o["key"]: o["result"]
                for o in json.loads((out / "full" / "report.json").read_text(encoding="utf-8"))["uploads"]}
    assert outcomes[OIL_KEY] == outcomes[ALERTS_KEY] == "uploaded"
    assert "no object" in outcomes[PRED_KEY]
    assert code == 1  # a skipped file must not look like success


def test_a_version_published_while_translating_is_not_overwritten(data_root, fake_s3):
    def publish(s3, key):
        if key == OIL_KEY:
            s3.objects[OIL_KEY] = {**s3.objects[OIL_KEY], "etag": "oil-2"}

    fake_s3.after_get = publish
    code, out = run(data_root, "--yes")
    assert OIL_KEY not in [k for k, _, _ in fake_s3.puts]
    outcomes = {o["key"]: o["result"]
                for o in json.loads((out / "full" / "report.json").read_text(encoding="utf-8"))["uploads"]}
    assert "changed while translating" in outcomes[OIL_KEY]
    assert code == 1


def test_force_overwrites_even_if_s3_changed_meanwhile(data_root, fake_s3):
    fake_s3.after_get = lambda s3, key: s3.objects[OIL_KEY].update(etag="oil-2") if key == OIL_KEY else None
    run(data_root, "--yes", "--force")
    assert OIL_KEY in [k for k, _, _ in fake_s3.puts]


def test_full_mode_can_skip_the_upload(data_root, fake_s3):
    code, _ = run(data_root, "--yes", "--no-upload")
    assert fake_s3.puts == [] and fake_s3.gets == [] and code == 0  # no S3 traffic at all


def test_full_run_asks_for_confirmation_before_replacing_s3(data_root, fake_s3, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    code, _ = run(data_root)
    assert code == 2 and fake_s3.puts == [] and fake_s3.gets == []
