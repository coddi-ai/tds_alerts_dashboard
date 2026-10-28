"""Informe preliminar de falla: intervenciones de mantencion previas (src/informe_falla/mantenciones.py).

Las vistas de mantencion (query_3 y query_7) son sinteticas: ninguna prueba lee data/.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.informe_falla import agent, mantenciones as m, report_html

FECHA = "2025-09-30"


def _accion(record, dia, unidad="CA-30", tipo="Reemplazo", sistema="Sistema de Motor",
            subsistema="Sistema de Combustible", componentes=("Bomba de Inyección de Combustible",),
            detalle="Se reemplazó la bomba de inyección por filtración.", categoria="Mant. No Programada"):
    return {
        "record_id": record, "machine_code": unidad, "change_date": pd.Timestamp(dia, tz="UTC"),
        "action_type_name": tipo, "action_system_name": sistema, "action_subsystem_name": subsistema,
        "component_names": list(componentes), "action_detail_clean": detalle, "action_detail_raw": "crudo",
        "record_original_text": f"Categoria: {categoria} | Razon: MNP-Motor diesel | Comentario: TEXTO PRIVADO",
    }


def _fuente(acciones, horas=()):
    q3 = m._preparar_acciones(pd.DataFrame(acciones))
    q7 = m._preparar_horas(pd.DataFrame(list(horas), columns=["machine_code", "day", "intervention_hours"]))
    return q3, q7


@pytest.fixture
def fuente(monkeypatch):
    def usar(acciones, horas=()):
        datos = _fuente(acciones, horas)
        monkeypatch.setattr(m, "_cargar", lambda cliente: datos)
    return usar


def _base():
    """Fuente que cubre de sobra la ventana de CA-30 (junio a diciembre de 2025)."""
    return [
        _accion("r-ini", "2025-06-01", subsistema="Sistema Eléctrico y de Partida", componentes=("Batería",),
                detalle="Cambio de batería."),
        _accion("r-fin", "2025-12-15", subsistema="Sistema Eléctrico y de Partida", componentes=("Batería",),
                detalle="Cambio de batería."),
    ]


def test_solo_entran_records_anteriores_a_la_fecha(fuente):
    fuente(_base() + [
        _accion("r-prev", "2025-09-25", detalle="Cambio del módulo UF16."),
        _accion("r-mismo-dia", FECHA, detalle="Válvula de escape dañada en la UF16."),
        _accion("r-despues", "2025-10-05", detalle="Posterior."),
        # Abierto en la fecha: empieza antes y termina despues (puede ser la detencion misma).
        _accion("r-abierto", "2025-09-29", detalle="Inicio de la detención."),
        _accion("r-abierto", "2025-10-01", detalle="Cierre de la detención."),
    ], horas=[("CA-30", "2025-09-25", 15.0)])
    r = m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA, modos=["combustion_risk"])
    assert r["cobertura_mantenciones"]["estado"] == "completa"
    filas = r["detenciones_previas"]
    assert [p["fecha"] for p in filas] == ["2025-09-25"]
    assert filas[0]["horas_dia"] == 15.0 and filas[0]["tipo"] == "Correctiva" and not filas[0]["cerca_de_la_detencion"]
    assert {"modo": "combustion_risk", "por": "subsistema"} in filas[0]["modos_relacionados"]
    assert r["antecedentes_mantencion"]["omitidos"]["abiertos_en_la_fecha"] == 1
    assert r["antecedentes_mantencion"]["ultima_intervencion_por_modo"][0]["dias_antes"] == 5


def test_el_texto_privado_no_sale_del_modulo(fuente):
    fuente(_base() + [_accion("r-prev", "2025-09-25")])
    r = m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA)
    texto = str(r)
    assert "TEXTO PRIVADO" not in texto and "crudo" not in texto and "Razon" not in texto


def test_categoria_estructurada_y_registros_cercanos(fuente):
    fuente(_base() + [
        _accion("r-pm", "2025-09-10", categoria="Mant. Programada", tipo="Inspección",
                subsistema="Sistema de Lubricación", detalle="Mantenimiento programado: muestra de aceite."),
        _accion("r-cerca", "2025-09-29", detalle="Diagnóstico de alarmas del motor."),
    ])
    r = m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA)
    tipos = {p["fecha"]: (p["tipo"], p["cerca_de_la_detencion"]) for p in r["detenciones_previas"]}
    assert tipos == {"2025-09-10": ("Programada", False), "2025-09-29": ("Correctiva", True)}
    assert r["antecedentes_mantencion"]["ultimo_pm"] == {"fecha": "2025-09-10", "dias_antes": 20}
    # Las correctivas van antes que las programadas en la tabla.
    assert r["detenciones_previas"][0]["tipo"] == "Correctiva"


def test_rellenos_se_cuentan_y_no_van_a_la_tabla(fuente):
    fuente(_base() + [
        # Capstone rotula los rellenos de aceite como "Bomba de Aceite de Motor".
        _accion("r-rel1", "2025-09-01", tipo="Relleno", componentes=("Bomba de Aceite de Motor",),
                subsistema="Sistema de Lubricación", detalle="Relleno de motor diésel."),
        _accion("r-rel2", "2025-09-08", tipo="Relleno", componentes=("Tanque de Refrigerante",),
                subsistema="Sistema de Enfriamiento", detalle="Se rellena refrigerante."),
    ])
    r = m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA)
    assert r["detenciones_previas"] == []
    rellenos = r["antecedentes_mantencion"]["rellenos"]
    assert (rellenos["aceite"]["n"], rellenos["refrigerante"]["n"]) == (1, 1)


def test_recurrencia_y_tope_de_filas(fuente):
    previas = [_accion(f"r{i}", f"2025-09-{i + 1:02d}", detalle=f"Correctiva {i}.") for i in range(10)]
    fuente(_base() + previas)
    r = m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA)
    assert len(r["detenciones_previas"]) == m.MAX_FILAS_TABLA
    assert r["antecedentes_mantencion"]["omitidos"]["fuera_del_tope"] == 10 - m.MAX_FILAS_TABLA
    assert r["antecedentes_mantencion"]["recurrencia"][0]["correctivas"] == 10
    en_linea = [p for p in r["detenciones_previas"] if p["en_linea_de_tiempo"]]
    assert len(en_linea) == m.MAX_PUNTOS_LINEA


def test_otros_sistemas_y_sin_contenido_se_omiten(fuente):
    fuente(_base() + [
        _accion("r-cabina", "2025-09-20", sistema="Estación del Operador - Cabina", detalle="Aire acondicionado."),
        _accion("r-vacio", "2025-09-21", detalle="Mantenimiento programado del motor diésel; el reporte no "
                                                  "especifica la operación realizada."),
    ])
    r = m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA)
    assert r["detenciones_previas"] == []
    omitidos = r["antecedentes_mantencion"]["omitidos"]
    assert (omitidos["otros_sistemas"], omitidos["sin_contenido"]) == (1, 1)


def test_nombres_de_unidad_equivalentes(fuente):
    fuente([_accion("r1", "2025-06-01", unidad="T_09"), _accion("r2", "2025-09-25", unidad="T_09"),
            _accion("r3", "2025-12-01", unidad="T_09")])
    r = m.antecedentes_mantencion("CDA", "T_9", FECHA)
    assert [p["fecha"] for p in r["detenciones_previas"]] == ["2025-09-25"]
    # CDA no tiene tabla de equivalencias por subsistema: solo por componente.
    assert r["cobertura_mantenciones"]["equivalencia"].startswith("sin tabla")
    assert all(x["por"] == "componente" for x in r["detenciones_previas"][0]["modos_relacionados"])


@pytest.mark.parametrize("acciones, unidad, fecha, estado", [
    ([], "CA-30", FECHA, "sin_fuente"),
    ([_accion("r1", "2025-06-01", unidad="CA-31")], "CA-30", FECHA, "unidad_sin_registros"),
    ([_accion("r1", "2025-01-01"), _accion("r2", "2025-02-01")], "CA-30", FECHA, "fuera_de_cobertura"),
    ([_accion("r1", "2025-08-20"), _accion("r2", "2025-12-01")], "CA-30", FECHA, "parcial"),
], ids=["sin-fuente", "unidad-sin-registros", "fuera-de-cobertura", "parcial"])
def test_estados_de_cobertura(fuente, acciones, unidad, fecha, estado):
    fuente(acciones)
    r = m.antecedentes_mantencion("CAPSTONE", unidad, fecha)
    assert r["cobertura_mantenciones"]["estado"] == estado
    assert (r["detenciones_previas"] is None) == (estado != "parcial")
    assert m.cobertura("CAPSTONE", unidad, fecha)["estado"] == estado


# ---------------------------------------------------------------------------
# Plantilla y controles
# ---------------------------------------------------------------------------

def _evid(mant):
    return {"consulta": {"unidad": "CA-30", "fecha": FECHA}, **mant}


def test_plantilla_sin_registros_no_dice_que_no_hubo_intervenciones(fuente):
    fuente([_accion("r1", "2025-06-01", unidad="CA-31"), _accion("r2", "2025-12-01", unidad="CA-31")])
    evid = _evid(m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA))
    bloque = report_html._bloque_previas(evid)
    assert "no tiene registros de CA-30" in bloque and "Sin intervenciones" not in bloque
    assert report_html.nota_cobertura_mantenciones(evid).startswith("La fuente de mantenciones no tiene registros")


def test_plantilla_con_cobertura_completa(fuente):
    fuente(_base() + [_accion("r-prev", "2025-09-25", detalle="Cambio del módulo UF16.")],
           horas=[("CA-30", "2025-09-25", 15.0)])
    evid = _evid(m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA))
    bloque = report_html._bloque_previas(evid)
    assert "Cambio del módulo UF16." in bloque and "15,0" in bloque and "Sistema de Combustible" in bloque
    assert report_html.nota_cobertura_mantenciones(evid) == ""
    eventos = report_html._linea_de_tiempo({**evid, "ranking_modos": [], "auditoria": {"brechas": []},
                                            "diario": {}, "analisis_por_metrica": {}})
    assert ("2025-09-25", "previa", "Correctiva previa") == eventos[0][:3]


def test_plantilla_completa_sin_intervenciones(fuente):
    fuente(_base())
    evid = _evid(m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA))
    assert "Sin intervenciones del sistema en el período analizado." in report_html._bloque_previas(evid)


def test_rutas_de_mantencion_citables_y_afirmaciones_prohibidas(fuente):
    fuente(_base() + [_accion("r-prev", "2025-09-25")])
    evid = _evid(m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA))
    assert agent._resolver(evid, "detenciones_previas[fecha=2025-09-25]")
    assert agent._resolver(evid, "detenciones_previas[fecha=2025-01-01]") is None
    informe = {"causa_mas_probable": "Falla confirmada por el registro de mantención del 25 de septiembre."}
    assert agent.afirmaciones_prohibidas(informe) == ["confirmada por el registro"]


def test_la_cabina_no_es_del_motor(fuente):
    """La vista agrupa la cabina en el Sistema de Motor: sus registros salen del informe (y de la IA)."""
    fuente(_base() + [
        _accion("r-cabina", "2025-09-21", subsistema="Cabina de Operación", componentes=("Líneas del Calentador",),
                detalle="Se reparó la manguera de calefacción debido a una filtración de refrigerante."),
        # Un record con la cabina y otro subsistema del motor se queda, sin las acciones de la cabina.
        _accion("r-mixto", "2025-09-25", subsistema="Sistema de Lubricación", componentes=("Líneas de Aceite de Motor",),
                detalle="Filtración en líneas de aceite."),
        _accion("r-mixto", "2025-09-25", subsistema="Cabina de Operación", componentes=("Aire Acondicionado",),
                detalle="Revisión del aire acondicionado."),
    ])
    r = m.antecedentes_mantencion("CAPSTONE", "CA-30", FECHA)
    assert [(p["fecha"], p["subsistema"]) for p in r["detenciones_previas"]] == [("2025-09-25", "Sistema de Lubricación")]
    assert "calefacción" not in str(r) and "Aire Acondicionado" not in str(r)
    assert r["antecedentes_mantencion"]["omitidos"]["fuera_del_sistema"] == 1
