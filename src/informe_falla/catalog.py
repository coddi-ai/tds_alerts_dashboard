"""
Metodo del Informe preliminar de falla: ventanas, umbrales, modos de falla, componentes compatibles y
catalogo de verificaciones. La operacion (modelo, carpetas, caches) y el contexto de cada
cliente estan en config.py.

Los textos del catalogo son fijos: la IA solo elige identificadores, no redacta
procedimientos. Ajustarlos con el equipo de mantencion.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

VERSION = 2   # 1 = score semanal; 2 = + score diario (risk_scores)

ZONA_HORARIA = "America/Santiago"

# Componente del Predictivo que analiza el informe. Los modos y el catalogo son de motor.
COMPONENTE = "motor"

# --- Ventanas, en semanas ISO contadas hacia atras desde la semana de la fecha (semana 0, excluida)
SEMANAS_RECIENTES = 4          # ventana de analisis: el ultimo mes (semanas -4 a -1)
SEMANAS_ATRAS = 13             # periodo analizado: 3 meses; lo anterior al ultimo mes es la linea base

# --- Calidad de datos (semanal)
MIN_SEMANAS_BASE = 4           # minimo de semanas de base para comparar contra la propia unidad
MIN_SEMANAS_RECIENTES = 2      # bajo esto: datos insuficientes
DIAS_SIN_DATOS_MAX = 3         # sobre esto, el valor de esa semana esta congelado (no es dato nuevo)
DIAS_DATOS_VIEJOS = 14         # ultimo dato mas antiguo que esto: se advierte primero
MIN_DIAS_MEDIA_30D = 21        # media de 30 dias calculada con menos dias: se advierte

# --- Semana anomala: debe cumplir TODO lo siguiente
#     (el percentil de flota solo no basta: una unidad que siempre anda alta estaria arriba todas las semanas)
PERCENTIL_FLOTA_MIN = 90       # sobre este percentil de la flota en esa semana
Z_MIN = 3.0                    # al menos estas desviaciones sobre la media de su linea base
SALTO_MIN = 2.0                # y al menos estos puntos sobre el maximo de su linea base

# --- Nivel por modo (semanal)
RACHA_ALTA = 2                 # alto: semanas anomalas seguidas hasta la ultima semana...
SEMANAS_ANOMALAS_ALTA = 3      # ...o este total de semanas anomalas en el mes
SEMANAS_ANOMALAS_MEDIA = 2     # medio: este total...
SEMANAS_FRESCAS = 2            # ...o una sola semana anomala dentro de las ultimas N semanas
MAX_FRACCION_FLOTA = 0.20      # si mas de esta fraccion de la flota tiene el mismo patron, no es especifico
UMBRAL_ALERTA_PREDICTIVO = 50  # alerta del Predictivo (por construccion, P98 de la flota): sube el nivel a alto

# --- Score diario (risk_scores)
DIAS_RECIENTES = 7 * SEMANAS_RECIENTES   # el mismo mes, contado en dias hasta el dia anterior a la fecha
MIN_DIAS_BASE = 21              # minimo de dias de base para comparar contra la propia unidad
MIN_DIAS_RECIENTES = 7          # bajo esto: datos diarios insuficientes
MIN_DIAS_RECIENTES_MEDIA = 25   # bajo esto (mas de 3 dias sin datos en el mes): confianza baja
# Dia anomalo: sobre el P90 de la flota ese dia, sobre el percentil PERCENTIL_BASE_DIARIO de su propia
# base diaria, al menos Z_MIN desviaciones sobre su media y SALTO_MIN puntos. Se usa un percentil de la
# base y no su maximo porque el maximo de ~150 dias esta dominado por dias extremos.
PERCENTIL_BASE_DIARIO = 95
DIAS_SOSTENIDO, VENTANA_SOSTENIDO = 3, 5    # episodio: al menos 3 dias anomalos dentro de 5 dias seguidos
RACHA_DIAS_ALTA = 3             # alto: dias anomalos seguidos hasta el ultimo dia con dato...
DIAS_ANOMALOS_ALTA = 7          # ...o un episodio con al menos este total de dias anomalos
DIAS_FRESCOS = 7                # medio: episodio, o 2 dias anomalos dentro de los ultimos 7 dias
DIAS_GRAFICO = 7 * SEMANAS_ATRAS   # el periodo analizado completo, para el grafico del informe (no va a la IA)

DECIMALES = 2
NIVELES = ["sin_datos", "ninguno", "bajo", "medio", "alto"]           # de menor a mayor
CONFIANZAS = ["insuficiente", "baja", "media", "alta"]
VEREDICTOS = ["SEÑAL CLARA", "SEÑAL DÉBIL", "SIN SEÑAL ANÓMALA", "DATOS INSUFICIENTES"]

# --- Modos de falla y componentes compatibles (orientacion para la inspeccion, no diagnostico)
COMPONENTES_POR_MODO = {
    "bearing_wear_risk": ["cojinetes de bancada y de biela", "cigüeñal", "bielas", "volante",
                          "amortiguador de cigüeñal"],
    "lubrication_failure_risk": ["bomba de aceite", "presión de galería (rifle)", "nivel de aceite",
                                 "filtros de aceite", "enfriador de aceite"],
    "oil_degradation_risk": ["estado y viscosidad del aceite", "filtros de aceite", "líneas de aceite",
                             "intervalo desde el último cambio"],
    "blowby_risk": ["anillos, pistones y camisas", "respiradero y presión de cárter", "culata y válvulas"],
    "coolant_contamination_risk": ["enfriador de aceite", "empaquetaduras de culata", "bomba de agua",
                                   "radiador y líneas de agua", "termostatos"],
    "thermal_imbalance_risk": ["inyectores por banco", "temperaturas de escape por cilindro (EGT)",
                               "múltiples de escape", "admisión por banco"],
    "turbocharger_risk": ["turbocargadores", "postenfriador (aftercooler)", "admisión y tubo de escape"],
    "combustion_risk": ["inyectores", "bomba y filtros de combustible", "dosificación de combustible"],
    "abrasive_wear_risk": ["filtros y limpiador de aire", "ductos de admisión (ingreso de polvo)"],
}
MODOS = ["abrasive_wear_risk", "combustion_risk", "thermal_imbalance_risk", "turbocharger_risk",
         "oil_degradation_risk", "coolant_contamination_risk", "lubrication_failure_risk",
         "bearing_wear_risk", "blowby_risk"]

NOMBRE_MODO = {
    "abrasive_wear_risk": "Desgaste abrasivo",
    "combustion_risk": "Combustión",
    "thermal_imbalance_risk": "Desbalance térmico",
    "turbocharger_risk": "Turbocargador",
    "oil_degradation_risk": "Degradación del aceite",
    "coolant_contamination_risk": "Contaminación por refrigerante",
    "lubrication_failure_risk": "Falla de lubricación",
    "bearing_wear_risk": "Desgaste de cojinetes",
    "blowby_risk": "Blow-by",
}

# --- Catalogo de verificaciones: id -> (accion, que buscar, tipo).
#     "rapida" = sin desarme; "mayor" = requiere desarme.
#     Los valores de especificacion (presiones, temperaturas, juegos) son los del manual del fabricante.
VERIFICACIONES = {
    # Antes de intervenir: valen para cualquier detencion de motor
    "PRE-1": ("Tomar una muestra de aceite antes de drenar o intervenir",
              "Enviarla al laboratorio: preserva la evidencia del estado interno del motor al momento de la falla.", "rapida"),
    "PRE-2": ("Descargar los códigos de falla y eventos del ECM",
              "Códigos activos o recientes que apunten a un sistema: presión de aceite, temperatura, inyección o sobrealimentación.", "rapida"),
    "PRE-3": ("Registrar horómetro, nivel de aceite y nivel de refrigerante al llegar",
              "Faltantes o excesos de aceite o refrigerante. El registro sirve para el cierre de la detención.", "rapida"),
    "PRE-4": ("Inspección visual y auditiva, con el motor detenido y, si es seguro, en marcha",
              "Fugas, humo anormal, ruidos o golpeteos.", "rapida"),
    # Desgaste de cojinetes
    "COJ-1": ("Revisar la presión de aceite en ralentí y en alta (ECM o manómetro)",
              "Presión bajo especificación: posible holgura en cojinetes o falla de lubricación.", "rapida"),
    "COJ-2": ("Cortar e inspeccionar el filtro de aceite", "Limalla o partículas metálicas brillantes (cobre, plomo, acero).", "rapida"),
    "COJ-3": ("Revisar el tapón magnético y el fondo del cárter", "Partículas o escamas metálicas.", "rapida"),
    "COJ-4": ("Revisar el amortiguador de vibraciones y el volante", "Daños, fugas del fluido del amortiguador o juego anormal.", "rapida"),
    "COJ-5": ("Inspeccionar cojinetes de biela y de bancada", "Desgaste, rayado o pérdida de material.", "mayor"),
    # Falla de lubricacion
    "LUB-1": ("Verificar el nivel de aceite y buscar fugas externas", "Nivel bajo o pérdidas en sellos, líneas o enfriador.", "rapida"),
    "LUB-2": ("Revisar la presión diferencial de los filtros de aceite", "Filtro restringido o trabajando en bypass.", "rapida"),
    "LUB-3": ("Revisar la bomba de aceite y la válvula reguladora de presión", "Desgaste, atascamiento o pérdida de caudal.", "mayor"),
    # Degradacion del aceite
    "ACE-1": ("Revisar las horas del aceite desde el último cambio", "Aceite sobre su intervalo de cambio.", "rapida"),
    "ACE-2": ("Revisar el aspecto y el olor del aceite", "Aceite muy oscuro o espeso, olor a combustible o aspecto lechoso.", "rapida"),
    "ACE-3": ("Revisar la temperatura de operación del aceite y el enfriador de aceite",
              "Sobretemperatura que acelera la degradación.", "rapida"),
    # Blow-by
    "BLW-1": ("Medir la presión de cárter", "Presión sobre especificación: paso de gases por anillos o camisas.", "rapida"),
    "BLW-2": ("Revisar el respiradero del cárter", "Respiradero obstruido o con arrastre excesivo de aceite.", "rapida"),
    "BLW-3": ("Revisar el consumo de aceite y si hay humo azul en el escape", "Consumo alto o humo azul persistente.", "rapida"),
    "BLW-4": ("Prueba de compresión o de fugas por cilindro, y boroscopía de camisas",
              "Cilindros con baja compresión, camisas rayadas o anillos dañados.", "mayor"),
    # Contaminacion por refrigerante
    "REF-1": ("Revisar el nivel y el consumo de refrigerante", "Pérdida de refrigerante sin fuga externa visible.", "rapida"),
    "REF-2": ("Revisar si el aceite está emulsionado (aspecto lechoso)", "Refrigerante en el aceite.", "rapida"),
    "REF-3": ("Prueba de presión del sistema de enfriamiento", "Caída de presión: fuga interna o externa.", "rapida"),
    "REF-4": ("Inspeccionar el enfriador de aceite y las empaquetaduras de culata",
              "Fisuras o fugas que mezclen refrigerante y aceite.", "mayor"),
    # Desbalance termico
    "TER-1": ("Revisar las temperaturas de escape por cilindro (EGT) y los códigos de inyectores",
              "Cilindros con temperatura muy distinta al resto.", "rapida"),
    "TER-2": ("Prueba de corte de cilindros", "Cilindros que no aportan potencia.", "rapida"),
    "TER-3": ("Revisar los múltiples de escape y de admisión por banco", "Fugas, fisuras o restricciones en un banco.", "rapida"),
    "TER-4": ("Inspeccionar los inyectores de los cilindros afectados", "Fallas de atomización o fugas.", "mayor"),
    # Turbocargador
    "TUR-1": ("Revisar el juego axial y radial de los turbocargadores", "Juego excesivo o roce del rodete.", "rapida"),
    "TUR-2": ("Buscar fugas de aceite en los turbos y en la admisión", "Aceite en la admisión, el escape o el aftercooler.", "rapida"),
    "TUR-3": ("Revisar la presión de sobrealimentación frente a la especificación",
              "Presión baja: fuga en la admisión, turbo dañado o aftercooler restringido.", "rapida"),
    "TUR-4": ("Revisar el aftercooler y los ductos de admisión", "Fugas, abrazaderas sueltas o restricción.", "rapida"),
    # Combustion
    "COM-1": ("Revisar la presión y los filtros de combustible", "Presión baja o filtros restringidos.", "rapida"),
    "COM-2": ("Revisar la calidad del combustible y si tiene agua", "Agua o contaminación en el combustible.", "rapida"),
    # Desgaste abrasivo
    "ABR-1": ("Revisar la restricción del filtro de aire", "Indicador de restricción alto o filtro dañado.", "rapida"),
    "ABR-2": ("Inspeccionar ductos, abrazaderas y sellos de admisión", "Entrada de aire sin filtrar: polvo en el lado limpio.", "rapida"),
    "ABR-3": ("Pedir silicio y metales de desgaste en el análisis de la muestra de aceite",
              "Silicio alto junto con hierro o aluminio: ingreso de polvo.", "rapida"),
}
ACCIONES_PREVIAS = ["PRE-1", "PRE-2", "PRE-3", "PRE-4"]
VERIFICACIONES_POR_MODO = {
    "bearing_wear_risk": ["COJ-1", "COJ-2", "COJ-3", "COJ-4", "COJ-5"],
    "lubrication_failure_risk": ["LUB-1", "COJ-1", "LUB-2", "COJ-2", "LUB-3"],
    "oil_degradation_risk": ["ACE-1", "ACE-2", "ACE-3", "LUB-2"],
    "blowby_risk": ["BLW-1", "BLW-2", "BLW-3", "BLW-4"],
    "coolant_contamination_risk": ["REF-1", "REF-2", "REF-3", "REF-4"],
    "thermal_imbalance_risk": ["TER-1", "TER-2", "TER-3", "TER-4"],
    "turbocharger_risk": ["TUR-1", "TUR-2", "TUR-3", "TUR-4"],
    "combustion_risk": ["COM-1", "COM-2", "TER-2", "TER-4"],
    "abrasive_wear_risk": ["ABR-1", "ABR-2", "ABR-3"],
}

assert set(MODOS) == set(COMPONENTES_POR_MODO) == set(NOMBRE_MODO) == set(VERIFICACIONES_POR_MODO), \
    "cada modo necesita componentes, nombre y verificaciones"
assert all(i in VERIFICACIONES for ids in VERIFICACIONES_POR_MODO.values() for i in ids + ACCIONES_PREVIAS)


def verificaciones(ids) -> list:
    return [{"id": i, "accion": VERIFICACIONES[i][0], "que_buscar": VERIFICACIONES[i][1], "tipo": VERIFICACIONES[i][2]}
            for i in ids]


def fecha_inicio_base(perfil: Optional[dict]) -> date:
    """Sin corte de base, cualquier fecha sirve: se usa una muy antigua."""
    return (perfil or {}).get("fecha_inicio_base") or date(2000, 1, 1)


# =============================================================================
# Mantenciones: equivalencias entre modos del Predictivo y la data de mantencion
# =============================================================================
# PROPUESTA SIN VALIDAR con mantenimiento: todo informe que la use lo declara.
# Origen: notebooks/paquete_troubleshooting/catalogos/equivalencias_subsistemas.json
# ("por_failure_mode", Capstone), copiada aqui porque esa carpeta no se versiona.
# Los valores son nombres de query_3.action_subsystem_name. Un cliente sin tabla queda
# sin modos relacionados por subsistema (y se declara), nunca con una tabla inventada.
EQUIVALENCIA_SIN_VALIDAR = "propuesta sin validar"
SUBSISTEMAS_POR_MODO = {
    "CAPSTONE": {
        "blowby_risk": ["Sistema de Motor Básico"],
        "lubrication_failure_risk": ["Sistema de Lubricación"],
        "bearing_wear_risk": ["Sistema de Motor Básico", "Sistema de Lubricación"],
        "oil_degradation_risk": ["Sistema de Lubricación"],
        "coolant_contamination_risk": ["Sistema de Enfriamiento", "Sistema de Lubricación"],
        "combustion_risk": ["Sistema de Combustible", "Sistema de entrada y salida de Aire"],
        "thermal_imbalance_risk": ["Sistema de Combustible", "Sistema de entrada y salida de Aire"],
        "turbocharger_risk": ["Sistema de entrada y salida de Aire"],
        "abrasive_wear_risk": ["Sistema de entrada y salida de Aire", "Sistema de Lubricación"],
    },
}

# Palabras de query_3.component_names que apuntan a un modo (en minuscula, por inclusion).
# Misma advertencia: propuesta sin validar. Vale para todos los clientes.
COMPONENTES_CLAVE_POR_MODO = {
    "turbocharger_risk": ["turbo", "postenfriador", "aftercooler"],
    "coolant_contamination_risk": ["enfriador de aceite", "radiador", "bomba de agua", "termostato",
                                   "refrigerante", "líneas de agua", "culata"],
    "combustion_risk": ["inyector", "bomba de inyección", "combustible"],
    "thermal_imbalance_risk": ["inyector", "múltiple de escape", "tubo de escape"],
    "lubrication_failure_risk": ["bomba de aceite", "líneas de aceite", "filtro de aceite", "colector del aceite"],
    "bearing_wear_risk": ["cojinete", "cigüeñal", "biela", "volante", "amortiguador"],
    "blowby_risk": ["respiradero", "cilindro", "pistón", "camisa", "anillo"],
    "abrasive_wear_risk": ["limpiador de aire", "filtro de aire", "ducto de admisión"],
}

# Sistemas de mantencion que corresponden a cada sistema del formulario (query_3.action_system_name, en minuscula).
SISTEMAS_MANTENCION = {
    "motor": {"motor", "sistema motor", "sistema de motor", "sistema de motor básico"},
}
