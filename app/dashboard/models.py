"""Acceso a datos del Dashboard General.

Este módulo no es dueño de ninguna tabla: solo LEE datos que ya viven en
otros módulos (ventas/egresos/productos) para armar el panel de inicio. Es
el mismo patrón de lectura cruzada ya usado por app.finanzas y app.ventas.
"""

from datetime import date, datetime, timedelta

from app.db import get_db

DIAS_SEMANA = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


def _variacion_pct(actual, anterior):
    """% de cambio vs el período anterior. None si no hay base de comparación."""
    if anterior is None or anterior <= 0:
        return None
    return round(((actual - anterior) / anterior) * 100, 1)


def _formatear_hace(momento):
    if momento is None:
        return "Sin ventas registradas todavía"
    delta = datetime.now() - momento
    segundos = delta.total_seconds()
    if segundos < 60:
        return "hace unos segundos"
    minutos = int(segundos // 60)
    if minutos < 60:
        return f"hace {minutos} min"
    horas = int(minutos // 60)
    if horas < 24:
        return f"hace {horas} h"
    dias = int(horas // 24)
    return f"hace {dias} d"


def obtener_resumen_hoy():
    hoy = date.today()
    ayer = hoy - timedelta(days=1)

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
                COALESCE((SELECT SUM(total) FROM ventas
                          WHERE estado = 'Completada' AND creado_en::date = %s), 0) AS ventas_hoy,
                COALESCE((SELECT SUM(total) FROM ventas
                          WHERE estado = 'Completada' AND creado_en::date = %s), 0) AS ventas_ayer,
                COALESCE((SELECT SUM(monto) FROM egresos WHERE fecha = %s), 0) AS gastos_hoy,
                COALESCE((SELECT SUM(monto) FROM egresos WHERE fecha = %s), 0) AS gastos_ayer,
                (SELECT MAX(creado_en) FROM ventas WHERE estado = 'Completada') AS ultima_venta_en;
            """,
            (hoy, ayer, hoy, ayer),
        )
        fila = cur.fetchone()

    ventas_hoy = float(fila["ventas_hoy"])
    ventas_ayer = float(fila["ventas_ayer"])
    gastos_hoy = float(fila["gastos_hoy"])
    gastos_ayer = float(fila["gastos_ayer"])
    utilidad_neta = round(ventas_hoy - gastos_hoy, 2)

    return {
        "ventas_hoy": ventas_hoy,
        "variacion_ventas": _variacion_pct(ventas_hoy, ventas_ayer),
        "gastos_hoy": gastos_hoy,
        "variacion_gastos": _variacion_pct(gastos_hoy, gastos_ayer),
        "utilidad_neta": utilidad_neta,
        "margen_pct": round((utilidad_neta / ventas_hoy) * 100, 1) if ventas_hoy > 0 else 0.0,
        "ultima_venta_texto": _formatear_hace(fila["ultima_venta_en"]),
    }


def obtener_flujo_caja_semana():
    """Ingresos (ventas) vs egresos por día, últimos 7 días (incluye hoy)."""
    hoy = date.today()
    desde = hoy - timedelta(days=6)

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT d.fecha,
                   COALESCE(v.ingresos, 0) AS ingresos,
                   COALESCE(e.egresos, 0) AS egresos
            FROM (SELECT generate_series(%s::timestamp, %s::timestamp, interval '1 day')::date AS fecha) d
            LEFT JOIN (
                SELECT creado_en::date AS fecha, SUM(total) AS ingresos
                FROM ventas
                WHERE estado = 'Completada' AND creado_en::date BETWEEN %s AND %s
                GROUP BY creado_en::date
            ) v ON v.fecha = d.fecha
            LEFT JOIN (
                SELECT fecha, SUM(monto) AS egresos
                FROM egresos
                WHERE fecha BETWEEN %s AND %s
                GROUP BY fecha
            ) e ON e.fecha = d.fecha
            ORDER BY d.fecha;
            """,
            (desde, hoy, desde, hoy, desde, hoy),
        )
        filas = cur.fetchall()

    dias = []
    max_valor = 0.0
    for fila in filas:
        ingresos = float(fila["ingresos"])
        egresos = float(fila["egresos"])
        max_valor = max(max_valor, ingresos, egresos)
        dias.append({
            "fecha": fila["fecha"],
            "etiqueta": DIAS_SEMANA[fila["fecha"].weekday()],
            "es_hoy": fila["fecha"] == hoy,
            "ingresos": ingresos,
            "egresos": egresos,
        })

    for dia in dias:
        dia["ingresos_pct"] = round((dia["ingresos"] / max_valor) * 100, 1) if max_valor > 0 else 0
        dia["egresos_pct"] = round((dia["egresos"] / max_valor) * 100, 1) if max_valor > 0 else 0

    return dias


def obtener_alertas_stock(limite=5):
    """Productos en o por debajo de su stock mínimo, del más crítico al menos crítico."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, nombre, unidad_venta, stock_actual, stock_minimo,
                   (stock_actual <= stock_minimo * 0.5) AS critico
            FROM productos
            WHERE activo = TRUE AND stock_actual <= stock_minimo
            ORDER BY (stock_actual - stock_minimo) ASC
            LIMIT %s;
            """,
            (limite,),
        )
        return cur.fetchall()


def obtener_ultimos_movimientos(limite=6):
    """Últimas líneas de venta (detalle_ventas), más recientes primero."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT v.numero_venta, v.estado,
                   dv.nombre_producto, dv.cantidad, dv.unidad_venta, dv.subtotal_linea
            FROM detalle_ventas dv
            JOIN ventas v ON v.id = dv.venta_id
            ORDER BY dv.id DESC
            LIMIT %s;
            """,
            (limite,),
        )
        return cur.fetchall()
