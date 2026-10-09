"""Acceso a datos del Módulo de Entrada de Canal (tabla `entradas_canal`)."""

from app.db import get_db

# DDL de la tabla. Se ejecuta una sola vez (idempotente gracias a IF NOT EXISTS).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entradas_canal (
    id                  SERIAL PRIMARY KEY,
    numero_lote         VARCHAR(30) UNIQUE NOT NULL,
    fecha_entrada       DATE NOT NULL DEFAULT CURRENT_DATE,
    proveedor           VARCHAR(150) NOT NULL,
    peso_lbs            NUMERIC(10, 2) NOT NULL CHECK (peso_lbs > 0),
    costo_por_libra     NUMERIC(10, 2) NOT NULL CHECK (costo_por_libra >= 0),
    costo_total         NUMERIC(12, 2) NOT NULL CHECK (costo_total >= 0),
    factura_archivo     VARCHAR(255),
    estado              VARCHAR(30) NOT NULL DEFAULT 'En Cuarto Frío',
    registrado_por      VARCHAR(150),
    usuario_id          INTEGER REFERENCES usuarios(id),
    creado_en           TIMESTAMP NOT NULL DEFAULT NOW()
);
ALTER TABLE entradas_canal ADD COLUMN IF NOT EXISTS usuario_id INTEGER REFERENCES usuarios(id);
"""

ESTADOS_VALIDOS = ("En Cuarto Frío", "Procesado", "Observación")

# --- Catálogo de Proveedores ------------------------------------------------
# `entradas_canal.proveedor` sigue guardando el NOMBRE como texto (sin FK) para no tocar el
# historial: renombrar un proveedor aquí no reescribe lotes ya registrados.

SCHEMA_SQL_PROVEEDORES = """
CREATE TABLE IF NOT EXISTS proveedores (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(150) NOT NULL,
    telefono        VARCHAR(30),
    nit             VARCHAR(20),
    direccion       VARCHAR(255),
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    registrado_por  VARCHAR(150),
    usuario_id      INTEGER REFERENCES usuarios(id),
    creado_en       TIMESTAMP NOT NULL DEFAULT NOW()
);
-- Un nombre por proveedor activo, sin distinguir mayúsculas.
CREATE UNIQUE INDEX IF NOT EXISTS uq_proveedores_nombre_activo ON proveedores (lower(nombre)) WHERE activo;
"""

# --- Módulo de Desposte y Control de Merma ---------------------------------

SCHEMA_SQL_DESPOSTE = """
CREATE TABLE IF NOT EXISTS despostes (
    id                          SERIAL PRIMARY KEY,
    entrada_canal_id            INTEGER NOT NULL UNIQUE REFERENCES entradas_canal(id),
    fecha_desposte               TIMESTAMP NOT NULL DEFAULT NOW(),
    peso_inicial_lbs            NUMERIC(10, 2) NOT NULL CHECK (peso_inicial_lbs > 0),
    peso_cortes_lbs             NUMERIC(10, 2) NOT NULL CHECK (peso_cortes_lbs >= 0),
    peso_merma_declarada_lbs    NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (peso_merma_declarada_lbs >= 0),
    peso_tara_lbs               NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (peso_tara_lbs >= 0),
    merma_lbs                   NUMERIC(10, 2) NOT NULL,
    rendimiento_pct             NUMERIC(5, 2) NOT NULL,
    merma_pct                   NUMERIC(5, 2) NOT NULL,
    registrado_por              VARCHAR(150),
    usuario_id                  INTEGER REFERENCES usuarios(id),
    creado_en                   TIMESTAMP NOT NULL DEFAULT NOW()
);
ALTER TABLE despostes ADD COLUMN IF NOT EXISTS usuario_id INTEGER REFERENCES usuarios(id);

CREATE TABLE IF NOT EXISTS desposte_detalle (
    id              SERIAL PRIMARY KEY,
    desposte_id     INTEGER NOT NULL REFERENCES despostes(id) ON DELETE CASCADE,
    tipo_corte      VARCHAR(100) NOT NULL,
    categoria       VARCHAR(20) NOT NULL CHECK (categoria IN ('corte', 'subproducto', 'merma')),
    peso_lbs        NUMERIC(10, 2) NOT NULL CHECK (peso_lbs >= 0)
);

