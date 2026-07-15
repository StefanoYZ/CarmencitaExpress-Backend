FIRST_FIT_3D = "FIRST_FIT_3D"
MINIMAX_MAXIMIN_3D = "MINIMAX_MAXIMIN_3D"
BEST_FIT_3D = "BEST_FIT_3D"
WORST_FIT = "WORST_FIT"
BEST_FIT_DECREASING_3D = "BEST_FIT_DECREASING_3D"
BACKTRACKING_LOGISTIC = "BACKTRACKING_LOGISTIC"
MINIMAX = "MINIMAX"
MAXIMIN = "MAXIMIN"

FRAGILITY_ORDER = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
STACK_PRIORITY = {"BAJA": 0, "MEDIA": 1, "ALTA": 2}

# Umbrales de las restricciones fisicas de estabilidad adicionales:
#   - FLAT_ELECTRONIC_RATIO: un electronico es "plano" si su dimension mayor es al
#     menos este multiplo de la menor (viaja parado sobre el canto delgado).
#   - LONGITUDINAL_MIN_CONTACT_RATIO: contacto minimo de la cara para considerar que
#     un paquete elevado esta sujeto en el eje de marcha (anti-vuelco al frenar).
#   - LEVER_LONG_SUPPORT_RATIO / LEVER_CENTRAL_BAND_RATIO: un soporte es "largo" si
#     largo/corto supera el ratio; lo apilado debe caer en su banda central para no
#     hacer palanca en un extremo.
FLAT_ELECTRONIC_RATIO = 3.0
LONGITUDINAL_MIN_CONTACT_RATIO = 0.30
LEVER_LONG_SUPPORT_RATIO = 2.5
LEVER_CENTRAL_BAND_RATIO = 0.60

LOGISTIC_ROUTE = [
    "TRUJILLO",
    "SHOREY",
    "HUAYCATAN",
    "SANTIAGO DE CHUCO",
    "CHACOMAS",
    "CACHICADAN",
    "SANTA CRUZ",
    "COCHAPAMBA",
    "UGALLAMA",
    "VILLACRUZ",
    "LAS MANZANAS",
    "ANGASMARCA",
    "TAMBO PAMPAMARCA ALTA",
    "PSICOCHACA",
    "SANTA CLARA DE TULPO",
    "LA YEGUADA",
    "MOLLEBAMBA",
    "COCHAMARCA",
    "OROCULLAY",
]

DESTINATION_ALIASES = {
    "HUAYATAN": "HUAYCATAN",
    "SANTA CRUZ DE CHUCA": "SANTA CRUZ",
    "ALGALLAMA": "UGALLAMA",
}
ROUTE_RANK = {destination: index for index, destination in enumerate(LOGISTIC_ROUTE)}
MAX_ROUTE_RANK = max(ROUTE_RANK.values())
