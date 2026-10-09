"""Catálogo de permisos del sistema (fuente de verdad: el código, no la base de datos).

Un permiso es un texto "<modulo>.<accion>". "ver" es el acceso al módulo; el resto son
acciones dentro de él. El módulo Configuración NO está aquí a propósito: es exclusivo del
Gerente y no se puede delegar (decisión de la v1).

Cuando aparezca una función nueva (p. ej. editar precios o exportar reportes), se añade
su acción a este catálogo y aparece sola en la matriz de permisos.
"""

# (código de acción, etiqueta que ve el Gerente en la matriz)
MODULOS = (
    {"codigo": "dashboard", "nombre": "Dashboard", "acciones": ()},
    {"codigo": "entrada_canal", "nombre": "Entrada de Canal", "acciones": (
        ("crear", "Registrar ingresos de canal"),
    )},
    {"codigo": "proveedores", "nombre": "Proveedores", "acciones": (
        ("crear", "Agregar proveedores"),
        ("editar", "Editar proveedores"),
        ("eliminar", "Eliminar proveedores"),
    )},
    {"codigo": "desposte", "nombre": "Desposte", "acciones": (
        ("crear", "Registrar despostes"),
    )},
    {"codigo": "inventario", "nombre": "Inventario", "acciones": (
        ("crear", "Crear productos"),
        ("editar", "Editar productos (precios, mínimo de stock, nombre)"),
    )},
    {"codigo": "pos", "nombre": "Punto de Venta", "acciones": (
        ("crear", "Facturar ventas"),
    )},
    {"codigo": "clientes", "nombre": "Clientes", "acciones": (
        ("crear", "Crear clientes"),
        ("editar", "Editar clientes"),
        ("eliminar", "Eliminar clientes"),
    )},
    {"codigo": "finanzas", "nombre": "Finanzas", "acciones": (
        ("crear", "Registrar gastos"),
        ("eliminar", "Eliminar gastos"),
    )},
)

# Permisos con los que nace el rol Carnicero (solo la primera vez; luego el Gerente los edita).
PERMISOS_INICIALES_CARNICERO = frozenset({
    "dashboard.ver",
    "entrada_canal.ver", "entrada_canal.crear",
    "desposte.ver", "desposte.crear",
    "inventario.ver",
})


# --- Qué permiso exige cada ruta ------------------------------------------------------------
# Regla de oro: FALLA CERRADO. Una ruta que no aparezca aquí (ni en las listas de abajo) es
# rechazada para todos menos el Gerente, así que una pantalla nueva nunca queda abierta por
# olvido. Un test comprueba que TODAS las rutas registradas estén cubiertas.
#
# Convención de "ver" vs "crear" en las pantallas que son un formulario:
#   - La pantalla de registrar (Desposte, Punto de Venta) exige "crear".
#   - Su historial/detalle exige "ver".
PERMISO_POR_ENDPOINT = {
    "dashboard.inicio": "dashboard.ver",

    "inventario.entrada_canal": "entrada_canal.ver",
    "inventario.registrar_entrada_canal": "entrada_canal.crear",
    "inventario.historial": "entrada_canal.ver",
    "inventario.exportar_historial_excel": "entrada_canal.ver",

    "inventario.proveedores": "proveedores.ver",
    "inventario.crear_proveedor": "proveedores.crear",
    "inventario.editar_proveedor": "proveedores.editar",
    "inventario.eliminar_proveedor": "proveedores.eliminar",
    "inventario.exportar_proveedores_excel": "proveedores.ver",

    "inventario.desposte": "desposte.crear",
    "inventario.registrar_desposte_ruta": "desposte.crear",
    "inventario.desposte_historial": "desposte.ver",
    "inventario.exportar_desposte_excel": "desposte.ver",
    "inventario.desposte_detalle": "desposte.ver",

    "inventario.catalogo_productos": "inventario.ver",
    "inventario.nuevo_producto": "inventario.crear",
    "inventario.editar_producto": "inventario.editar",

    "ventas.pos": "pos.crear",
    "ventas.checkout": "pos.crear",
    "ventas.historial": "pos.ver",
    "ventas.exportar_historial_excel": "pos.ver",
    "ventas.venta_detalle": "pos.ver",

    "ventas.clientes": "clientes.ver",
    "ventas.exportar_clientes_excel": "clientes.ver",
    "ventas.crear_cliente_form": "clientes.crear",
    "ventas.crear_cliente_api": "clientes.crear",
    "ventas.editar_cliente": "clientes.editar",
    "ventas.eliminar_cliente": "clientes.eliminar",

    "finanzas.dashboard": "finanzas.ver",
    "finanzas.exportar_cuadre_excel": "finanzas.ver",
    "finanzas.registrar_egreso": "finanzas.crear",
    "finanzas.listado_egresos": "finanzas.ver",
    "finanzas.exportar_egresos_excel": "finanzas.ver",
    "finanzas.eliminar_egreso": "finanzas.eliminar",
}

