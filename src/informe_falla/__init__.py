"""
Informe preliminar de fallas: la falla mas probable de una detencion y sus antecedentes, a partir
de lo que el Predictivo mostro en los 3 meses previos y de las detenciones previas de la unidad.

El informe tiene tres secciones: Resumen (diagnostico, causa probable y acciones, escrito por la IA
integrando las otras dos), Predictivo y Detenciones.

Flujo (cada paso en su modulo):
  1. evidence.py       - herramientas sin IA: comparan el score semanal y diario de cada modo
                         de falla contra la propia unidad y contra la flota.
     analisis_unidad.py - el diagnostico y la causa probable que el Predictivo publico para la unidad
                         la semana previa (unit_failure_analisis).
     curva.py          - el estado del ciclo de vida del motor (cumulative_risk_curve).
     mantenciones.py   - las intervenciones de mantencion previas de la unidad.
  2. agent.py          - la IA redacta el diagnostico y la causa probable de las detenciones y el
                         Resumen, con los lineamientos de mensajes; los controles revisan los textos.
  3. report_html.py / pdf.py - el informe para el cliente, como HTML y luego PDF.
  4. service.py        - orquesta lo anterior desde el dashboard: carga los datos, corre el
                         trabajo en segundo plano y guarda el PDF.

Los parametros del analisis, los limites de los mensajes y el catalogo de verificaciones estan en catalog.py.
"""