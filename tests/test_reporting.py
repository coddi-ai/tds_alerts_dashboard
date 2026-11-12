"""Reportes > Reportabilidad: catalogo de S3, ruta de entrega del PDF y armado de la vista.

S3 se reemplaza por un cliente falso en memoria; ninguna prueba toca el bucket real.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import dash
import pandas as pd
import pytest

from config.users import USERS
from dashboard import report_files
from dashboard.callbacks import reporting_callbacks as rc
from dashboard.components import report_states as rs
from dashboard.components import reporting_views as views
from src.data import report_health, report_store
from src.data import report_view as rv
from dashboard.components import status_chip
from src.status_scale import SCALE, get_status
from src.data.report_store import ReportStore, latest_by_unit, parse_report_key, unit_sort_key

ROOT = Path(__file__).resolve().parent.parent
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


# ---------------------------------------------------------------------------
# Vista: catalogo
# ---------------------------------------------------------------------------

@pytest.fixture
def app_context():
    app = dash.Dash(__name__, url_base_pathname=PREFIX)
    with app.server.test_request_context("/"):
        yield


def test_catalogo_respeta_usuario_y_servicio(fake_s3, app_context, monkeypatch):
    monkeypatch.setattr(report_health, "HISTORY_LOADERS", {})
    monkeypatch.setattr(report_health, "CURVE_LOADERS", {})
    records, notice = rc.load_catalog("CDA", ["CDA"])
    assert notice is None and len(records) == 5
    assert all(r["health"] == "sin_datos" for r in records)
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


def test_version_regenerada_reemplaza_a_la_original():
    entries = [parse_report_key(k.split("/reports/")[1]) for k in KEYS
               if "/capstone/" in k and k.endswith(".pdf")]
    records = [{**e.to_record(), "health": None} for e in entries]
    kept = rc.keep_latest_versions(records)
    assert sorted(r["filename"] for r in kept) == [
        "informe_predictivo_ca-49_20260907_01.pdf",
        "informe_predictivo_ca-50_transmision_20260907.pdf",
    ]


# ---------------------------------------------------------------------------
# Estado combinado
# ---------------------------------------------------------------------------

def _frame(rows, columns):
    return pd.DataFrame(rows, columns=columns)


def _attach(records, analysis=(), curve=()):
    """attach_health con historiales en memoria: analysis=[(unidad, fecha, estado)], igual curve."""
    analysis_df = _frame([(u, pd.Timestamp(d), e, 2026, 44) for u, d, e in analysis],
                         ["Unit", "Fecha", "estado", "year", "week"])
    curve_df = _frame([(u, pd.Timestamp(d), e) for u, d, e in curve], ["Unit", "Fecha", "estado"])
    return report_health.attach_health(
        records, "CAPSTONE",
        loaders={"predictivo": lambda c, s: analysis_df},
        curve_loaders={"predictivo": lambda c, s: curve_df},
    )


def _rec(unit, date="2026-11-04", system="motor", health=None, analysis=None, curve=None):
    suffix = "_transmision" if system == "transmision" else ""
    key = f"{date}/informe_predictivo_{unit.lower()}{suffix}_{date.replace('-', '')}.pdf"
    return {"key": key, "filename": key.split("/")[1], "technique": "predictivo", "system": system, "unit": unit,
            "date": date, "version": 0, "health": health, "health_analysis": analysis, "health_curve": curve,
            "health_analysis_date": None, "health_analysis_week": None, "health_curve_date": None,
            "href": f"/pdf/{key}", "download_href": f"/dl/{key}"}


@pytest.mark.parametrize("states, expected", [
    (("normal", "anormal"), "anormal"),
    (("Anormal", "normal"), "anormal"),
    (("alerta", "normal"), "alerta"),
    (("alerta", "Crítico"), "anormal"),   # no hay un nivel Crítico aparte: es Anormal, como en todo el dashboard
    (("normal", "Atención"), "alerta"),
    (("normal", None), "normal"),       # una sola fuente: vale esa
    ((None, "Alerta"), "alerta"),
    ((None, None), "sin_datos"),         # ninguna: Sin Datos, nunca Normal
    (("Sin datos", float("nan")), "sin_datos"),
    (("basura", None), "sin_datos"),
])
def test_estado_combinado_es_el_mas_critico(states, expected):
    assert report_health.combine_states(*states) == expected


def test_escala_de_criticidad():
    assert report_health.STATE_ORDER == ("sin_datos", "normal", "alerta", "anormal")
    assert report_health.STATES_BY_SEVERITY == ("anormal", "alerta", "normal", "sin_datos")


def test_unidad_con_analisis_normal_y_curva_anormal_queda_anormal():
    """Caso CA-90 de capstone: el analisis dice normal, la curva anormal."""
    records = [_rec("CA-90"), _rec("CA-91"), _rec("CA-92"), _rec("CA-93")]
    _attach(
        records,
        analysis=[("CA-90", "2026-11-01", "normal"), ("CA-91", "2026-11-01", "alerta"),
                  ("CA-92", "2026-11-01", "normal")],
        curve=[("CA-90", "2026-11-01", "Anormal"), ("CA-91", "2026-11-01", "Normal"),
               ("CA-93", "2026-11-01", "Alerta")],
    )
    by_unit = {r["unit"]: r for r in records}
    assert (by_unit["CA-90"]["health_analysis"], by_unit["CA-90"]["health_curve"], by_unit["CA-90"]["health"]) == \
        ("normal", "anormal", "anormal")
    assert by_unit["CA-91"]["health"] == "alerta"   # el analisis pesa mas que una curva normal
    assert by_unit["CA-92"]["health"] == "normal" and by_unit["CA-92"]["health_curve"] is None
    assert by_unit["CA-93"]["health"] == "alerta" and by_unit["CA-93"]["health_analysis"] is None


def test_sin_ninguna_fuente_es_sin_datos():
    records = [_rec("CA-50")]
    _attach(records)
    assert records[0]["health"] == "sin_datos"
    assert records[0]["health_analysis"] is None and records[0]["health_curve"] is None


def test_cada_reporte_usa_los_datos_hasta_su_fecha():
    records = [_rec("T_9", "2026-10-01"), _rec("T_9", "2026-10-12"), _rec("T_9", "2026-11-04")]
    _attach(
        records,
        analysis=[("T_09", "2026-09-28", "alerta"), ("T_09", "2026-10-10", "normal")],
        curve=[("T_09", "2026-09-30", "Normal"), ("T_09", "2026-10-11", "Anormal"), ("T_09", "2026-10-25", "Alerta")],
    )
    first, second, third = records
    assert first["health"] == "alerta"       # lo posterior al 10-01 no cuenta
    assert second["health"] == "anormal" and second["health_curve_date"] == "2026-10-11"
    # 2026-11-04: el analisis (10-10) tiene 25 dias y no cuenta; la curva (10-25) tiene 10 y si
    assert (third["health_analysis"], third["health_curve"], third["health"]) == (None, "alerta", "alerta")


def test_fuente_con_dato_demasiado_viejo_no_aporta():
    records = [_rec("CA-1", "2026-11-04")]
    _attach(records, analysis=[("CA-1", "2026-10-20", "anormal")], curve=[("CA-1", "2026-11-03", "Normal")])
    assert records[0]["health_analysis"] is None and records[0]["health"] == "normal"


def test_una_fuente_que_falla_no_rompe_el_catalogo():
    def boom(client, system):
        raise RuntimeError("parquet roto")

    curve = _frame([("CA-1", pd.Timestamp("2026-11-03"), "Alerta")], ["Unit", "Fecha", "estado"])
    records = [_rec("CA-1")]
    report_health.attach_health(records, "CAPSTONE", loaders={"predictivo": boom},
                                curve_loaders={"predictivo": lambda c, s: curve})
    assert records[0]["health"] == "alerta" and records[0]["health_analysis"] is None


def test_un_critico_de_una_fuente_se_lee_como_anormal():
    records = [_rec("CA-1")]
    _attach(records, analysis=[("CA-1", "2026-11-03", "alerta")], curve=[("CA-1", "2026-11-03", "Crítico")])
    assert records[0]["health_curve"] == "anormal" and records[0]["health"] == "anormal"


# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------

def _luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_paleta_sale_de_la_escala_unica_del_dashboard():
    """Mismos colores que status_chip.css: Normal verde, Alerta naranja, Anormal rojo, Sin Datos gris."""
    assert set(rs.STATE_STYLES) == {"sin_datos", "normal", "alerta", "anormal"}
    for status in SCALE:
        style = rs.STATE_STYLES[status.key]
        assert (style["bg"], style["text"], style["dot"], style["border"]) == (
            status.bg, status.text, status.solid, status.border)
    assert rs.STATE_STYLES["anormal"]["dot"] == "#b91c1c" and rs.STATE_STYLES["alerta"]["dot"] == "#c2410c"
    assert rs.STATE_STYLES["normal"]["dot"] == "#15803d"


def test_escala_y_css_de_los_chips_no_se_desalinean():
    css = (ROOT / "dashboard" / "assets" / "status_chip.css").read_text(encoding="utf-8")
    for status in SCALE:
        for token, value in (("solid", status.solid), ("bg", status.bg), ("text", status.text),
                             ("border", status.border)):
            assert f"--st-{status.css}-{token}: {value};" in css, (status.key, token)


@pytest.mark.parametrize("raw, name", [
    ("normal", "Normal"), ("ALERTA ", "Alerta"), ("Atención", "Alerta"), ("anormal", "Anormal"),
    ("Crítico", "Anormal"), ("critico", "Anormal"), ("Sin Datos", "Sin Datos"), ("InsufficientData", "Sin Datos"),
    (None, "Sin Datos"), (float("nan"), "Sin Datos"), ("", "Sin Datos"),
])
def test_get_status_acepta_cualquier_escritura(raw, name):
    assert get_status(raw).name == name
    assert status_chip.canonical_status(raw) == name   # el chip del resto del dashboard dice lo mismo


def test_escala_ordenada_y_el_chip_general_usa_los_mismos_colores():
    assert [s.name for s in SCALE] == ["Sin Datos", "Normal", "Alerta", "Anormal"]
    assert [s.rank for s in SCALE] == [0, 1, 2, 3]
    assert status_chip.STATUS_SOLID_COLORS == {s.name: s.solid for s in SCALE}


@pytest.mark.parametrize("state", list(rs.STATE_STYLES))
def test_texto_de_cada_estado_tiene_contraste_suficiente(state):
    style = rs.STATE_STYLES[state]
    assert _contrast(style["text"], style["bg"]) >= 4.5


def test_chip_lleva_etiqueta_de_texto_y_la_paleta_del_estado(app_context):
    chip = rs.state_chip("anormal")
    assert "Anormal" in str(chip) and chip.style["--rp-bg"] == "#fee2e2" and chip.style["--rp-dot"] == "#b91c1c"
    assert "Sin Datos" in str(rs.state_chip(None))      # la etiqueta del resto del dashboard
    assert rs.state_label("Crítico") == "Anormal"


def test_estilos_no_dan_borde_de_color_a_la_izquierda_ni_usan_icono_pdf():
    css = (ROOT / "dashboard" / "assets" / "reporting.css").read_text(encoding="utf-8")
    assert "border-left" not in css and "border-inline-start" not in css
    views_source = (ROOT / "dashboard" / "components" / "reporting_views.py").read_text(encoding="utf-8")
    assert "fa-file-pdf" not in views_source


# ---------------------------------------------------------------------------
# Estado actual
# ---------------------------------------------------------------------------

def _fleet():
    return [
        _rec("CA-10", health="normal"),
        _rec("CA-9", health="alerta"),
        _rec("CA-90", health="anormal", analysis="normal", curve="anormal"),
        _rec("CA-100", health="alerta"),
        _rec("CA-7", health="sin_datos"),
        _rec("CA-8", health="anormal"),
        _rec("CA-9", date="2026-10-12", health="normal"),
        _rec("CA-9", date="2026-11-04", system="transmision", health="normal"),
    ]


def test_conteos_y_secciones_ordenadas_por_criticidad_y_unidad():
    batch = rv.batch_records(_fleet(), "predictivo", "motor", "2026-11-04")
    assert rv.state_counts(batch) == {"anormal": 2, "alerta": 2, "normal": 1, "sin_datos": 1}
    attention, clear = rv.split_sections(batch)
    assert [r["unit"] for r in attention] == ["CA-8", "CA-90", "CA-9", "CA-100"]
    assert [r["unit"] for r in clear] == ["CA-10", "CA-7"]
    # El filtro de estado usa el estado combinado.
    attention, clear = rv.split_sections(batch, "alerta")
    assert [r["unit"] for r in attention] == ["CA-9", "CA-100"] and clear == []
    attention, clear = rv.split_sections(batch, "sin_datos")
    assert attention == [] and [r["unit"] for r in clear] == ["CA-7"]
    assert len(rv.split_sections(batch, "all")[0]) == 4


def test_todos_los_sistemas_suma_los_dos():
    batch = rv.batch_records(_fleet(), "predictivo", "all", "2026-11-04")
    assert len(batch) == 7 and {r["system"] for r in batch} == {"motor", "transmision"}


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None:
        yield from _walk(children)


def _by_class(node, name):
    return [n for n in _walk(node) if name in (getattr(n, "className", "") or "").split()]


def _attr(component, name):
    if not hasattr(component, "to_plotly_json"):
        return None
    return component.to_plotly_json()["props"].get(name)


def test_tarjetas_y_fichas(app_context):
    batch = rv.batch_records(_fleet(), "predictivo", "motor", "2026-11-04")
    attention, clear = rv.split_sections(batch)
    sections = views.overview_sections(attention, clear, show_system=False)
    cards = _by_class(sections[0], "rp-card")
    assert [c.className.split()[-1] for c in cards] == [
        "rp-card--anormal", "rp-card--anormal", "rp-card--alerta", "rp-card--alerta"]
    text = str(cards[1])
    assert "CA-90" in text and "Anormal" in text and "Motor · informe del 2026-11-04" in text
    assert "Ver informe →" in text
    assert cards[1].style["--rp-bg"] == "#fee2e2"
    assert cards[1].href.endswith("?report=2026-11-04%2Finforme_predictivo_ca-90_20261104.pdf")  # enlace real
    assert "fa-file-pdf" not in str(sections)

    tiles = _by_class(sections[1], "rp-tile")
    assert [tile.className.split()[-1] for tile in tiles] == ["rp-tile--normal", "rp-tile--sin_datos"]
    assert "Sin Datos" in str(tiles[1]) and tiles[1].href
    # Los encabezados llevan el conteo.
    assert "4 unidades" in str(sections[0]) and "2 unidades" in str(sections[1])
    assert "combina el último análisis de la unidad y la curva de riesgo acumulado" in str(sections[-1])


def test_fila_de_filtros_de_estado_con_conteos(app_context):
    batch = rv.batch_records(_fleet(), "predictivo", "motor", "2026-11-04")
    row = views.state_filter_row(rv.state_counts(batch), "alerta")
    buttons = _by_class(row, "rp-filter")
    assert len(buttons) == 5
    assert "Todas" in str(buttons[0]) and "6" in str(buttons[0])
    assert [_attr(b, "aria-pressed") for b in buttons] == ["false", "false", "true", "false", "false"]
    assert [_attr(b, "data-rp-state") for b in buttons] == [
        "all", "anormal", "alerta", "normal", "sin_datos"]


# ---------------------------------------------------------------------------
# Informe de unidad
# ---------------------------------------------------------------------------

def _catalog_with_history():
    return [
        _rec("CA-8", "2026-11-04", health="anormal", analysis="alerta", curve="anormal"),
        _rec("CA-90", "2026-11-04", health="anormal", analysis="normal", curve="anormal"),
        _rec("CA-90", "2026-10-12", health="normal", analysis="normal", curve="normal"),
        _rec("CA-90", "2026-11-04", system="transmision", health="alerta"),
        _rec("CA-10", "2026-11-04", health="normal"),
        _rec("CA-10", "2026-10-12", health="alerta"),
        _rec("CA-11", "2026-10-12", health="alerta"),   # sin informe del 2026-11-04
    ]


CA90_KEY = "2026-11-04/informe_predictivo_ca-90_20261104.pdf"


def test_lista_del_visor_y_vecinos():
    records = _catalog_with_history()
    model = rv.viewer_model(records, CA90_KEY, "2026-11-04")
    assert [r["unit"] for r in model["rows"]] == ["CA-8", "CA-90", "CA-10"]
    assert (model["position"], model["total"]) == (1, 3)
    assert model["previous"]["unit"] == "CA-8" and model["next"]["unit"] == "CA-10"
    assert [s for s, _ in model["systems"]] == ["motor", "transmision"]
    assert [r["date"] for r in model["dates"]] == ["2026-11-04", "2026-10-12"]

    first = rv.viewer_model(records, "2026-11-04/informe_predictivo_ca-8_20261104.pdf", "2026-11-04")
    assert first["previous"] is None and first["next"]["unit"] == "CA-90"
    last = rv.viewer_model(records, "2026-11-04/informe_predictivo_ca-10_20261104.pdf", "2026-11-04")
    assert last["next"] is None and last["previous"]["unit"] == "CA-90"
    assert rv.viewer_model(records, "no/existe.pdf") is None


def test_cambiar_de_unidad_conserva_sistema_y_fecha_o_cae_al_ultimo():
    records = _catalog_with_history()
    # Abierto el informe del 10-12 de CA-90, con la lista del 11-04 (CA-11 no esta en esa lista).
    model = rv.viewer_model(records, "2026-10-12/informe_predictivo_ca-90_20261012.pdf", "2026-11-04")
    targets = {row["unit"]: row["target"]["date"] for row in model["rows"]}
    assert targets == {"CA-8": "2026-11-04", "CA-90": "2026-10-12", "CA-10": "2026-10-12"}
    # CA-8 no tiene informe del 10-12: cae al mas reciente de su sistema.
    systems = dict(model["systems"])
    assert systems["transmision"]["date"] == "2026-11-04"   # CA-90 no tiene transmision el 10-12


def test_busqueda_de_la_lista():
    rows = rv.viewer_model(_catalog_with_history(), CA90_KEY)["rows"]
    assert [r["unit"] for r in rv.search_rows(rows, "ca-9")] == ["CA-90"]
    assert [r["unit"] for r in rv.search_rows(rows, " ")] == [r["unit"] for r in rows]
    assert rv.search_rows(rows, "zzz") == []


def test_cabecera_con_estado_combinado_fuentes_y_vecinos(app_context):
    model = rv.viewer_model(_catalog_with_history(), CA90_KEY, "2026-11-04")
    header = views.report_header(model)
    text = str(header)
    assert "Estado combinado · Análisis de la unidad: Normal · Curva de riesgo acumulado: Anormal" in text
    chip = _by_class(header, "rp-chip")[0]
    assert "Anormal" in str(chip) and chip.style["--rp-dot"] == "#b91c1c"   # no el Normal del analisis
    assert "2 / 3" in text
    labels = {_attr(n, "aria-label") for n in _walk(header)}
    assert {"Anterior: CA-8", "Siguiente: CA-10"} <= labels
    assert "Cerrar informe" in text


def test_barra_con_sistema_y_tira_de_historial(app_context):
    model = rv.viewer_model(_catalog_with_history(), CA90_KEY, "2026-11-04")
    toolbar = views.report_toolbar(model)
    text = str(toolbar)
    assert "Abrir en pestaña nueva" in text and "Descargar PDF" in text and "Historial de informes" in text
    dates = _by_class(toolbar, "rp-date")
    assert [_attr(d, "data-rp-key")[:10] for d in dates] == ["2026-11-04", "2026-10-12"]
    assert "rp-date--on" in dates[0].className and "rp-date--on" not in dates[1].className
    # Cada fecha lleva punto de estado y su etiqueta.
    assert "Anormal" in str(dates[0]) and "Normal" in str(dates[1])
    assert len(_by_class(toolbar, "rp-segment__btn")) == 2
    assert views.pdf_src(model["record"]).endswith("#toolbar=0&navpanes=0&view=FitH")


# ---------------------------------------------------------------------------
# Navegacion (acciones del navegador)
# ---------------------------------------------------------------------------

def test_abrir_cerrar_y_cambiar_de_pestana():
    records = _catalog_with_history()
    key = "2026-10-12/informe_predictivo_ca-90_20261012.pdf"
    view = rc.next_view(None, {"type": "open", "key": key, "ctx": "current"}, records, "2026-11-04")
    assert view == {"tab": "current", "key": key, "list_date": "2026-11-04"}
    # Desde el Historial la lista toma la fecha del informe abierto.
    opened = rc.next_view({"tab": "history"}, {"type": "open", "key": key, "ctx": "record"}, records, "2026-11-04")
    assert opened == {"tab": "current", "key": key, "list_date": "2026-10-12"}
    # Dentro del visor la lista no cambia de fecha.
    moved = rc.next_view(view, {"type": "open", "key": CA90_KEY, "ctx": "keep"}, records, "2026-10-12")
    assert moved["list_date"] == "2026-11-04" and moved["key"] == CA90_KEY
    assert rc.next_view(view, {"type": "close"}, records, None) == {"tab": "current", "key": None, "list_date": None}
    assert rc.next_view(view, {"type": "tab", "tab": "history"}, records, None)["tab"] == "history"
    assert rc.next_view(view, {"type": "open", "key": "../x.pdf", "ctx": "keep"}, records, None) is None
    assert rc.next_view(view, {"type": "sort", "col": "unit"}, records, None) is None
    assert rc.open_model({"key": "hackeado/otro.pdf"}, records) is None


# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------

def test_filtros_del_historial_usan_el_estado_combinado():
    records = _catalog_with_history()
    assert len(rv.filter_history(records, "predictivo", None, None, None, None)) == 7
    assert {r["unit"] for r in rv.filter_history(records, state="anormal")} == {"CA-8", "CA-90"}
    assert len(rv.filter_history(records, state="alerta")) == 3
    assert {r["unit"] for r in rv.filter_history(records, unit="CA-10")} == {"CA-10"}
    assert len(rv.filter_history(records, date="2026-10-12")) == 3
    assert len(rv.filter_history(records, system="transmision")) == 1
    assert len(rv.filter_history(records, "all", "all", "all", "all", "all")) == 7


def test_orden_y_paginacion_del_historial():
    records = _catalog_with_history()
    by_date = rv.sort_history(records, "date", "desc")
    assert by_date[0]["date"] == "2026-11-04" and by_date[-1]["date"] == "2026-10-12"
    assert rv.sort_history(records, "unit", "asc")[0]["unit"] == "CA-8"
    by_state = rv.sort_history(records, "health", "desc")
    assert [r["health"] for r in by_state[:2]] == ["anormal", "anormal"] and by_state[-1]["health"] == "normal"

    state = {"sort": "date", "dir": "desc", "page": 3}
    assert rv.next_sort(state, "date") == {"sort": "date", "dir": "asc", "page": 1}
    assert rv.next_sort(state, "unit") == {"sort": "unit", "dir": "asc", "page": 1}
    assert rv.next_sort({"sort": "unit", "dir": "asc", "page": 2}, "health")["dir"] == "desc"

    assert rv.paginate(list(range(32)), 3, 15) == ([30, 31], 3, 3, 31)
    assert rv.paginate(list(range(32)), 99, 15)[1] == 3 and rv.paginate([], 1, 15)[3] == 0
    assert rc.next_history_state({"page": 4}, "reporting-his-state", None)["page"] == 1
    assert rc.next_history_state({"page": 1}, "reporting-action", {"type": "page", "page": "2"})["page"] == 2
    assert rc.next_history_state({"page": 1}, "reporting-action", {"type": "state"}) is None


def test_tabla_con_chips_boton_con_texto_y_descarga_con_aria_label(app_context):
    records = _catalog_with_history()
    shown = rv.sort_history(records, "date", "desc")[:3]
    table = views.history_table(shown, "date", "desc")
    text = str(table)
    for column in ("Fecha", "Unidad", "Sistema", "Estado", "Acciones"):
        assert column in text
    assert len(_by_class(table, "rp-chip")) == 3          # chips, no celdas rellenas
    assert "backgroundColor" not in text
    open_buttons = [n for n in _walk(table) if _attr(n, "data-rp-ctx") == "record"]
    assert len(open_buttons) == 3 and all(b.children == "Ver informe" for b in open_buttons)
    icons = _by_class(table, "rp-icon-btn")
    assert len(icons) == 3 and all(_attr(i, "aria-label").startswith("Descargar informe de ") for i in icons)
    assert "aria-sort" in text and "descending" in text
    assert "Mostrando 1–3 de 7" in str(views.history_pager(1, 3, 7, 1, 3))


def test_ninguna_vista_lee_el_estado_de_una_fuente_para_color_o_etiqueta():
    """El color y la etiqueta salen siempre de `health` (el combinado); las fuentes solo se muestran como texto."""
    import inspect
    for module in (rc, views, rv):
        source = inspect.getsource(module)
        used = source.count("health_analysis") + source.count("health_curve")
        allowed = sum(inspect.getsource(fn).count("health_analysis") + inspect.getsource(fn).count("health_curve")
                      for fn in (getattr(module, "sources_text", None), getattr(module, "sources_detail", None))
                      if fn is not None)
        assert used == allowed, module.__name__
    joined = inspect.getsource(rc) + inspect.getsource(views) + inspect.getsource(rv)
    assert "unit_failure_analisis" not in joined
