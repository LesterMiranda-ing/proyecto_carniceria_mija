import os
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from app.auditoria import models as auditoria
from app.comun.excel import respuesta_excel
from app.finanzas import models

finanzas_bp = Blueprint(
    "finanzas",
    __name__,
    url_prefix="/finanzas",
    template_folder="../templates",
)

EXTENSIONES_COMPROBANTE = {"jpg", "jpeg", "png", "pdf"}
CARPETA_COMPROBANTES = os.path.join("app", "static", "uploads", "egresos")


def _extension_valida(nombre_archivo):
    return "." in nombre_archivo and nombre_archivo.rsplit(".", 1)[1].lower() in EXTENSIONES_COMPROBANTE


def _guardar_comprobante(archivo):
    """Guarda el recibo/comprobante subido en static/uploads/egresos."""
    if not archivo or archivo.filename == "":
        return None
    if not _extension_valida(archivo.filename):
        flash("El comprobante debe ser JPG, PNG o PDF.", "error")
        return None

    os.makedirs(CARPETA_COMPROBANTES, exist_ok=True)
    nombre_unico = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(archivo.filename)}"
    archivo.save(os.path.join(CARPETA_COMPROBANTES, nombre_unico))
    return nombre_unico


def _resolver_rango(rango, desde_param, hasta_param):
    hoy = date.today()
    if rango == "7dias":
        return hoy - timedelta(days=6), hoy
    if rango == "personalizado" and desde_param and hasta_param:
        try:
            desde = datetime.strptime(desde_param, "%Y-%m-%d").date()
            hasta = datetime.strptime(hasta_param, "%Y-%m-%d").date()
            if desde <= hasta:
                return desde, hasta
        except ValueError:
            pass
    return hoy, hoy  # "hoy" o fallback ante datos inválidos


@finanzas_bp.route("/", methods=["GET"])
def dashboard():
    rango = request.args.get("rango", "hoy")
    if rango not in ("hoy", "7dias", "personalizado"):
        rango = "hoy"
    desde_param = request.args.get("desde", "")
    hasta_param = request.args.get("hasta", "")
    fecha_desde, fecha_hasta = _resolver_rango(rango, desde_param, hasta_param)

    resumen = models.obtener_resumen_periodo(fecha_desde, fecha_hasta)
    cuadre = models.obtener_cuadre_diario(fecha_desde, fecha_hasta)
    gastos_recientes = models.obtener_gastos_recientes(limite=5)

    return render_template(
        "finanzas/dashboard.html",
        resumen=resumen,
        cuadre=cuadre,
        gastos_recientes=gastos_recientes,
        categorias=models.CATEGORIAS_EGRESO,
        rango=rango,
        fecha_desde=fecha_desde.isoformat(),
        fecha_hasta=fecha_hasta.isoformat(),
        fecha_hoy=date.today().isoformat(),
    )


@finanzas_bp.route("/cuadre/excel", methods=["GET"])
def exportar_cuadre_excel():
    rango = request.args.get("rango", "hoy")
    if rango not in ("hoy", "7dias", "personalizado"):
        rango = "hoy"
    fecha_desde, fecha_hasta = _resolver_rango(rango, request.args.get("desde", ""), request.args.get("hasta", ""))

    cuadre = models.obtener_cuadre_diario(fecha_desde, fecha_hasta)
    filas = [
        (
            dia["fecha"].strftime("%d/%m/%Y"), float(dia["venta_bruta"]), float(dia["gasto_operativo"]),
            float(dia["balance"]), "Rentable" if dia["balance"] >= 0 else "Pérdida",
        )
        for dia in cuadre
    ]
    return respuesta_excel(
        "cuadre_de_ventas.xlsx", "Cuadre de Ventas",
        ["Fecha", "Venta Bruta (Q)", "Gasto Operativo (Q)", "Balance (Q)", "Estado"],
        filas,
    )


@finanzas_bp.route("/egresos", methods=["POST"])
def registrar_egreso():
    fecha_str = request.form.get("fecha", "").strip()
    monto_str = request.form.get("monto", "").strip()
    categoria = request.form.get("categoria", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    archivo = request.files.get("comprobante")

    errores = []
    fecha = None
    if not fecha_str:
        errores.append("La fecha es obligatoria.")
    else:
        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            errores.append("La fecha no es válida.")

    monto = None
    try:
        monto = float(monto_str)
        if monto <= 0:
            errores.append("El monto debe ser mayor a 0.")
    except (TypeError, ValueError):
        errores.append("El monto no es válido.")

    if categoria not in models.CATEGORIAS_EGRESO:
        errores.append("Selecciona una categoría válida.")
    if not descripcion:
        errores.append("La descripción es obligatoria.")

    if errores:
        for error in errores:
            flash(error, "error")
        return redirect(url_for("finanzas.dashboard"))

    comprobante = _guardar_comprobante(archivo)

    nuevo = models.crear_egreso(
        fecha, monto, categoria, descripcion, comprobante,
        registrado_por=g.usuario["nombre_completo"], usuario_id=g.usuario["id"],
    )
    auditoria.registrar(
        "egreso_creado", f"Registró el gasto «{descripcion}» por Q{monto:,.2f}.", "egreso", nuevo["id"],
        {"fecha": fecha.isoformat(), "categoria": categoria, "monto": monto, "con_comprobante": bool(comprobante)},
    )
    flash(f"Gasto registrado: {descripcion} — Q{monto:,.2f}", "success")
    return redirect(url_for("finanzas.dashboard"))


@finanzas_bp.route("/egresos/listado", methods=["GET"])
def listado_egresos():
    pagina = max(int(request.args.get("pagina", 1) or 1), 1)
    por_pagina = 15
    registros, total_registros = models.obtener_egresos(pagina=pagina, por_pagina=por_pagina)
    total_paginas = max((total_registros + por_pagina - 1) // por_pagina, 1)

    return render_template(
        "finanzas/egresos.html",
        registros=registros,
        total_registros=total_registros,
        pagina=pagina,
        total_paginas=total_paginas,
        por_pagina=por_pagina,
    )


@finanzas_bp.route("/egresos/listado/excel", methods=["GET"])
def exportar_egresos_excel():
    registros, _total = models.obtener_egresos(pagina=1, por_pagina=1_000_000)
    filas = [
        (
            r["fecha"].strftime("%d/%m/%Y"), r["descripcion"], r["categoria"],
            float(r["monto"]), r["registrado_por"] or "",
        )
        for r in registros
    ]
    return respuesta_excel(
        "gastos_operativos.xlsx", "Gastos",
        ["Fecha", "Descripción", "Categoría", "Monto (Q)", "Registrado por"],
        filas,
    )


@finanzas_bp.route("/egresos/<int:egreso_id>/eliminar", methods=["POST"])
def eliminar_egreso(egreso_id):
    antes = models.obtener_egreso(egreso_id)
    try:
        models.eliminar_egreso(egreso_id)
        if antes:
            auditoria.registrar(
                "egreso_eliminado", f"Eliminó el gasto «{antes['descripcion']}» por Q{float(antes['monto']):,.2f}.",
                "egreso", egreso_id,
                {"fecha": antes["fecha"].isoformat(), "categoria": antes["categoria"], "monto": float(antes["monto"]),
                 "registrado_por": antes["registrado_por"]},
            )
        flash("Gasto eliminado.", "success")
    except ValueError as exc:
        flash(str(exc), "error")

    return redirect(url_for("finanzas.listado_egresos"))
