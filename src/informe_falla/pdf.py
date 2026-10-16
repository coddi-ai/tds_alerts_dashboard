"""
RCA Asistido: HTML del informe a PDF con WeasyPrint.

WeasyPrint necesita Pango del sistema (en la imagen Docker se instala con apt; en Windows
requiere GTK). Si no esta disponible, `pdf_disponible()` es False y el servicio lo informa
en vez de fallar a medio camino.

Solo se cargan recursos locales: las fuentes de assets/fonts y las imagenes del formulario,
que llegan como data URIs. Cualquier otra URL se rechaza, asi el HTML (que lleva texto del
usuario y de la IA) no puede hacer que el servidor pida recursos a la red.

La plantilla esta diseñada a ~1100 px de ancho (como el informe en el navegador): la pagina
se define en px con proporcion A4 (assets/report.css, @page) y se reduce con `zoom` para que
el PDF quede en A4 real.
"""

from __future__ import annotations

from src.rca.report_html import ASSETS_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Ancho de la pagina en px CSS (assets/report.css, @page) frente a A4 (210 mm = 793.7 px CSS).
ANCHO_PAGINA_PX = 1060
ZOOM = 793.7 / ANCHO_PAGINA_PX


def pdf_disponible() -> bool:
    try:
        import weasyprint  # noqa: F401
    except Exception as exc:   # OSError si falta Pango, ImportError si falta el paquete
        logger.warning(f"RCA: WeasyPrint no disponible ({type(exc).__name__}: {exc})")
        return False
    return True


def _verificar(url: str) -> None:
    if not (url.startswith("data:") or url.startswith(ASSETS_DIR.resolve().as_uri() + "/")):
        raise ValueError(f"Recurso externo bloqueado en el PDF del RCA: {url[:80]}")


def _fetcher():
    """Fetcher que solo deja pasar data URIs y archivos de assets/."""
    try:
        from weasyprint.urls import URLFetcher   # WeasyPrint >= 68: clase
    except ImportError:
        from weasyprint import default_url_fetcher   # versiones anteriores: funcion

        def fetch(url, *args, **kwargs):
            _verificar(url)
            return default_url_fetcher(url, *args, **kwargs)
        return fetch

    class SoloLocales(URLFetcher):
        def fetch(self, url, headers=None):
            _verificar(url)
            return super().fetch(url, headers)

    return SoloLocales(allowed_protocols={"file", "data"})


def html_a_pdf(documento_html: str) -> bytes:
    from weasyprint import HTML

    base = ASSETS_DIR.resolve().as_uri() + "/"
    return HTML(string=documento_html, base_url=base, url_fetcher=_fetcher()).write_pdf(zoom=ZOOM)
