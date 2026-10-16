"""
RCA Asistido: informe de analisis de causa raiz probable de una detencion, a partir
de lo que el Predictivo mostro en los 3 meses previos.

Flujo (cada paso en su modulo):
  1. evidence.py  - herramientas sin IA: comparan el score semanal y diario de cada modo
                    de falla contra la propia unidad y contra la flota.
  2. agent.py     - la IA redacta el RCA sobre esa evidencia (esquema estricto) y los
                    controles revisan fuentes, hipotesis y pasos de inspeccion.
  3. report_html.py / pdf.py - el informe para el cliente, como HTML y luego PDF.
  4. service.py   - orquesta lo anterior desde el dashboard: carga los datos, corre el
                    trabajo en segundo plano y guarda el PDF.

Los parametros del analisis y el catalogo de verificaciones estan en catalog.py.
"""