CREATE TABLE IF NOT EXISTS desposte_tara (
    id                  SERIAL PRIMARY KEY,
    desposte_id         INTEGER NOT NULL REFERENCES despostes(id) ON DELETE CASCADE,
    item                VARCHAR(50) NOT NULL,
    cantidad            INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
    peso_unitario_lbs   NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (peso_unitario_lbs >= 0),
    subtotal_lbs        NUMERIC(10, 2) NOT NULL DEFAULT 0
);
"""

# Catálogo de cortes esperados por canal de res. "campo" se usa como sufijo fijo
# en los <input name="corte_<campo>"> del formulario, para no depender de slugs
# calculados en dos lugares distintos (Python y Jinja).
TIPOS_CORTE = (
    {"campo": "posta_pulpa", "nombre": "Postas", "categoria": "corte", "etiqueta": "Clasificado"},
    {"campo": "costilla", "nombre": "Costillar y Espinazo", "categoria": "corte", "etiqueta": "Con Hueso"},
    {"campo": "bistec_lomo", "nombre": "Bistec / Lomo", "categoria": "corte", "etiqueta": "Piezas"},
    {"campo": "hueso_blanco", "nombre": "Hueso / Blanco", "categoria": "subproducto", "etiqueta": "Subproducto"},
    {"campo": "merma_grasa", "nombre": "Desperdicio", "categoria": "merma", "etiqueta": "Merma"},
)

# Catálogo de tara (peso de empaque que se descuenta del total pesado).
TIPOS_TARA = (
    {"campo": "cajas", "item": "Cajas Plásticas", "peso_unitario_defecto": 1.20},
    {"campo": "bandejas", "item": "Bandejas", "peso_unitario_defecto": 0.45},
    {"campo": "ganchos", "item": "Ganchos", "peso_unitario_defecto": 0.80},
)

# Rendimiento mínimo esperado (%) para considerar la merma "dentro de parámetros normales".
RENDIMIENTO_MINIMO_ESPERADO = 90.0

# --- Catálogo de Productos / Stock ------------------------------------------
# El stock vendible (tabla `productos`) vive en el módulo de inventario porque
# es el mismo dominio que ya controla entradas de canal y desposte (ver
# ARQUITECTURA_Y_REGLAS.md). El módulo de ventas (app/ventas/) solo LEE esta
# tabla para el catálogo del POS y la actualiza (resta stock) al facturar.

SCHEMA_SQL_PRODUCTOS = """
CREATE TABLE IF NOT EXISTS productos (
    id                  SERIAL PRIMARY KEY,
    codigo              VARCHAR(20) UNIQUE NOT NULL,
    nombre              VARCHAR(150) NOT NULL,
    categoria           VARCHAR(30) NOT NULL DEFAULT 'Res',
    descripcion         TEXT,
    unidad_venta        VARCHAR(10) NOT NULL DEFAULT 'lb' CHECK (unidad_venta IN ('lb', 'unidad')),
    costo               NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (costo >= 0),
    precio_detalle      NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (precio_detalle >= 0),
    precio_mayoreo      NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (precio_mayoreo >= 0),
    stock_actual        NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (stock_actual >= 0),
    stock_minimo        NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (stock_minimo >= 0),
    foto_archivo        VARCHAR(255),
    desposte_origen_id  INTEGER REFERENCES despostes(id),
    activo              BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en           TIMESTAMP NOT NULL DEFAULT NOW()
);
ALTER TABLE productos ADD COLUMN IF NOT EXISTS descripcion TEXT;
ALTER TABLE productos ADD COLUMN IF NOT EXISTS costo NUMERIC(10, 2) NOT NULL DEFAULT 0;
ALTER TABLE productos ADD COLUMN IF NOT EXISTS foto_archivo VARCHAR(255);
-- Control de avisos por WhatsApp: cuándo se avisó por última vez de este producto y en qué nivel.
ALTER TABLE productos ADD COLUMN IF NOT EXISTS ultima_alerta_stock TIMESTAMP;
ALTER TABLE productos ADD COLUMN IF NOT EXISTS ultima_alerta_critica BOOLEAN NOT NULL DEFAULT FALSE;
"""

# "Especialidades" cubre productos que no son un corte crudo de res/cerdo/pollo ni
# embutido (salsas, condimentos, preparados de la casa, etc.).
CATEGORIAS_PRODUCTO = ("Res", "Cerdo", "Pollo", "Embutidos", "Especialidades")

# Prefijo del código autogenerado por categoría (C-001, E-012, etc. — como en el prototipo).
PREFIJO_CODIGO_POR_CATEGORIA = {
    "Res": "C",
    "Cerdo": "P",
    "Pollo": "A",
    "Embutidos": "E",
    "Especialidades": "S",
}

# Precio de detalle sugerido por corte cuando el desposte genera el producto automáticamente.
# El precio de mayoreo por defecto aplica un descuento fijo (ver DESCUENTO_MAYOREO_DEFECTO).
# Son valores iniciales editables luego por el administrador — no hay lista de precios oficial.
PRECIOS_SUGERIDOS_CORTE = {
    "Postas": 9.50,
    "Costillar y Espinazo": 6.50,
    "Bistec / Lomo": 11.00,
    "Hueso / Blanco": 2.00,
}
DESCUENTO_MAYOREO_DEFECTO = 0.88  # 12% menos que el precio de detalle


def crear_tabla():
    """Crea las tablas del módulo (entrada de canal + desposte + productos) si no existen."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(SCHEMA_SQL)
        cur.execute(SCHEMA_SQL_DESPOSTE)
        cur.execute(SCHEMA_SQL_PRODUCTOS)

        # Solo la primera vez que se crea la tabla de proveedores: se cargan los nombres que ya
        # aparecen en el historial de entradas (así no empieza vacía). Después no se vuelve a sembrar,
        # para no resucitar proveedores dados de baja ni catalogar nombres escritos a mano.
        cur.execute("SELECT to_regclass('proveedores') AS tabla;")
        es_nueva = cur.fetchone()["tabla"] is None
        cur.execute(SCHEMA_SQL_PROVEEDORES)
        if es_nueva:
            cur.execute(
                """
                INSERT INTO proveedores (nombre)
                SELECT DISTINCT ON (lower(trim(proveedor))) trim(proveedor)
                FROM entradas_canal
                WHERE trim(proveedor) <> ''
                ORDER BY lower(trim(proveedor)), id;
                """
            )
    db.commit()


