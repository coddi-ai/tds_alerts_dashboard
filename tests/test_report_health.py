"""Estado de salud de cada reporte segun el analisis predictivo vigente a su fecha."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data import predictive_v2
from src.data.report_health import MAX_ANALYSIS_AGE_DAYS, attach_health, unit_key


def _history():
    # Corridas semanales reales de Capstone: domingo 2026-09-06 (W36) y sabado 2026-09-12 (W37).
    return pd.DataFrame([
        {"Unit": "T_09", "Fecha": "2026-08-30", "estado": "normal", "year": 2026, "week": 35},
        {"Unit": "T_09", "Fecha": "2026-09-06", "estado": "Anormal", "year": 2026, "week": 36},
        {"Unit": "T_09", "Fecha": "2026-09-12", "estado": "alerta", "year": 2026, "week": 37},
        {"Unit": "T_10", "Fecha": "2026-09-06", "estado": None, "year": 2026, "week": 36},
    ]).assign(Fecha=lambda df: pd.to_datetime(df["Fecha"]))


def _record(unit, date, system="motor"):
    return {"technique": "predictivo", "system": system, "unit": unit, "date": date}


@pytest.mark.parametrize("a, b", [("T_09", "T_9"), ("t_9", "T_9"), ("ca-030", "CA-30"), (" CA-30 ", "ca-30")])
def test_unidades_equivalentes_entre_parquet_y_pdf(a, b):
    assert unit_key(a) == unit_key(b)


def test_usa_el_ultimo_analisis_publicado_hasta_la_fecha_del_informe():
    calls = []

    def loader(client, system):
        calls.append((client, system))
        return _history()

    records = attach_health([
        _record("T_9", "2026-09-07"),   # lunes de W37: el analisis de W37 (09-12) aun no existia
        _record("T_9", "2026-09-12"),   # mismo dia del analisis W37
        _record("T_9", "2026-08-29"),   # antes de toda corrida
        _record("T_9", f"2026-09-{12 + MAX_ANALYSIS_AGE_DAYS + 1}"),  # analisis demasiado viejo
        _record("T_10", "2026-09-07"),  # estado vacio en la fuente
        _record("T_99", "2026-09-07"),  # unidad sin historial
    ], "CDA", loaders={"predictivo": loader})

    assert [(r["health"], r["health_week"]) for r in records] == [
        ("anormal", "2026-W36"),
        ("alerta", "2026-W37"),
        (None, None),
        (None, None),
        (None, None),
        (None, None),
    ]
    assert records[0]["health_date"] == "2026-09-06"
    assert calls == [("cda", "motor")]  # un historial por sistema, en minusculas como la carpeta


def test_tecnica_sin_fuente_o_fuente_rota_queda_sin_dato():
    def broken(client, system):
        raise OSError("parquet corrupto")

    records = attach_health([_record("T_9", "2026-09-07"), {**_record("T_9", "2026-09-07"), "technique": "aceite"}],
                            "CDA", loaders={"predictivo": broken})
    assert [r["health"] for r in records] == [None, None]


def test_historial_lee_todas_las_particiones(tmp_path, monkeypatch):
    base = tmp_path / "unit_failure_analisis"
    for week, estado in ((36, "normal"), (37, "alerta")):
        folder = base / "year=2026" / f"week={week}"
        folder.mkdir(parents=True)
        pd.DataFrame({"Unit": ["T_09"], "Fecha": [pd.Timestamp(f"2026-09-{week - 30:02d}")], "estado": [estado],
                      "ranking": [1.0]}).to_parquet(folder / "unit_failure_analisis.parquet")
    monkeypatch.setattr(predictive_v2, "unit_failure_analisis_base_path", lambda client, component: base)

    df = predictive_v2.load_unit_state_history("cda", "motor")
    assert list(df.columns) == ["Unit", "Fecha", "estado", "year", "week"]
    assert df[["week", "estado"]].values.tolist() == [[36, "normal"], [37, "alerta"]]

    monkeypatch.setattr(predictive_v2, "unit_failure_analisis_base_path", lambda c, s: tmp_path / "no-existe")
    assert predictive_v2.load_unit_state_history("cda", "motor").empty