# Basta con estar autenticado (con la contraseña ya cambiada).
ENDPOINTS_SOLO_AUTENTICADOS = frozenset({"index", "auth.logout", "auth.cambiar_password", "auth.sin_acceso"})

# Archivos subidos (/static/uploads/<carpeta>/...): cada carpeta exige haber podido ver su módulo.
# Con varios permisos, basta uno.
PERMISOS_POR_CARPETA_UPLOADS = {
    "uploads/facturas/": ("entrada_canal.ver",),
    "uploads/egresos/": ("finanzas.ver",),
    "uploads/productos/": ("inventario.ver", "pos.ver"),
}

# Adónde mandar al usuario al iniciar sesión, en orden de preferencia (primera coincidencia).
PAGINAS_DE_INICIO = (
    ("dashboard.ver", "dashboard.inicio"),
    ("pos.crear", "ventas.pos"),
    ("pos.ver", "ventas.historial"),
    ("entrada_canal.ver", "inventario.entrada_canal"),
    ("desposte.crear", "inventario.desposte"),
    ("desposte.ver", "inventario.desposte_historial"),
    ("inventario.ver", "inventario.catalogo_productos"),
    ("proveedores.ver", "inventario.proveedores"),
    ("clientes.ver", "ventas.clientes"),
    ("finanzas.ver", "finanzas.dashboard"),
)


def codigo(modulo, accion):
    return f"{modulo}.{accion}"


def permite(efectivos, permiso):
    """True si `efectivos` (conjunto de permisos del usuario) autoriza `permiso`.

    Una acción solo vale si también se tiene el acceso "ver" de su módulo (defensa extra por si
    en la base quedó una acción suelta).
    """
    if permiso not in efectivos:
        return False
    modulo = permiso.split(".", 1)[0]
    return permiso == codigo(modulo, "ver") or codigo(modulo, "ver") in efectivos


def permite_alguno(efectivos, permisos_):
    return any(permite(efectivos, p) for p in permisos_)


def endpoint_de_inicio(efectivos):
    """Primera pantalla a la que el usuario tiene acceso, o 'auth.sin_acceso' si no tiene ninguna."""
    for permiso, endpoint in PAGINAS_DE_INICIO:
        if permite(efectivos, permiso):
            return endpoint
    return "auth.sin_acceso"


def _construir_todos():
    codigos = set()
    for modulo in MODULOS:
        codigos.add(codigo(modulo["codigo"], "ver"))
        for accion, _etiqueta in modulo["acciones"]:
            codigos.add(codigo(modulo["codigo"], accion))
    return frozenset(codigos)


TODOS = _construir_todos()


def normalizar(codigos):
    """Deja solo permisos válidos y aplica la regla "una acción exige ver el módulo".

    Ignora cualquier código desconocido (un formulario manipulado no puede inventar
    permisos) y añade "<modulo>.ver" a todo módulo con alguna acción marcada.
    """
    validos = {c for c in (codigos or ()) if c in TODOS}
    for c in list(validos):
        modulo = c.split(".", 1)[0]
        validos.add(codigo(modulo, "ver"))
    return validos
