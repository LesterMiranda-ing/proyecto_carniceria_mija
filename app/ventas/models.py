"""Acceso a datos del Módulo de Punto de Venta (POS) y Gestión de Clientes.

Nota sobre `productos`: esa tabla se define y se llena en app.inventario.models
(es el stock generado por Entrada de Canal + Desposte). Este módulo la LEE y
la actualiza directamente (resta stock al facturar) dentro de la misma
transacción de la venta — es la misma base de datos, y separar esa resta en
una llamada aparte a app.inventario rompería la atomicidad de la venta.
"""

from datetime import datetime

from flask import current_app

from app.db import get_db

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS clientes (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(150) NOT NULL,
    tipo_cliente    VARCHAR(20) NOT NULL DEFAULT 'detalle' CHECK (tipo_cliente IN ('detalle', 'mayoreo')),
    categoria       VARCHAR(50),
    telefono        VARCHAR(30),
    direccion       VARCHAR(255),
    nit             VARCHAR(20),
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en       TIMESTAMP NOT NULL DEFAULT NOW()
);
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS categoria VARCHAR(50);
-- Corrige instalaciones donde `nit`/`telefono` quedaron como numéricos (rompe ILIKE en la búsqueda).
ALTER TABLE clientes ALTER COLUMN nit TYPE VARCHAR(20) USING nit::text;
ALTER TABLE clientes ALTER COLUMN telefono TYPE VARCHAR(30) USING telefono::text;

CREATE TABLE IF NOT EXISTS ventas (
    id                      SERIAL PRIMARY KEY,
    numero_venta            VARCHAR(20) UNIQUE NOT NULL,
    cliente_id              INTEGER NOT NULL REFERENCES clientes(id),
    tipo_precio_aplicado    VARCHAR(20) NOT NULL CHECK (tipo_precio_aplicado IN ('detalle', 'mayoreo')),
    metodo_pago             VARCHAR(20) NOT NULL DEFAULT 'Efectivo',
    subtotal                NUMERIC(12, 2) NOT NULL CHECK (subtotal >= 0),
    total                   NUMERIC(12, 2) NOT NULL CHECK (total >= 0),
    estado                  VARCHAR(20) NOT NULL DEFAULT 'Completada',
    vendedor                VARCHAR(150),
    usuario_id              INTEGER REFERENCES usuarios(id),
    creado_en               TIMESTAMP NOT NULL DEFAULT NOW()
);
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS metodo_pago VARCHAR(20) NOT NULL DEFAULT 'Efectivo';
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS usuario_id INTEGER REFERENCES usuarios(id);

CREATE TABLE IF NOT EXISTS detalle_ventas (
    id                  SERIAL PRIMARY KEY,
    venta_id            INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
    producto_id         INTEGER NOT NULL REFERENCES productos(id),
    nombre_producto     VARCHAR(150) NOT NULL,
    cantidad            NUMERIC(10, 3) NOT NULL CHECK (cantidad > 0),
    unidad_venta        VARCHAR(10) NOT NULL,
    precio_unitario     NUMERIC(10, 2) NOT NULL CHECK (precio_unitario >= 0),
    subtotal_linea      NUMERIC(12, 2) NOT NULL CHECK (subtotal_linea >= 0)
);
"""

CLIENTE_GENERAL_NOMBRE = "Cliente General"
TIPOS_CLIENTE = ("detalle", "mayoreo")
METODOS_PAGO = ("Efectivo", "Tarjeta", "Transferencia")


def crear_tabla():
    """Crea las tablas del módulo y garantiza que exista el 'Cliente General' (venta de mostrador)."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(SCHEMA_SQL)
        cur.execute("SELECT id FROM clientes WHERE nombre = %s LIMIT 1;", (CLIENTE_GENERAL_NOMBRE,))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO clientes (nombre, tipo_cliente) VALUES (%s, 'detalle');",
                (CLIENTE_GENERAL_NOMBRE,),
            )
    db.commit()


# --- Clientes ------------------------------------------------------------------

