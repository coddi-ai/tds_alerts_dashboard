"""Reportes > Reportabilidad: catalogo de S3, ruta de entrega del PDF y armado de la vista.

S3 se reemplaza por un cliente falso en memoria; ninguna prueba toca el bucket real.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import dash
import pytest

from config.users import USERS
from dashboard import report_files
from dashboard.callbacks import reporting_callbacks as rc
from src.data import report_health, report_store
from src.data.report_store import ReportStore, latest_by_unit, parse_report_key, unit_sort_key

PREFIX = "/alerts-dashboard/"
ROUTE = f"{PREFIX}reports/file"
PDF = b"%PDF-1.4 sintetico"

ADMIN = next(n for n, u in USERS.items() if u.get("role") == "admin")
CDA_USER = next(n for n, u in USERS.items() if u.get("role") == "client" and u.get("clients") == ["CDA"])
CAPSTONE_USER = next(n for n, u in USERS.items() if u.get("role") == "client" and u.get("clients") == ["CAPSTONE"])

KEYS = [
    "test_chatbot/cda/reports/2026-10-06/informe_predictivo_t_9_20261006.pdf",
    "test_chatbot/cda/reports/2026-10-06/informe_predictivo_t_10_transmision_20261006.pdf",
    "test_chatbot/cda/reports/2026-10-12/informe_predictivo_t_9_20261012.pdf",
    "test_chatbot/cda/reports/2026-10-12/informe_predictivo_t_10_20261012.pdf",
    "test_chatbot/cda/reports/2026-10-12/informe_predictivo_t_10_transmision_20261012.pdf",
    "test_chatbot/cda/reports/2026-10-12/notas.txt",
    "test_chatbot/capstone/reports/2026-09-07/informe_predictivo_ca-49_20260907.pdf",
    "test_chatbot/capstone/reports/2026-09-07/informe_predictivo_ca-49_20260907_01.pdf",
    "test_chatbot/capstone/reports/2026-09-07/informe_predictivo_ca-50_transmision_20260907.pdf",
]


class _Body:
    def __init__(self, data):
        self.data = data

    def iter_chunks(self, size):
        for i in range(0, len(self.data), size):
            yield self.data[i:i + size]


class _NoSuchKey(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    def __init__(self, keys):
        self.keys = list(keys)
        self.list_calls = 0
        self.requested = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        fake = self

        class _Paginator:
            def paginate(self, Bucket, Prefix):
                fake.list_calls += 1
                contents = [{"Key": k, "Size": 2048, "LastModified": datetime(2026, 10, 12, tzinfo=timezone.utc)}
                            for k in fake.keys if k.startswith(Prefix)]
                yield {"Contents": contents[:3]}
                yield {"Contents": contents[3:]}

        return _Paginator()

    def get_object(self, Bucket, Key):
        self.requested.append(Key)
        if Key not in self.keys:
            raise _NoSuchKey()
        return {"Body": _Body(PDF), "ContentLength": len(PDF)}


@pytest.fixture
def fake_s3(monkeypatch):
    s3 = FakeS3(KEYS)
    monkeypatch.setattr(report_store, "_store", ReportStore("bucket", s3, root="test_chatbot"))
    return s3


# ---------------------------------------------------------------------------
# Nombres de archivo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key, unit, system, version", [
    ("2026-10-06/informe_predictivo_t_10_20261006.pdf", "T_10", "motor", 0),
    ("2026-10-06/informe_predictivo_t_10_transmision_20261006.pdf", "T_10", "transmision", 0),
    ("2026-08-19/informe_predictivo_ca-30_20260819.pdf", "CA-30", "motor", 0),
    ("2026-09-07/informe_predictivo_ca-49_20260907_01.pdf", "CA-49", "motor", 1),
])
def test_nombres_reales_se_interpretan(key, unit, system, version):
    entry = parse_report_key(key)
    assert (entry.unit, entry.system, entry.version, entry.technique) == (unit, system, version, "predictivo")
    assert entry.date == key.split("/")[0]


@pytest.mark.parametrize("key", [
    "", "informe_predictivo_t_9_20261006.pdf", "../cda/reports/2026-10-06/informe_predictivo_t_9_20261006.pdf",
    "2026-10-06/../informe_predictivo_t_9_20261006.pdf", "2026-10-06/informe_predictivo_t_9_20261006.pdf.exe",
    "2026-10-06/otro_archivo.pdf", "hoy/informe_predictivo_t_9_20261006.pdf",
    "2026-10-06/informe_predictivo_../x_20261006.pdf",
])
def test_claves_ajenas_o_maliciosas_se_rechazan(key):
    assert parse_report_key(key) is None


def test_orden_natural_y_ultimo_por_unidad():
    assert sorted(["T_10", "T_9", "T_24"], key=unit_sort_key) == ["T_9", "T_10", "T_24"]
    entries = [parse_report_key(k.split("/reports/")[1]) for k in KEYS if k.endswith(".pdf")]
    latest = {(e.system, e.unit): (e.date, e.version) for e in latest_by_unit(entries)}
    assert latest[("motor", "T_9")] == ("2026-10-12", 0)
    assert latest[("motor", "CA-49")] == ("2026-09-07", 1)


# ---------------------------------------------------------------------------
# Listado y cache
# ---------------------------------------------------------------------------

def test_listado_por_cliente_ordenado_y_cacheado():
    s3 = FakeS3(KEYS)
    now = [0.0]
    store = ReportStore("bucket", s3, cache_seconds=60, clock=lambda: now[0])

    entries = store.list_reports("CDA")
    assert [e.date for e in entries] == sorted([e.date for e in entries], reverse=True)
    assert len(entries) == 5  # notas.txt queda fuera
    assert all(e.size == 2048 and e.last_modified for e in entries)
    assert store.list_reports("cda") is entries and s3.list_calls == 1

    now[0] = 61
    store.list_reports("CDA")
    store.list_reports("CDA", refresh=True)
    assert s3.list_calls == 3


def test_open_report_valida_y_queda_bajo_el_cliente():
    s3 = FakeS3(KEYS)
    store = ReportStore("bucket", s3)
    chunks, length = store.open_report("CDA", "2026-10-12/informe_predictivo_t_9_20261012.pdf")
    assert b"".join(chunks) == PDF and length == len(PDF)
    assert s3.requested == ["test_chatbot/cda/reports/2026-10-12/informe_predictivo_t_9_20261012.pdf"]
    with pytest.raises(ValueError):
        store.open_report("CDA", "../capstone/reports/x.pdf")
    with pytest.raises(report_store.ReportNotFound):
        store.open_report("CDA", "2026-01-01/informe_predictivo_t_9_20260101.pdf")


# ---------------------------------------------------------------------------
# Ruta de entrega
# ---------------------------------------------------------------------------

@pytest.fixture
def client(fake_s3):
    app = dash.Dash(__name__, url_base_pathname=PREFIX, suppress_callback_exceptions=True)
    app.layout = dash.html.Div()
    app.server.secret_key = "flask-secret-key-sintetica-0123456789"
    report_files.register_report_files(app)
    app.server.testing = True
    with app.server.test_client() as test_client:
        yield test_client


def _login(test_client, username):
    with test_client.session_transaction() as session:
        session["dashboard_user"] = username


def _get(test_client, client="CDA", key="2026-10-12/informe_predictivo_t_9_20261012.pdf", **extra):
    return test_client.get(ROUTE, query_string={"client": client, "key": key, **extra})


def test_sin_sesion_vuelve_al_inicio(client, fake_s3):
    response = _get(client)
    assert response.status_code == 302 and response.headers["Location"].endswith(PREFIX)
    assert fake_s3.requested == []


def test_entrega_el_pdf_sin_cache_ni_credenciales(client, fake_s3):
    _login(client, CDA_USER)
    response = _get(client)
    assert response.status_code == 200
    assert response.data == PDF
    assert response.mimetype == "application/pdf"
    assert response.headers["Content-Disposition"].startswith("inline;")
    assert "no-store" in response.headers["Cache-Control"]
    assert fake_s3.requested == ["test_chatbot/cda/reports/2026-10-12/informe_predictivo_t_9_20261012.pdf"]

    download = _get(client, download="1")
    assert download.headers["Content-Disposition"].startswith("attachment;")


def test_cliente_ajeno_al_usuario_403(client, fake_s3):
    _login(client, CDA_USER)
    response = _get(client, client="CAPSTONE", key="2026-09-07/informe_predictivo_ca-49_20260907.pdf")
    assert response.status_code == 403 and fake_s3.requested == []


def test_servicio_no_habilitado_403(client, fake_s3, monkeypatch):
    _login(client, ADMIN)
    monkeypatch.setattr(report_files, "is_service_enabled", lambda c, s: False)
    assert _get(client).status_code == 403 and fake_s3.requested == []


@pytest.mark.parametrize("key", ["../capstone/reports/2026-09-07/informe_predictivo_ca-49_20260907.pdf",
                                 "2026-10-12/notas.txt", ""])
def test_clave_invalida_400_sin_tocar_s3(client, fake_s3, key):
    _login(client, CDA_USER)
    assert _get(client, key=key).status_code == 400 and fake_s3.requested == []


def test_reporte_inexistente_404(client):
    _login(client, CDA_USER)
    assert _get(client, key="2026-01-01/informe_predictivo_t_9_20260101.pdf").status_code == 404


def test_sistema_no_habilitado_no_se_entrega(client, fake_s3, monkeypatch):
    _login(client, CDA_USER)
    monkeypatch.setattr(report_files, "is_service_enabled",
                        lambda c, s: s != "predictive-transmision")
    response = _get(client, key="2026-10-12/informe_predictivo_t_10_transmision_20261012.pdf")
    assert response.status_code == 404 and fake_s3.requested == []


# ---------------------------------------------------------------------------
# Vista
# ---------------------------------------------------------------------------

@pytest.fixture
def app_context():
    app = dash.Dash(__name__, url_base_pathname=PREFIX)
    with app.server.test_request_context("/"):
        yield


def test_catalogo_respeta_usuario_y_servicio(fake_s3, app_context, monkeypatch):
    monkeypatch.setattr(report_health, "HISTORY_LOADERS", {})
    records, notice = rc.load_catalog("CDA", ["CDA"])
    assert notice is None and len(records) == 5
    href = urlsplit(records[0]["href"])
    assert href.path == ROUTE
    assert parse_qs(href.query) == {"client": ["CDA"], "key": [records[0]["key"]]}
    assert "test_chatbot" not in records[0]["href"]

    records, notice = rc.load_catalog("CAPSTONE", ["CDA"])
    assert records == [] and notice is not None

    # Sin predictive-transmision, esos informes no se listan.
    monkeypatch.setattr(report_files, "is_service_enabled", lambda c, s: s != "predictive-transmision")
    records, _ = rc.load_catalog("CDA", ["CDA"])
    assert {r["system"] for r in records} == {"motor"}


def _records(client_folder):
    entries = [parse_report_key(k.split("/reports/")[1]) for k in KEYS
               if f"/{client_folder}/" in k and k.endswith(".pdf")]
    return [{**e.to_record(), "href": f"/x/{e.key}", "download_href": f"/d/{e.key}",
             "health": None, "health_date": None, "health_week": None} for e in entries]


def test_version_regenerada_reemplaza_a_la_original():
    kept = rc.keep_latest_versions(_records("capstone"))
    assert sorted(r["filename"] for r in kept) == [
        "informe_predictivo_ca-49_20260907_01.pdf",
        "informe_predictivo_ca-50_transmision_20260907.pdf",
    ]


def test_lote_colorea_por_estado_y_cuenta(app_context):
    records = rc.keep_latest_versions(_records("cda"))
    for r in records:
        r["health"] = "anormal" if r["unit"] == "T_9" else "normal"
    html_text = str(rc.build_batch(records, "2026-10-12"))
    assert "'type': 'reporting-open'" in html_text
    assert "1 Anormal" in html_text and "#fcebeb" in html_text  # paleta del Predictivo


def test_filtros_y_filas_de_tabla(app_context):
    records = _records("cda")
    records[0]["health"] = "alerta"
    assert len(rc.filter_records(records, "predictivo", None, None, None)) == 5
    assert {r["unit"] for r in rc.filter_records(records, None, "transmision", None, None)} == {"T_10"}
    assert len(rc.filter_records(records, None, None, ["T_9"], "2026-10-12")) == 1
    assert len(rc.filter_records(records, None, None, None, None, ["alerta"])) == 1
    assert len(rc.filter_records(records, None, None, None, None, [rc.NO_HEALTH])) == 4

    row = rc.table_rows(records)[0]
    assert set(row) == {"id", "date", "unit", "system", "health", "health_raw", "preview", "download"}
    assert (row["id"], row["health"], row["health_raw"]) == (records[0]["key"], "Alerta", "alerta")
    assert 'class="fas fa-eye"' in row["preview"] and "href" not in row["preview"]
    assert f'href="{records[0]["download_href"]}"' in row["download"] and "fa-download" in row["download"]


def test_previsualizacion_desde_boton_tabla_y_saltos(app_context):
    records = _records("cda")
    by = {(r["unit"], r["system"], r["date"]): r for r in records}
    t10_motor = by[("T_10", "motor", "2026-10-12")]

    assert rc.preview_target({"type": "reporting-open", "key": t10_motor["key"]}, records,
                             None, None, None, None) is t10_motor
    cell = {"row_id": t10_motor["key"], "column_id": "unit"}
    assert rc.preview_target("reporting-datatable", records, None, cell, None, None) is t10_motor
    # Clic en "Descargar": baja el archivo, no abre el modal.
    assert rc.preview_target("reporting-datatable", records, None,
                             {**cell, "column_id": "download"}, None, None) is None
    # Cambiar de sistema y de fecha sin salir de la unidad.
    assert rc.preview_target("reporting-preview-system", records, t10_motor["key"], None,
                             None, "transmision") is by[("T_10", "transmision", "2026-10-12")]
    assert rc.preview_target("reporting-preview-date", records, by[("T_10", "transmision", "2026-10-12")]["key"],
                             None, "2026-10-06", None) is by[("T_10", "transmision", "2026-10-06")]
    # T_10 no tiene motor el 2026-10-06 en este bucket de prueba.
    assert rc.preview_target("reporting-preview-date", records, t10_motor["key"], None,
                             "2026-10-06", None) is None


def test_pdf_solo_embebible_desde_el_dashboard(client):
    _login(client, CDA_USER)
    response = _get(client)
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in response.headers["Content-Security-Policy"]


def test_dentro_del_lote_motor_primero_y_unidades_en_orden_natural():
    store = ReportStore("bucket", FakeS3(KEYS))
    entries = store.list_reports("CDA")
    assert [(e.date, e.system, e.unit) for e in entries] == [
        ("2026-10-12", "motor", "T_9"),
        ("2026-10-12", "motor", "T_10"),
        ("2026-10-12", "transmision", "T_10"),
        ("2026-10-06", "motor", "T_9"),
        ("2026-10-06", "transmision", "T_10"),
    ]
