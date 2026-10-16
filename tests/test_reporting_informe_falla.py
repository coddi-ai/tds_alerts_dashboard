"""Reportes > Reporte RCA: validacion de imagenes, armado de la solicitud y acceso por cliente.

Las unidades se reemplazan por una lista fija; ninguna prueba calcula el Resumen General.
"""

from __future__ import annotations

import base64

import pytest

from config.client_services import KNOWN_SERVICE_IDS, is_service_enabled
from dashboard.callbacks import rca_callbacks as rc
from dashboard.services_registry import NAV_PATHS, SERVICE_SECTIONS, resolve_service_id_for_pathname
from src.data import rca_report
from src.data.rca_report import RCA_MAX_IMAGE_BYTES, RCA_MAX_IMAGES

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _upload(data: bytes = PNG, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


@pytest.fixture
def units(monkeypatch):
    monkeypatch.setattr(rc, "get_ordered_units", lambda client: [{"unit": u} for u in ("T_10", "T_9", "T_09", "T_2")])


def test_decode_image_accepts_supported_images():
    image, reason = rca_report.decode_image("falla.png", _upload())
    assert reason is None
    assert image["mime"] == "image/png" and image["size"] == len(PNG) and image["caption"] == ""


@pytest.mark.parametrize("contents, reason", [
    (_upload(b"%PDF", "application/pdf"), "type"),
    ("data:image/png;base64,@@no-es-base64@@", "invalid"),
    (_upload(b"0" * (RCA_MAX_IMAGE_BYTES + 1)), "size"),
    (None, "type"),
], ids=["pdf", "base64-roto", "muy-grande", "vacio"])
def test_decode_image_rejects(contents, reason):
    assert rca_report.decode_image("x", contents) == (None, reason)


def test_add_images_stops_at_the_limit():
    files = [_upload()] * (RCA_MAX_IMAGES + 2)
    names = [f"f{i}.png" for i in range(len(files))]
    images, rejected = rc.add_images([], files, names)
    assert len(images) == RCA_MAX_IMAGES
    assert rejected == [(names[-2], "limit"), (names[-1], "limit")]


def test_captions_survive_by_image_id():
    images, _ = rc.add_images([], [_upload(), _upload()], ["a.png", "b.png"])
    ids = [{"type": "rca-image-caption", "id": images[1]["id"]}]
    updated = rc.with_captions(images, ids, ["Fisura en carcasa"])
    assert [i["caption"] for i in updated] == ["", "Fisura en carcasa"]


def test_request_carries_the_form_and_summary_drops_image_data():
    images, _ = rc.add_images([], [_upload()], ["a.png"])
    images[0]["caption"] = "  Vista lateral "
    request = rca_report.build_rca_request(
        "CDA", "T_10", "", None,
        {"title": " Perdida de potencia ", "description": "Desc", "findings": None},
        images, "operador",
    )
    assert request["system"] is None and request["event_date"] is None
    assert request["title"] == "Perdida de potencia" and request["findings"] == "" and request["actions"] == ""
    assert request["troubleshooting"] is None
    assert base64.b64decode(request["images"][0]["data_base64"]) == PNG
    assert request["images"][0]["caption"] == "Vista lateral"

    summary = rca_report.request_summary(request)
    assert "data_base64" not in summary["images"][0]
    assert "data_base64" in request["images"][0]


def test_units_are_deduplicated_and_sorted_naturally(units):
    loaded, notice = rc.load_units("cda", ["CDA"])
    assert notice is None
    assert loaded == ["T_2", "T_9", "T_10"]


def test_units_require_access_and_the_service(units):
    assert rc.load_units("CDA", ["CAPSTONE"])[0] == []
    assert rc.load_units("", ["CDA"])[0] == []
    assert not is_service_enabled("EMIN", "reporting-rca")
    assert rc.load_units("EMIN", ["EMIN"])[0] == []


def test_ready_result_embeds_the_pdf_and_lists_failed_controls(monkeypatch):
    monkeypatch.setattr(rc, "rca_file_href",
                        lambda client, rid, download=False: f"/rca/file?client={client}&id={rid}&d={int(download)}")
    job = {"report_id": "RCA_T_10_2026-10-14_1", "unit": "T_10", "event_date": "2026-10-14",
           "verdict": "SEÑAL DÉBIL", "confidence": "baja", "problems": ["2 fuentes no existen"]}
    card = str(rc.build_ready("CDA", job))
    assert "/rca/file?client=CDA&id=RCA_T_10_2026-10-14_1&d=0#view=FitH" in card
    assert "&d=1" in card and "2 fuentes no existen" in card


def test_error_result_uses_the_reason_text():
    assert "OPENAI_API_KEY" in str(rc.build_error("no_api_key"))
    assert "Intenta nuevamente" in str(rc.build_error("motivo-desconocido"))


def test_service_is_registered_under_reports():
    assert "reporting-rca" in KNOWN_SERVICE_IDS
    reporting = next(s for s in SERVICE_SECTIONS if s["section"] == "reporting")
    assert reporting["services"] == ["reporting-main", "reporting-rca"]
    assert NAV_PATHS["reporting-rca"] == "/reporting/rca"
    assert resolve_service_id_for_pathname("reporting/rca") == "reporting-rca"
    assert resolve_service_id_for_pathname("reporting") == "reporting-main"