def obtener_clientes_activos():
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, nombre, tipo_cliente, telefono, direccion, nit, creado_en
            FROM clientes
            WHERE activo = TRUE
            ORDER BY (nombre = %s) DESC, nombre;
            """,
            (CLIENTE_GENERAL_NOMBRE,),
        )
        return cur.fetchall()


def obtener_cliente_por_id(cliente_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM clientes WHERE id = %s;", (cliente_id,))
        return cur.fetchone()


def crear_cliente(nombre, tipo_cliente, telefono=None, direccion=None, nit=None, categoria=None):
    if tipo_cliente not in TIPOS_CLIENTE:
        raise ValueError("Tipo de cliente inválido.")
    if not nombre or not nombre.strip():
        raise ValueError("El nombre del cliente es obligatorio.")

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO clientes (nombre, tipo_cliente, categoria, telefono, direccion, nit)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, nombre, tipo_cliente;
            """,
            (nombre.strip(), tipo_cliente, categoria, telefono, direccion, nit),
        )
        fila = cur.fetchone()
    db.commit()
    return fila


def actualizar_cliente(cliente_id, nombre, tipo_cliente, telefono=None, direccion=None, nit=None, categoria=None):
    if tipo_cliente not in TIPOS_CLIENTE:
        raise ValueError("Tipo de cliente inválido.")
    if not nombre or not nombre.strip():
        raise ValueError("El nombre del cliente es obligatorio.")

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE clientes
            SET nombre = %s, tipo_cliente = %s, categoria = %s, telefono = %s, direccion = %s, nit = %s
            WHERE id = %s AND activo = TRUE
            RETURNING id;
            """,
            (nombre.strip(), tipo_cliente, categoria, telefono, direccion, nit, cliente_id),
        )
        fila = cur.fetchone()
    db.commit()
    if fila is None:
        raise ValueError("El cliente no existe.")
    return fila


def eliminar_cliente(cliente_id):
    """Baja lógica (activo = FALSE): conserva el historial de ventas ya asociado a este cliente."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT nombre FROM clientes WHERE id = %s;", (cliente_id,))
        cliente = cur.fetchone()
        if cliente is None:
            raise ValueError("El cliente no existe.")
        if cliente["nombre"] == CLIENTE_GENERAL_NOMBRE:
            raise ValueError("No se puede eliminar el Cliente General (se usa para ventas de mostrador).")
        cur.execute("UPDATE clientes SET activo = FALSE WHERE id = %s;", (cliente_id,))
    db.commit()


def obtener_clientes(tipo=None, busqueda=None):
    """Listado para la pantalla de Gestión de Clientes: incluye categoría y última compra."""
    condiciones = ["c.activo = TRUE"]
    parametros = []
    if tipo:
        condiciones.append("c.tipo_cliente = %s")
        parametros.append(tipo)
    if busqueda:
        condiciones.append("(c.nombre ILIKE %s OR c.nit ILIKE %s)")
        parametros.extend([f"%{busqueda}%", f"%{busqueda}%"])

    where_sql = f"WHERE {' AND '.join(condiciones)}"
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.id, c.nombre, c.tipo_cliente, c.categoria, c.telefono, c.direccion, c.nit, c.creado_en,
                   MAX(v.creado_en) AS ultima_compra
            FROM clientes c
            LEFT JOIN ventas v ON v.cliente_id = c.id
            {where_sql}
            GROUP BY c.id
            ORDER BY (c.nombre = %s) DESC, c.nombre;
            """,
            parametros + [CLIENTE_GENERAL_NOMBRE],
        )
        return cur.fetchall()


def obtener_resumen_clientes():
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE tipo_cliente = 'mayoreo') AS total_mayoreo,
                COUNT(*) FILTER (WHERE tipo_cliente = 'detalle') AS total_detalle
            FROM clientes
            WHERE activo = TRUE;
            """
        )
        return cur.fetchone()


# --- Ventas ----------------------------------------------------------------------

def _generar_numero_venta(cur):
    hoy = datetime.now().strftime("%Y%m%d")
    cur.execute("SELECT COUNT(*) AS total FROM ventas WHERE numero_venta LIKE %s;", (f"V-{hoy}-%",))
    total = cur.fetchone()["total"]
    return f"V-{hoy}-{total + 1:04d}"


