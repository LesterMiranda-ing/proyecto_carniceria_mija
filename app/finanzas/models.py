"""Acceso a datos del Módulo de Finanzas: Egresos Operativos y Cuadre de Ventas.

Nota sobre `ventas`: esa tabla la define app.ventas.models. Este módulo solo la
LEE (nunca la modifica) para calcular el cuadre diario y la rentabilidad — es
la misma base de datos, y Finanzas únicamente agrega lo que le falta al
negocio: el lado de los egresos y el cruce venta-gasto por día.
"""

from app.db import get_db

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS egresos (
    id                  SERIAL PRIMARY KEY,
    fecha               DATE NOT NULL DEFAULT CURRENT_DATE,
    monto               NUMERIC(10, 2) NOT NULL CHECK (monto > 0),
    categoria           VARCHAR(50) NOT NULL,
    descripcion         VARCHAR(255) NOT NULL,
    comprobante_archivo VARCHAR(255),
    registrado_por      VARCHAR(150),
    usuario_id          INTEGER REFERENCES usuarios(id),
    creado_en           TIMESTAMP NOT NULL DEFAULT NOW()
);
ALTER TABLE egresos ADD COLUMN IF NOT EXISTS usuario_id INTEGER REFERENCES usuarios(id);
"""

CATEGORIAS_EGRESO = ("Luz", "Agua", "Salarios", "Transporte", "Mantenimiento", "Compra de Insumos", "Otros")


def crear_tabla():
    db = get_db()
    with db.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    db.commit()


# --- Egresos -----------------------------------------------------------------

def crear_egreso(fecha, monto, categoria, descripcion, comprobante_archivo=None, registrado_por=None, usuario_id=None):
    if categoria not in CATEGORIAS_EGRESO:
        raise ValueError("Selecciona una categoría válida.")
    if not descripcion or not descripcion.strip():
        raise ValueError("La descripción del gasto es obligatoria.")
    if monto is None or monto <= 0:
        raise ValueError("El monto debe ser mayor a 0.")

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO egresos (fecha, monto, categoria, descripcion, comprobante_archivo, registrado_por, usuario_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (fecha, monto, categoria, descripcion.strip(), comprobante_archivo, registrado_por, usuario_id),
        )
        fila = cur.fetchone()
    db.commit()
    return fila


def obtener_gastos_recientes(limite=5):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, fecha, monto, categoria, descripcion, comprobante_archivo, registrado_por
            FROM egresos
            ORDER BY fecha DESC, creado_en DESC
            LIMIT %s;
            """,
            (limite,),
        )
        return cur.fetchall()


def obtener_egresos(fecha_desde=None, fecha_hasta=None, pagina=1, por_pagina=15):
    condiciones = []
    parametros = []
    if fecha_desde:
        condiciones.append("fecha >= %s")
        parametros.append(fecha_desde)
    if fecha_hasta:
        condiciones.append("fecha <= %s")
        parametros.append(fecha_hasta)

    where_sql = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    offset = (pagina - 1) * por_pagina

    db = get_db()
    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM egresos {where_sql};", parametros)
        total_registros = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT id, fecha, monto, categoria, descripcion, comprobante_archivo, registrado_por, creado_en
            FROM egresos
            {where_sql}
            ORDER BY fecha DESC, creado_en DESC
            LIMIT %s OFFSET %s;
            """,
            parametros + [por_pagina, offset],
        )
        registros = cur.fetchall()

    return registros, total_registros


def obtener_egreso(egreso_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM egresos WHERE id = %s;", (egreso_id,))
        return cur.fetchone()


def eliminar_egreso(egreso_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("DELETE FROM egresos WHERE id = %s RETURNING id;", (egreso_id,))
        fila = cur.fetchone()
    db.commit()
    if fila is None:
        raise ValueError("El gasto no existe.")


# --- Cuadre de ventas / rentabilidad ------------------------------------------

def obtener_resumen_periodo(fecha_desde, fecha_hasta):
    """Totales del rango: ventas (solo 'Completada'), egresos y la rentabilidad neta."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
                COALESCE((SELECT SUM(total) FROM ventas
                          WHERE estado = 'Completada' AND creado_en::date BETWEEN %s AND %s), 0) AS ventas_totales,
                COALESCE((SELECT SUM(monto) FROM egresos
                          WHERE fecha BETWEEN %s AND %s), 0) AS egresos_totales;
            """,
            (fecha_desde, fecha_hasta, fecha_desde, fecha_hasta),
        )
        fila = cur.fetchone()

    ventas_totales = float(fila["ventas_totales"])
    egresos_totales = float(fila["egresos_totales"])
    return {
        "ventas_totales": ventas_totales,
        "egresos_totales": egresos_totales,
        "rentabilidad_neta": round(ventas_totales - egresos_totales, 2),
    }


def obtener_cuadre_diario(fecha_desde, fecha_hasta):
    """Una fila por cada día del rango: venta bruta, gasto operativo y balance neto."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT d.fecha,
                   COALESCE(v.venta_bruta, 0) AS venta_bruta,
                   COALESCE(e.gasto_operativo, 0) AS gasto_operativo,
                   COALESCE(v.venta_bruta, 0) - COALESCE(e.gasto_operativo, 0) AS balance
            FROM (SELECT generate_series(%s::timestamp, %s::timestamp, interval '1 day')::date AS fecha) d
            LEFT JOIN (
                SELECT creado_en::date AS fecha, SUM(total) AS venta_bruta
                FROM ventas
                WHERE estado = 'Completada' AND creado_en::date BETWEEN %s AND %s
                GROUP BY creado_en::date
            ) v ON v.fecha = d.fecha
            LEFT JOIN (
                SELECT fecha, SUM(monto) AS gasto_operativo
                FROM egresos
                WHERE fecha BETWEEN %s AND %s
                GROUP BY fecha
            ) e ON e.fecha = d.fecha
            ORDER BY d.fecha DESC;
            """,
            (fecha_desde, fecha_hasta, fecha_desde, fecha_hasta, fecha_desde, fecha_hasta),
        )
        return cur.fetchall()