def _validar_proveedor(nombre, telefono, nit, direccion):
    nombre = (nombre or "").strip()
    telefono = (telefono or "").strip() or None
    nit = (nit or "").strip() or None
    direccion = (direccion or "").strip() or None
    if not nombre:
        raise ValueError("El nombre del proveedor es obligatorio.")
    for etiqueta, valor, maximo in (("El nombre", nombre, 150), ("El teléfono", telefono, 30),
                                    ("El NIT", nit, 20), ("La dirección", direccion, 255)):
        if valor and len(valor) > maximo:
            raise ValueError(f"{etiqueta} no puede pasar de {maximo} caracteres.")
    return nombre, telefono, nit, direccion


def _nombre_proveedor_en_uso(cur, nombre, excluir_id=None):
    cur.execute(
        "SELECT 1 FROM proveedores WHERE lower(nombre) = lower(%s) AND activo = TRUE AND id <> %s;",
        (nombre, excluir_id or 0),
    )
    return cur.fetchone() is not None


def crear_proveedor(nombre, telefono=None, nit=None, direccion=None, registrado_por=None, usuario_id=None):
    nombre, telefono, nit, direccion = _validar_proveedor(nombre, telefono, nit, direccion)
    db = get_db()
    with db.cursor() as cur:
        if _nombre_proveedor_en_uso(cur, nombre):
            raise ValueError(f"Ya existe un proveedor llamado «{nombre}».")
        cur.execute(
            """
            INSERT INTO proveedores (nombre, telefono, nit, direccion, registrado_por, usuario_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, nombre;
            """,
            (nombre, telefono, nit, direccion, registrado_por, usuario_id),
        )
        fila = cur.fetchone()
    db.commit()
    return fila