def registrar_venta(cliente_id, tipo_precio, items, metodo_pago="Efectivo", vendedor=None, usuario_id=None):
    """Procesa una venta completa: valida stock, calcula precios según tipo de cliente,
    descuenta existencias y guarda venta + detalle. Todo en una sola transacción con
    bloqueo de fila (`FOR UPDATE`) sobre cada producto, para que dos cajas cobrando al
    mismo tiempo no puedan vender más stock del que realmente existe.

    items: lista de dicts {"producto_id": int, "cantidad": float}
    """
    if tipo_precio not in TIPOS_CLIENTE:
        raise ValueError("Tipo de precio inválido.")
    if metodo_pago not in METODOS_PAGO:
        raise ValueError("Método de pago inválido.")
    if not items:
        raise ValueError("El carrito está vacío.")

    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT id FROM clientes WHERE id = %s AND activo = TRUE;", (cliente_id,))
        if cur.fetchone() is None:
            raise ValueError("El cliente seleccionado no es válido.")

        lineas = []
        alertas_stock = []
        whatsapp_activo = bool(current_app.config.get("CALLMEBOT_PHONE") and current_app.config.get("CALLMEBOT_APIKEY"))
        subtotal_total = 0.0

        for item in items:
            producto_id = item.get("producto_id")
            try:
                cantidad = float(item.get("cantidad", 0))
            except (TypeError, ValueError):
                raise ValueError("Cantidad inválida en el carrito.")

            if cantidad <= 0:
                raise ValueError("Cada línea debe tener una cantidad mayor a 0.")

            cur.execute(
                """
                SELECT id, nombre, unidad_venta, precio_detalle, precio_mayoreo, stock_actual
                FROM productos
                WHERE id = %s AND activo = TRUE
                FOR UPDATE;
                """,
                (producto_id,),
            )
            producto = cur.fetchone()
            if producto is None:
                raise ValueError(f"El producto #{producto_id} no existe o no está disponible.")

            if float(producto["stock_actual"]) < cantidad:
                raise ValueError(
                    f"Stock insuficiente para {producto['nombre']} "
                    f"(disponible: {producto['stock_actual']} {producto['unidad_venta']})."
                )

            precio_unitario = float(
                producto["precio_mayoreo"] if tipo_precio == "mayoreo" else producto["precio_detalle"]
            )
            subtotal_linea = round(precio_unitario * cantidad, 2)
            subtotal_total += subtotal_linea

            lineas.append({
                "producto_id": producto["id"],
                "nombre_producto": producto["nombre"],
                "cantidad": cantidad,
                "unidad_venta": producto["unidad_venta"],
                "precio_unitario": precio_unitario,
                "subtotal_linea": subtotal_linea,
            })

        subtotal_total = round(subtotal_total, 2)
        total = subtotal_total  # sin impuestos por ahora (ver prototipo: Impuestos 0%)
        numero_venta = _generar_numero_venta(cur)

        cur.execute(
            """
            INSERT INTO ventas
                (numero_venta, cliente_id, tipo_precio_aplicado, metodo_pago, subtotal, total, vendedor, usuario_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, numero_venta, creado_en;
            """,
            (numero_venta, cliente_id, tipo_precio, metodo_pago, subtotal_total, total, vendedor, usuario_id),
        )
        venta = cur.fetchone()

        for linea in lineas:
            cur.execute(
                """
                INSERT INTO detalle_ventas
                    (venta_id, producto_id, nombre_producto, cantidad, unidad_venta,
                     precio_unitario, subtotal_linea)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (venta["id"], linea["producto_id"], linea["nombre_producto"], linea["cantidad"],
                 linea["unidad_venta"], linea["precio_unitario"], linea["subtotal_linea"]),
            )
            cur.execute(
                """
                UPDATE productos SET stock_actual = stock_actual - %s WHERE id = %s
                RETURNING nombre, unidad_venta, stock_actual, stock_minimo;
                """,
                (linea["cantidad"], linea["producto_id"]),
            )
            restante = cur.fetchone()
            # Mismo criterio que el Dashboard/Inventario: bajo stock = en o por debajo del mínimo;
            # crítico = en o por debajo de la mitad del mínimo.
            if float(restante["stock_actual"]) <= float(restante["stock_minimo"]):
                critico = float(restante["stock_actual"]) <= float(restante["stock_minimo"]) * 0.5
                # ¿Toca avisar por WhatsApp? Solo si nunca se avisó de este producto, si ya pasó
                # el tiempo de espera, o si ahora está en nivel crítico y el último aviso no lo era.
                # El UPDATE condicional decide y registra a la vez, así dos ventas simultáneas
                # no mandan el mismo aviso dos veces. Si WhatsApp no está configurado NO se marca
                # nada: así configurarlo después no deja avisos "gastados" sin haberse enviado.
                avisar = False
                if whatsapp_activo:
                    cur.execute(
                        """
                        UPDATE productos
                        SET ultima_alerta_stock = NOW(), ultima_alerta_critica = %s
                        WHERE id = %s
                          AND (ultima_alerta_stock IS NULL
                               OR ultima_alerta_stock < NOW() - %s * interval '1 hour'
                               OR (%s AND NOT ultima_alerta_critica))
                        RETURNING id;
                        """,
                        (critico, linea["producto_id"], current_app.config.get("ALERTA_STOCK_HORAS", 6), critico),
                    )
                    avisar = cur.fetchone() is not None
                alertas_stock.append({
                    "producto_id": linea["producto_id"],
                    "nombre": restante["nombre"],
                    "unidad_venta": restante["unidad_venta"],
                    "stock_actual": float(restante["stock_actual"]),
                    "stock_minimo": float(restante["stock_minimo"]),
                    "critico": critico,
                    "avisar": avisar,
                })

    db.commit()

    return {
        "id": venta["id"],
        "numero_venta": venta["numero_venta"],
        "subtotal": subtotal_total,
        "total": total,
        "items": lineas,
        "alertas_stock": alertas_stock,
    }


def revertir_aviso_stock(producto_ids):
    """Deshace la marca de "ya avisado" cuando el WhatsApp NO se pudo enviar, para que la
    siguiente venta de ese producto lo reintente en vez de esperar las horas de espera."""
    if not producto_ids:
        return
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "UPDATE productos SET ultima_alerta_stock = NULL, ultima_alerta_critica = FALSE WHERE id = ANY(%s);",
            (list(producto_ids),),
        )
    db.commit()


def obtener_historial_ventas(busqueda=None, pagina=1, por_pagina=10):
    condiciones = []
    parametros = []
    if busqueda:
        condiciones.append("(v.numero_venta ILIKE %s OR c.nombre ILIKE %s)")
        parametros.extend([f"%{busqueda}%", f"%{busqueda}%"])

    where_sql = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    offset = (pagina - 1) * por_pagina

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS total FROM ventas v JOIN clientes c ON c.id = v.cliente_id {where_sql};",
            parametros,
        )
        total_registros = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT v.id, v.numero_venta, v.tipo_precio_aplicado, v.subtotal, v.total,
                   v.estado, v.vendedor, v.creado_en, c.nombre AS cliente_nombre
            FROM ventas v
            JOIN clientes c ON c.id = v.cliente_id
            {where_sql}
            ORDER BY v.creado_en DESC
            LIMIT %s OFFSET %s;
            """,
            parametros + [por_pagina, offset],
        )
        registros = cur.fetchall()

    return registros, total_registros


def obtener_venta_por_id(venta_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT v.*, c.nombre AS cliente_nombre, c.tipo_cliente AS cliente_tipo, c.nit AS cliente_nit
            FROM ventas v
            JOIN clientes c ON c.id = v.cliente_id
            WHERE v.id = %s;
            """,
            (venta_id,),
        )
        venta = cur.fetchone()
        if venta is None:
            return None, []

        cur.execute(
            "SELECT * FROM detalle_ventas WHERE venta_id = %s ORDER BY id;",
            (venta_id,),
        )
        detalle = cur.fetchall()

    return venta, detalle
