"""
Informe preliminar de fallas: la falla mas probable de una detencion y sus antecedentes, a partir
de lo que el Predictivo mostro en los 3 meses previos y de las detenciones previas de la unidad.

El informe tiene cuatro secciones: Resumen (diagnostico, causa probable y acciones, escrito por la IA
desde el diagnostico y la causa probable de las otras), Aceite, Monitoreo de riesgo (el Predictivo) y
Detenciones. Aceite y Detenciones llevan su propio diagnostico y causa probable, escritos por la IA.

Flujo (cada paso en su modulo):
  1. evidence.py       - herramientas sin IA: comparan el score semanal y diario de cada modo
                         de falla contra la propia unidad y contra la flota.
     analisis_unidad.py - el diagnostico y la causa probable que el Predictivo publico para la unidad
                         la semana previa (unit_failure_analisis).
     curva.py          - el estado del ciclo de vida del motor (cumulative_risk_curve).
     mantenciones.py   - las intervenciones de mantencion previas del sistema (sin la cabina).
     aceite.py         - las muestras de aceite del sistema en los 3 meses previos y el diagnostico y la
                         causa probable de las recomendaciones del laboratorio (con la IA si se puede).
  2. secciones.py      - la IA redacta el diagnostico y la causa probable de Detenciones y el Resumen,
                         este SOLO desde lo que dicen las secciones; aceite.py redacta el de Aceite. Los
                         lineamientos de mensajes y los controles vienen de agent.py.
  3. report_html.py / pdf.py - el informe para el cliente, como HTML y luego PDF.
  4. service.py        - orquesta lo anterior desde el dashboard: carga los datos, corre el
                         trabajo en segundo plano y guarda el PDF.

Los parametros del analisis, los limites de los mensajes y el catalogo de verificaciones estan en catalog.py.
"""