def actualizar_proveedor(proveedor_id, nombre, telefono=None, nit=None, direccion=None):
    nombre, telefono, nit, direccion = _validar_proveedor(nombre, telefono, nit, direccion)
    db = get_db()
    with db.cursor() as cur:
        if _nombre_proveedor_en_uso(cur, nombre, excluir_id=proveedor_id):
            raise ValueError(f"Ya existe otro proveedor llamado «{nombre}».")
        cur.execute(
            """
            UPDATE proveedores SET nombre = %s, telefono = %s, nit = %s, direccion = %s
            WHERE id = %s AND activo = TRUE RETURNING id;
            """,
            (nombre, telefono, nit, direccion, proveedor_id),
        )
        fila = cur.fetchone()
    db.commit()
    if fila is None:
        raise ValueError("El proveedor no existe.")
    return fila


def eliminar_proveedor(proveedor_id):
    """Baja lógica: los lotes ya registrados con este proveedor conservan su nombre."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute("UPDATE proveedores SET activo = FALSE WHERE id = %s AND activo = TRUE RETURNING id;", (proveedor_id,))
        fila = cur.fetchone()
    db.commit()
    if fila is None:
        raise ValueError("El proveedor no existe.")


def obtener_proveedor_por_id(proveedor_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM proveedores WHERE id = %s AND activo = TRUE;", (proveedor_id,))
        return cur.fetchone()


def obtener_nombres_proveedores():
    """Para las sugerencias del campo Proveedor en Entrada de Canal."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT nombre FROM proveedores WHERE activo = TRUE ORDER BY lower(nombre);")
        return [f["nombre"] for f in cur.fetchall()]


def obtener_proveedores(busqueda=None):
    """Listado con cuántos lotes se le han comprado y cuándo fue la última entrada."""
    condiciones = ["p.activo = TRUE"]
    parametros = []
    if busqueda:
        condiciones.append("(p.nombre ILIKE %s OR p.nit ILIKE %s)")
        parametros.extend([f"%{busqueda}%", f"%{busqueda}%"])
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT p.id, p.nombre, p.telefono, p.nit, p.direccion, p.creado_en,
                   COUNT(ec.id) AS lotes, MAX(ec.fecha_entrada) AS ultima_entrada
            FROM proveedores p
            LEFT JOIN entradas_canal ec ON lower(trim(ec.proveedor)) = lower(p.nombre)
            WHERE {' AND '.join(condiciones)}
            GROUP BY p.id
            ORDER BY lower(p.nombre);
            """,
            parametros,
        )
        return cur.fetchall()


def generar_numero_lote(fecha_entrada):
    """Genera un número de lote único con el formato LT-DDMM-<secuencia del día>."""
    db = get_db()
    prefijo = f"LT-{fecha_entrada.strftime('%d%m')}"
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS total FROM entradas_canal WHERE numero_lote LIKE %s",
            (f"{prefijo}-%",),
        )
        total = cur.fetchone()["total"]
    secuencia = chr(ord("A") + total) if total < 26 else str(total + 1)
    return f"{prefijo}-{secuencia}"


def insertar_entrada(fecha_entrada, proveedor, peso_lbs, costo_por_libra, factura_archivo=None,
                      registrado_por=None, usuario_id=None):
    """Inserta un nuevo ingreso de canal calculando el costo total (peso * costo/libra)."""
    costo_total = round(float(peso_lbs) * float(costo_por_libra), 2)
    numero_lote = generar_numero_lote(fecha_entrada)

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entradas_canal
                (numero_lote, fecha_entrada, proveedor, peso_lbs, costo_por_libra,
                 costo_total, factura_archivo, registrado_por, usuario_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, numero_lote, costo_total;
            """,
            (numero_lote, fecha_entrada, proveedor, peso_lbs, costo_por_libra,
             costo_total, factura_archivo, registrado_por, usuario_id),
        )
        fila = cur.fetchone()
    db.commit()
    return fila


