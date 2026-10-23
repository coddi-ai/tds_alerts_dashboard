"""
Genera un informe preliminar de fallas de ejemplo, desde cualquier carpeta.

    python probar_informe.py --unidad CA-88 --fecha 2026-06-28              # con la IA (OPENAI_API_KEY)
    python probar_informe.py --unidad CA-88 --fecha 2026-06-28 --sin-ia     # textos de relleno, sin costo
    python probar_informe.py --unidad CA-88 --fecha 2026-06-28 --cliente CDA
    python probar_informe.py --unidad CA-88 --fecha 2026-06-28 --origen s3  # datos desde S3 (ERS_S3_BUCKET)

El PDF y su registro JSON quedan en outputs/informe_falla/<cliente>/ (ver config.py).
"""

import argparse
import json
import os
import sys
from pathlib import Path

# El paquete importa todo como src.informe_falla...: se agrega la raiz del repo a la ruta de
# busqueda y se trabaja desde ella (algunos lectores de datos usan rutas relativas a la raiz).
RAIZ_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ_REPO))
os.chdir(RAIZ_REPO)

try:
    from dotenv import load_dotenv
    load_dotenv(RAIZ_REPO / ".env")
except ImportError:
    pass

from src.informe_falla import service  # noqa: E402


def ia_de_relleno(system, user, esquema):
    """Reemplaza a la IA: sirve para revisar el formato con datos reales, sin llamar a OpenAI."""
    texto = {"diagnostico": "Texto de prueba.", "causa_probable": "Texto de prueba."}
    return json.dumps({
        "veredicto": "SEÑAL CLARA", "confianza": "media", "motivo_confianza": "Texto de prueba.",
        "detenciones": texto,
        "resumen": {**texto, "acciones": ["Acción de prueba."], "riesgo_si_no_se_hace": "Texto de prueba."},
        "coincide_con_veredicto_reglas": True, "motivo_si_difiere": "",
    })


def main():
    parser = argparse.ArgumentParser(description="Informe preliminar de fallas de ejemplo")
    parser.add_argument("--unidad", required=True, help="por ejemplo CA-88")
    parser.add_argument("--fecha", required=True, help="fecha de la detención, AAAA-MM-DD")
    parser.add_argument("--cliente", default="CAPSTONE")
    parser.add_argument("--sin-ia", action="store_true", help="usa textos de relleno en vez de la IA")
    parser.add_argument("--origen", choices=["local", "s3"],
                        help="de dónde leer el Predictivo; sin esta opción, INFORME_FALLA_ORIGEN del .env (o local)")
    args = parser.parse_args()
    if args.origen:
        os.environ["INFORME_FALLA_ORIGEN"] = args.origen

    solicitud = {"client": args.cliente, "unit": args.unidad, "event_date": args.fecha,
                 "system": "motor", "images": [], "requested_by": "probar_informe.py"}
    try:
        resultado = service.generar_informe(solicitud, llm_fn=ia_de_relleno if args.sin_ia else None)
    except service.InformeError as exc:
        print(f"No se generó el informe: {exc.motivo}")
        if str(exc) and str(exc) != exc.motivo:
            print("Detalle:", exc)
        sys.exit(1)

    print(f"Veredicto: {resultado['verdict']} | confianza: {resultado['confidence']}")
    print("Datos del Predictivo desde:", os.environ.get("INFORME_FALLA_ORIGEN", "local"))
    print("Controles:", "; ".join(resultado["problems"]) if resultado["problems"] else "OK")
    print("PDF:", service.ruta_pdf(args.cliente, resultado["report_id"]))


if __name__ == "__main__":
    main()