def obtener_ultimos_ingresos(limite=5):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, numero_lote, fecha_entrada, proveedor, peso_lbs,
                   costo_por_libra, costo_total, estado
            FROM entradas_canal
            ORDER BY creado_en DESC
            LIMIT %s;
            """,
            (limite,),
        )
        return cur.fetchall()


def obtener_peso_promedio():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT AVG(peso_lbs) AS promedio FROM entradas_canal;")
        fila = cur.fetchone()
        return round(float(fila["promedio"]), 1) if fila["promedio"] is not None else 0.0


def contar_entradas():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM entradas_canal;")
        return cur.fetchone()["total"]


def obtener_historial(fecha_desde=None, fecha_hasta=None, busqueda=None, pagina=1, por_pagina=10):
    """Lista paginada del historial con filtros opcionales de fecha y texto (proveedor/lote)."""
    condiciones = []
    parametros = []

    if fecha_desde:
        condiciones.append("fecha_entrada >= %s")
        parametros.append(fecha_desde)
    if fecha_hasta:
        condiciones.append("fecha_entrada <= %s")
        parametros.append(fecha_hasta)
    if busqueda:
        condiciones.append("(proveedor ILIKE %s OR numero_lote ILIKE %s)")
        parametros.extend([f"%{busqueda}%", f"%{busqueda}%"])

    where_sql = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    offset = (pagina - 1) * por_pagina

    db = get_db()
    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM entradas_canal {where_sql};", parametros)
        total_registros = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT id, numero_lote, fecha_entrada, proveedor, peso_lbs,
                   costo_por_libra, costo_total, estado, registrado_por, creado_en
            FROM entradas_canal
            {where_sql}
            ORDER BY creado_en DESC
            LIMIT %s OFFSET %s;
            """,
            parametros + [por_pagina, offset],
        )
        registros = cur.fetchall()

    return registros, total_registros


def obtener_entrada_por_id(entrada_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM entradas_canal WHERE id = %s;", (entrada_id,))
        return cur.fetchone()


# --- Desposte ----------------------------------------------------------------

def obtener_canales_pendientes_desposte():
    """Canales que ya ingresaron pero todavía no tienen un desposte registrado."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT ec.id, ec.numero_lote, ec.proveedor, ec.fecha_entrada, ec.peso_lbs
            FROM entradas_canal ec
            WHERE NOT EXISTS (SELECT 1 FROM despostes d WHERE d.entrada_canal_id = ec.id)
            ORDER BY ec.creado_en DESC;
            """
        )
        return cur.fetchall()


def registrar_desposte(entrada_canal_id, cortes, tara_items, registrado_por=None, usuario_id=None):
    """Registra el desposte de un canal: guarda el detalle, calcula rendimiento/merma
    y marca el canal como 'Procesado'.

    cortes: lista de dicts {tipo_corte, categoria, peso_lbs}
    tara_items: lista de dicts {item, cantidad, peso_unitario_lbs}

    Reglas de cálculo:
      - peso_cortes_lbs (aprovechable) = suma de las líneas con categoría 'corte' o 'subproducto'.
      - peso_merma_declarada_lbs = suma de las líneas con categoría 'merma' (grasa/recorte sin uso).
      - peso_tara_lbs = suma de (cantidad * peso unitario) de cajas/bandejas/ganchos: se pesaron
        junto con el producto, así que se descuentan del total.
      - merma_lbs = peso_inicial - (peso_cortes + peso_merma_declarada - peso_tara): incluye la
        merma declarada MÁS cualquier diferencia no explicada (evaporación, manejo, redondeo).
      - rendimiento_pct = peso_cortes_lbs / peso_inicial_lbs * 100 (solo lo aprovechable/vendible).
    """
    canal = obtener_entrada_por_id(entrada_canal_id)
    if canal is None:
        raise ValueError("El canal seleccionado no existe.")
    if canal["estado"] == "Procesado":
        raise ValueError("Este canal ya tiene un desposte registrado.")

    peso_inicial = float(canal["peso_lbs"])

    peso_cortes = round(sum(c["peso_lbs"] for c in cortes if c["categoria"] in ("corte", "subproducto")), 2)
    peso_merma_declarada = round(sum(c["peso_lbs"] for c in cortes if c["categoria"] == "merma"), 2)
    peso_tara = round(sum(t["cantidad"] * t["peso_unitario_lbs"] for t in tara_items), 2)

    peso_registrado_neto = peso_cortes + peso_merma_declarada - peso_tara
    merma_lbs = round(peso_inicial - peso_registrado_neto, 2)
    rendimiento_pct = round((peso_cortes / peso_inicial) * 100, 2) if peso_inicial else 0.0
    merma_pct = round((merma_lbs / peso_inicial) * 100, 2) if peso_inicial else 0.0

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO despostes
                (entrada_canal_id, peso_inicial_lbs, peso_cortes_lbs, peso_merma_declarada_lbs,
                 peso_tara_lbs, merma_lbs, rendimiento_pct, merma_pct, registrado_por, usuario_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (entrada_canal_id, peso_inicial, peso_cortes, peso_merma_declarada,
             peso_tara, merma_lbs, rendimiento_pct, merma_pct, registrado_por, usuario_id),
        )
        desposte_id = cur.fetchone()["id"]

        for corte in cortes:
            if corte["peso_lbs"] <= 0:
                continue
            cur.execute(
                """
                INSERT INTO desposte_detalle (desposte_id, tipo_corte, categoria, peso_lbs)
                VALUES (%s, %s, %s, %s);
                """,
                (desposte_id, corte["tipo_corte"], corte["categoria"], corte["peso_lbs"]),
            )
            # La merma/grasa no es vendible: no genera stock. Corte y subproducto sí.
            if corte["categoria"] in ("corte", "subproducto"):
                _generar_o_actualizar_producto(cur, corte["tipo_corte"], corte["peso_lbs"], desposte_id)

        for tara in tara_items:
            if tara["cantidad"] <= 0:
                continue
            subtotal = round(tara["cantidad"] * tara["peso_unitario_lbs"], 2)
            cur.execute(
                """
                INSERT INTO desposte_tara (desposte_id, item, cantidad, peso_unitario_lbs, subtotal_lbs)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (desposte_id, tara["item"], tara["cantidad"], tara["peso_unitario_lbs"], subtotal),
            )

        cur.execute("UPDATE entradas_canal SET estado = 'Procesado' WHERE id = %s;", (entrada_canal_id,))

    db.commit()

    return {
        "id": desposte_id,
        "peso_inicial_lbs": peso_inicial,
        "peso_cortes_lbs": peso_cortes,
        "peso_merma_declarada_lbs": peso_merma_declarada,
        "peso_tara_lbs": peso_tara,
        "merma_lbs": merma_lbs,
        "rendimiento_pct": rendimiento_pct,
        "merma_pct": merma_pct,
    }


def obtener_historial_desposte(busqueda=None, pagina=1, por_pagina=10):
    condiciones = []
    parametros = []
    if busqueda:
        condiciones.append("(ec.proveedor ILIKE %s OR ec.numero_lote ILIKE %s)")
        parametros.extend([f"%{busqueda}%", f"%{busqueda}%"])

    where_sql = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    offset = (pagina - 1) * por_pagina

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM despostes d
            JOIN entradas_canal ec ON ec.id = d.entrada_canal_id
            {where_sql};
            """,
            parametros,
        )
        total_registros = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT d.id, d.fecha_desposte, d.peso_inicial_lbs, d.peso_cortes_lbs,
                   d.peso_merma_declarada_lbs, d.peso_tara_lbs, d.merma_lbs,
                   d.rendimiento_pct, d.merma_pct, d.registrado_por,
                   ec.numero_lote, ec.proveedor
            FROM despostes d
            JOIN entradas_canal ec ON ec.id = d.entrada_canal_id
            {where_sql}
            ORDER BY d.creado_en DESC
            LIMIT %s OFFSET %s;
            """,
            parametros + [por_pagina, offset],
        )
        registros = cur.fetchall()

    return registros, total_registros


def obtener_desposte_por_id(desposte_id):
    """Encabezado + detalle de cortes + detalle de tara de un desposte específico."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT d.*, ec.numero_lote, ec.proveedor, ec.fecha_entrada
            FROM despostes d
            JOIN entradas_canal ec ON ec.id = d.entrada_canal_id
            WHERE d.id = %s;
            """,
            (desposte_id,),
        )
        encabezado = cur.fetchone()
        if encabezado is None:
            return None, [], []

        cur.execute(
            "SELECT tipo_corte, categoria, peso_lbs FROM desposte_detalle WHERE desposte_id = %s ORDER BY id;",
            (desposte_id,),
        )
        detalle = cur.fetchall()

        cur.execute(
            "SELECT item, cantidad, peso_unitario_lbs, subtotal_lbs FROM desposte_tara WHERE desposte_id = %s ORDER BY id;",
            (desposte_id,),
        )
        tara = cur.fetchall()

    return encabezado, detalle, tara


# --- Productos / Stock --------------------------------------------------------

def generar_codigo_producto(cur, categoria):
    """Genera un código único tipo C-001, E-012, etc. según la categoría."""
    prefijo = PREFIJO_CODIGO_POR_CATEGORIA.get(categoria, "O")
    cur.execute(
        "SELECT COUNT(*) AS total FROM productos WHERE codigo LIKE %s;",
        (f"{prefijo}-%",),
    )
    total = cur.fetchone()["total"]
    return f"{prefijo}-{total + 1:03d}"


def _generar_o_actualizar_producto(cur, tipo_corte, peso_lbs, desposte_id):
    """Crea o incrementa el stock de un producto a partir de una línea de desposte.

    Se llama DENTRO de la transacción de `registrar_desposte`, reutilizando el
    mismo cursor, para que el stock generado sea parte atómica del desposte.
    Si ya existe un producto con ese nombre (comparación insensible a mayúsculas),
    simplemente se incrementa su stock; si no, se crea con precios sugeridos.
    """
    cur.execute("SELECT id, stock_actual FROM productos WHERE lower(nombre) = lower(%s);", (tipo_corte,))
    existente = cur.fetchone()

    if existente:
        # Si la reposición lo saca del nivel bajo, el aviso por WhatsApp se reinicia: la próxima
        # vez que baje del mínimo se avisará aunque no hayan pasado las horas de espera.
        cur.execute(
            """
            UPDATE productos
            SET stock_actual = stock_actual + %s,
                ultima_alerta_stock = CASE WHEN stock_actual + %s > stock_minimo THEN NULL ELSE ultima_alerta_stock END,
                ultima_alerta_critica = CASE WHEN stock_actual + %s > stock_minimo THEN FALSE ELSE ultima_alerta_critica END
            WHERE id = %s;
            """,
            (peso_lbs, peso_lbs, peso_lbs, existente["id"]),
        )
        return existente["id"]

    precio_detalle = PRECIOS_SUGERIDOS_CORTE.get(tipo_corte, 0)
    precio_mayoreo = round(precio_detalle * DESCUENTO_MAYOREO_DEFECTO, 2)
    codigo = generar_codigo_producto(cur, "Res")

    cur.execute(
        """
        INSERT INTO productos
            (codigo, nombre, categoria, unidad_venta, precio_detalle, precio_mayoreo,
             stock_actual, stock_minimo, desposte_origen_id)
        VALUES (%s, %s, 'Res', 'lb', %s, %s, %s, 10, %s)
        RETURNING id;
        """,
        (codigo, tipo_corte, precio_detalle, precio_mayoreo, peso_lbs, desposte_id),
    )
    return cur.fetchone()["id"]


def crear_producto(nombre, categoria, unidad_venta, precio_detalle, precio_mayoreo,
                    stock_actual=0, stock_minimo=0, descripcion=None, costo=0, foto_archivo=None):
    """Alta manual de un producto (ej. embutidos que no vienen de un desposte)."""
    db = get_db()
    with db.cursor() as cur:
        codigo = generar_codigo_producto(cur, categoria)
        cur.execute(
            """
            INSERT INTO productos
                (codigo, nombre, categoria, descripcion, unidad_venta, costo, precio_detalle,
                 precio_mayoreo, stock_actual, stock_minimo, foto_archivo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, codigo;
            """,
            (codigo, nombre, categoria, descripcion, unidad_venta, costo, precio_detalle,
             precio_mayoreo, stock_actual, stock_minimo, foto_archivo),
        )
        fila = cur.fetchone()
    db.commit()
    return fila


def actualizar_producto(producto_id, nombre, categoria, descripcion, costo, precio_detalle,
                         precio_mayoreo, stock_minimo, foto_archivo=None):
    """Edita los datos comerciales de un producto.

    NO toca `stock_actual` (solo cambia con desposte y ventas, para no romper la trazabilidad),
    ni `unidad_venta` (cambiarla reinterpretaría el stock existente), ni el código.
    `foto_archivo=None` conserva la foto actual.
    """
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El nombre del producto es obligatorio.")
    if categoria not in CATEGORIAS_PRODUCTO:
        raise ValueError("Selecciona una categoría válida.")

    db = get_db()
    with db.cursor() as cur:
        # El desposte enlaza cortes con productos por nombre (sin distinguir mayúsculas): dos
        # productos activos con el mismo nombre harían ambigua esa búsqueda.
        cur.execute(
            "SELECT 1 FROM productos WHERE lower(nombre) = lower(%s) AND id <> %s AND activo = TRUE;",
            (nombre, producto_id),
        )
        if cur.fetchone():
            raise ValueError(f"Ya existe otro producto llamado «{nombre}».")

        cur.execute(
            """
            UPDATE productos
            SET nombre = %s, categoria = %s, descripcion = %s, costo = %s, precio_detalle = %s,
                precio_mayoreo = %s, stock_minimo = %s, foto_archivo = COALESCE(%s, foto_archivo),
                ultima_alerta_stock = CASE WHEN stock_minimo <> %s THEN NULL ELSE ultima_alerta_stock END,
                ultima_alerta_critica = CASE WHEN stock_minimo <> %s THEN FALSE ELSE ultima_alerta_critica END
            WHERE id = %s AND activo = TRUE
            RETURNING id;
            """,
            (nombre, categoria, descripcion, costo, precio_detalle, precio_mayoreo,
             stock_minimo, foto_archivo, stock_minimo, stock_minimo, producto_id),
        )
        fila = cur.fetchone()
    db.commit()
    if fila is None:
        raise ValueError("El producto no existe.")
    return fila


def obtener_productos_catalogo(categoria=None, busqueda=None):
    condiciones = ["activo = TRUE"]
    parametros = []
    if categoria:
        condiciones.append("categoria = %s")
        parametros.append(categoria)
    if busqueda:
        condiciones.append("(nombre ILIKE %s OR codigo ILIKE %s)")
        parametros.extend([f"%{busqueda}%", f"%{busqueda}%"])

    where_sql = f"WHERE {' AND '.join(condiciones)}"
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, codigo, nombre, categoria, unidad_venta, precio_detalle, precio_mayoreo,
                   stock_actual, stock_minimo, foto_archivo,
                   (stock_actual <= stock_minimo) AS stock_bajo
            FROM productos
            {where_sql}
            ORDER BY categoria, nombre;
            """,
            parametros,
        )
        return cur.fetchall()


def obtener_resumen_inventario():
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_productos,
                COALESCE(SUM(stock_actual * precio_detalle), 0) AS valor_total,
                COUNT(*) FILTER (WHERE stock_actual <= stock_minimo) AS stock_bajo
            FROM productos
            WHERE activo = TRUE;
            """
        )
        return cur.fetchone()


def obtener_productos_para_venta():
    """Productos activos para el catálogo del POS (incluye los de stock 0 para mostrarlos deshabilitados)."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, codigo, nombre, categoria, unidad_venta, precio_detalle, precio_mayoreo, stock_actual
            FROM productos
            WHERE activo = TRUE
            ORDER BY categoria, nombre;
            """
        )
        return cur.fetchall()


def obtener_producto_por_id(producto_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM productos WHERE id = %s;", (producto_id,))
        return cur.fetchone()
