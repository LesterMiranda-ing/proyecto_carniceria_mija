import os
from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from app.auditoria import models as auditoria
from app.comun.excel import respuesta_excel
from app.inventario import models

inventario_bp = Blueprint(
    "inventario",
    __name__,
    url_prefix="/inventario",
    template_folder="../templates",
)

EXTENSIONES_FACTURA = {"jpg", "jpeg", "png", "pdf"}
EXTENSIONES_IMAGEN = {"jpg", "jpeg", "png"}
CARPETA_FACTURAS = os.path.join("app", "static", "uploads", "facturas")
CARPETA_FOTOS_PRODUCTOS = os.path.join("app", "static", "uploads", "productos")


def _extension_valida(nombre_archivo, extensiones_permitidas):
    return "." in nombre_archivo and nombre_archivo.rsplit(".", 1)[1].lower() in extensiones_permitidas


def _guardar_archivo(archivo, carpeta, extensiones_permitidas, mensaje_error):
    """Guarda un archivo subido en `carpeta` con un nombre único y devuelve ese nombre."""
    if not archivo or archivo.filename == "":
        return None
    if not _extension_valida(archivo.filename, extensiones_permitidas):
        flash(mensaje_error, "error")
        return None

    os.makedirs(carpeta, exist_ok=True)
    nombre_unico = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(archivo.filename)}"
    archivo.save(os.path.join(carpeta, nombre_unico))
    return nombre_unico


def _guardar_factura(archivo):
    return _guardar_archivo(archivo, CARPETA_FACTURAS, EXTENSIONES_FACTURA, "La factura debe ser JPG, PNG o PDF.")


def _guardar_foto_producto(archivo):
    return _guardar_archivo(archivo, CARPETA_FOTOS_PRODUCTOS, EXTENSIONES_IMAGEN, "La fotografía debe ser JPG o PNG.")


@inventario_bp.route("/entrada-canal", methods=["GET"])
def entrada_canal():
    ultimos_ingresos = models.obtener_ultimos_ingresos(limite=5)
    peso_promedio = models.obtener_peso_promedio()
    return render_template(
        "inventario/entrada_canal.html",
        ultimos_ingresos=ultimos_ingresos,
        peso_promedio=peso_promedio,
        proveedores=models.obtener_nombres_proveedores(),
        fecha_hoy=datetime.now().strftime("%Y-%m-%d"),
    )


@inventario_bp.route("/entrada-canal", methods=["POST"])
def registrar_entrada_canal():
    fecha_str = request.form.get("fecha_entrada", "").strip()
    proveedor = request.form.get("proveedor", "").strip()
    peso_lbs = request.form.get("peso_lbs", "").strip()
    costo_por_libra = request.form.get("costo_por_libra", "").strip()
    archivo_factura = request.files.get("factura")

    errores = []
    fecha_entrada = None
    if not fecha_str:
        errores.append("La fecha de entrada es obligatoria.")
    else:
        try:
            fecha_entrada = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            errores.append("La fecha de entrada no es válida.")

    if not proveedor:
        errores.append("El proveedor es obligatorio.")

    try:
        peso_lbs_val = float(peso_lbs)
        if peso_lbs_val <= 0:
            errores.append("El peso debe ser mayor a 0.")
    except (TypeError, ValueError):
        errores.append("El peso total no es válido.")
        peso_lbs_val = None

    try:
        costo_por_libra_val = float(costo_por_libra)
        if costo_por_libra_val < 0:
            errores.append("El costo por libra no puede ser negativo.")
    except (TypeError, ValueError):
        errores.append("El costo por libra no es válido.")
        costo_por_libra_val = None

    if errores:
        for error in errores:
            flash(error, "error")
        return redirect(url_for("inventario.entrada_canal"))

    nombre_factura = _guardar_factura(archivo_factura)

    resultado = models.insertar_entrada(
        fecha_entrada=fecha_entrada,
        proveedor=proveedor,
        peso_lbs=peso_lbs_val,
        costo_por_libra=costo_por_libra_val,
        factura_archivo=nombre_factura,
        registrado_por=g.usuario["nombre_completo"],
        usuario_id=g.usuario["id"],
    )

    auditoria.registrar(
        "entrada_canal_creada",
        f"Registró el lote {resultado['numero_lote']} de «{proveedor}» ({peso_lbs_val:.2f} lb).",
        "entrada_canal", resultado["id"],
        {"proveedor": proveedor, "peso_lbs": peso_lbs_val, "costo_por_libra": costo_por_libra_val,
         "costo_total": float(resultado["costo_total"])},
    )
    flash(
        f"Ingreso registrado: lote {resultado['numero_lote']} — "
        f"Inversión total Q{resultado['costo_total']:,.2f}",
        "success",
    )
    return redirect(url_for("inventario.entrada_canal"))


@inventario_bp.route("/entrada-canal/historial", methods=["GET"])
def historial():
    fecha_desde = request.args.get("desde") or None
    fecha_hasta = request.args.get("hasta") or None
    busqueda = request.args.get("q") or None
    pagina = max(int(request.args.get("pagina", 1) or 1), 1)
    por_pagina = 10

    registros, total_registros = models.obtener_historial(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        busqueda=busqueda,
        pagina=pagina,
        por_pagina=por_pagina,
    )
    total_paginas = max((total_registros + por_pagina - 1) // por_pagina, 1)

    return render_template(
        "inventario/historial.html",
        registros=registros,
        total_registros=total_registros,
        pagina=pagina,
        total_paginas=total_paginas,
        por_pagina=por_pagina,
        fecha_desde=fecha_desde or "",
        fecha_hasta=fecha_hasta or "",
        busqueda=busqueda or "",
    )


# --- Proveedores ------------------------------------------------------------------

@inventario_bp.route("/proveedores", methods=["GET"])
def proveedores():
    busqueda = (request.args.get("q") or "").strip() or None
    return render_template(
        "inventario/proveedores.html",
        proveedores=models.obtener_proveedores(busqueda),
        busqueda=busqueda or "",
    )


@inventario_bp.route("/proveedores", methods=["POST"])
def crear_proveedor():
    try:
        nuevo = models.crear_proveedor(
            request.form.get("nombre"), request.form.get("telefono"), request.form.get("nit"),
            request.form.get("direccion"),
            registrado_por=g.usuario["nombre_completo"], usuario_id=g.usuario["id"],
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("inventario.proveedores"))

    auditoria.registrar(
        "proveedor_creado", f"Agregó al proveedor «{nuevo['nombre']}».", "proveedor", nuevo["id"],
        {"telefono": request.form.get("telefono") or None, "nit": request.form.get("nit") or None},
    )
    flash(f"Proveedor «{nuevo['nombre']}» agregado.", "success")
    return redirect(url_for("inventario.proveedores"))


@inventario_bp.route("/proveedores/<int:proveedor_id>/editar", methods=["POST"])
def editar_proveedor(proveedor_id):
    antes = models.obtener_proveedor_por_id(proveedor_id)
    try:
        models.actualizar_proveedor(
            proveedor_id, request.form.get("nombre"), request.form.get("telefono"), request.form.get("nit"),
            request.form.get("direccion"),
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("inventario.proveedores"))

    if antes:
        despues = {k: (request.form.get(k) or "").strip() for k in ("nombre", "telefono", "nit", "direccion")}
        modificado = auditoria.cambios(antes, despues, ["nombre", "telefono", "nit", "direccion"])
        if modificado:
            auditoria.registrar("proveedor_editado", f"Editó al proveedor «{antes['nombre']}».", "proveedor",
                                proveedor_id, {"cambios": modificado})
    flash("Proveedor actualizado.", "success")
    return redirect(url_for("inventario.proveedores"))


@inventario_bp.route("/proveedores/<int:proveedor_id>/eliminar", methods=["POST"])
def eliminar_proveedor(proveedor_id):
    antes = models.obtener_proveedor_por_id(proveedor_id)
    try:
        models.eliminar_proveedor(proveedor_id)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("inventario.proveedores"))

    auditoria.registrar(
        "proveedor_eliminado", f"Eliminó al proveedor «{antes['nombre'] if antes else proveedor_id}».",
        "proveedor", proveedor_id, {"nit": antes["nit"], "telefono": antes["telefono"]} if antes else None,
    )
    flash("Proveedor eliminado. Los lotes ya registrados conservan su nombre.", "success")
    return redirect(url_for("inventario.proveedores"))


@inventario_bp.route("/proveedores/excel", methods=["GET"])
def exportar_proveedores_excel():
    lista = models.obtener_proveedores((request.args.get("q") or "").strip() or None)
    filas = [
        (p["nombre"], p["telefono"] or "", p["nit"] or "", p["direccion"] or "", p["lotes"],
         p["ultima_entrada"].strftime("%d/%m/%Y") if p["ultima_entrada"] else "Sin entradas")
        for p in lista
    ]
    return respuesta_excel(
        "proveedores.xlsx", "Proveedores",
        ["Proveedor", "Teléfono", "NIT", "Dirección", "Lotes", "Última Entrada"], filas,
    )


@inventario_bp.route("/entrada-canal/historial/excel", methods=["GET"])
def exportar_historial_excel():
    fecha_desde = request.args.get("desde") or None
    fecha_hasta = request.args.get("hasta") or None
    busqueda = request.args.get("q") or None

    registros, _total = models.obtener_historial(
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, busqueda=busqueda,
        pagina=1, por_pagina=1_000_000,
    )
    filas = [
        (
            r["creado_en"].strftime("%d/%m/%Y %H:%M"), r["numero_lote"], r["proveedor"],
            float(r["peso_lbs"]), float(r["costo_por_libra"]), float(r["costo_total"]),
            r["estado"], r["registrado_por"] or "",
        )
        for r in registros
    ]
    return respuesta_excel(
        "historial_entrada_canal.xlsx", "Entrada de Canal",
        ["Fecha", "Lote", "Proveedor", "Peso (lbs)", "Costo/lb (Q)", "Total Inv. (Q)", "Estado", "Registrado por"],
        filas,
    )


@inventario_bp.route("/desposte", methods=["GET"])
def desposte():
    canal_id = request.args.get("canal_id", type=int)
    canales_pendientes = models.obtener_canales_pendientes_desposte()

    ids_pendientes = {c["id"] for c in canales_pendientes}

    canal_seleccionado = None
    if canal_id:
        if canal_id in ids_pendientes:
            canal_seleccionado = models.obtener_entrada_por_id(canal_id)
        else:
            flash("Ese canal ya fue procesado o no existe. Elige otro de la lista.", "error")
            canal_seleccionado = canales_pendientes[0] if canales_pendientes else None
    elif canales_pendientes:
        canal_seleccionado = canales_pendientes[0]

    return render_template(
        "inventario/desposte.html",
        canales_pendientes=canales_pendientes,
        canal_seleccionado=canal_seleccionado,
        tipos_corte=models.TIPOS_CORTE,
        tipos_tara=models.TIPOS_TARA,
        rendimiento_minimo=models.RENDIMIENTO_MINIMO_ESPERADO,
    )


@inventario_bp.route("/desposte", methods=["POST"])
def registrar_desposte_ruta():
    entrada_canal_id = request.form.get("entrada_canal_id", type=int)
    if not entrada_canal_id:
        flash("Selecciona el canal que vas a procesar.", "error")
        return redirect(url_for("inventario.desposte"))

    cortes = []
    for tipo in models.TIPOS_CORTE:
        valor = request.form.get(f"corte_{tipo['campo']}", "0").strip()
        try:
            peso = max(float(valor), 0.0) if valor else 0.0
        except ValueError:
            peso = 0.0
        cortes.append({"tipo_corte": tipo["nombre"], "categoria": tipo["categoria"], "peso_lbs": peso})

    if all(c["peso_lbs"] <= 0 for c in cortes):
        flash("Registra al menos un corte con peso mayor a 0.", "error")
        return redirect(url_for("inventario.desposte", canal_id=entrada_canal_id))

    tara_items = []
    for tara in models.TIPOS_TARA:
        cantidad_raw = request.form.get(f"tara_{tara['campo']}_cantidad", "0").strip()
        peso_unit_raw = request.form.get(f"tara_{tara['campo']}_peso", str(tara["peso_unitario_defecto"])).strip()
        try:
            cantidad = max(int(float(cantidad_raw)), 0) if cantidad_raw else 0
        except ValueError:
            cantidad = 0
        try:
            peso_unitario = max(float(peso_unit_raw), 0.0) if peso_unit_raw else 0.0
        except ValueError:
            peso_unitario = 0.0
        tara_items.append({"item": tara["item"], "cantidad": cantidad, "peso_unitario_lbs": peso_unitario})

    try:
        resultado = models.registrar_desposte(
            entrada_canal_id, cortes, tara_items,
            registrado_por=g.usuario["nombre_completo"], usuario_id=g.usuario["id"],
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("inventario.desposte"))

    canal = models.obtener_entrada_por_id(entrada_canal_id)
    auditoria.registrar(
        "desposte_creado",
        f"Registró el desposte del lote {canal['numero_lote'] if canal else entrada_canal_id} "
        f"(rendimiento {resultado['rendimiento_pct']}%).",
        "desposte", resultado["id"],
        {"rendimiento_pct": resultado["rendimiento_pct"], "merma_pct": resultado["merma_pct"],
         "merma_lbs": resultado["merma_lbs"], "cortes": {c["tipo_corte"]: c["peso_lbs"] for c in cortes if c["peso_lbs"] > 0}},
    )
    flash(
        f"Desposte registrado — Rendimiento {resultado['rendimiento_pct']}% · "
        f"Merma {resultado['merma_pct']}% ({resultado['merma_lbs']} lbs)",
        "success",
    )
    return redirect(url_for("inventario.desposte_detalle", desposte_id=resultado["id"]))


@inventario_bp.route("/desposte/historial", methods=["GET"])
def desposte_historial():
    busqueda = request.args.get("q") or None
    pagina = max(int(request.args.get("pagina", 1) or 1), 1)
    por_pagina = 10

    registros, total_registros = models.obtener_historial_desposte(
        busqueda=busqueda, pagina=pagina, por_pagina=por_pagina
    )
    total_paginas = max((total_registros + por_pagina - 1) // por_pagina, 1)

    return render_template(
        "inventario/desposte_historial.html",
        registros=registros,
        total_registros=total_registros,
        pagina=pagina,
        total_paginas=total_paginas,
        por_pagina=por_pagina,
        busqueda=busqueda or "",
        rendimiento_minimo=models.RENDIMIENTO_MINIMO_ESPERADO,
    )


@inventario_bp.route("/desposte/historial/excel", methods=["GET"])
def exportar_desposte_excel():
    busqueda = request.args.get("q") or None
    registros, _total = models.obtener_historial_desposte(busqueda=busqueda, pagina=1, por_pagina=1_000_000)
    filas = [
        (
            r["fecha_desposte"].strftime("%d/%m/%Y %H:%M"), r["numero_lote"], r["proveedor"],
            float(r["peso_inicial_lbs"]), float(r["peso_cortes_lbs"]), float(r["merma_lbs"]),
            float(r["rendimiento_pct"]), r["registrado_por"] or "",
        )
        for r in registros
    ]
    return respuesta_excel(
        "historial_desposte.xlsx", "Desposte",
        ["Fecha", "Lote", "Proveedor", "Peso Inicial (lbs)", "Aprovechable (lbs)", "Merma (lbs)",
         "Rendimiento (%)", "Registrado por"],
        filas,
    )


@inventario_bp.route("/desposte/<int:desposte_id>", methods=["GET"])
def desposte_detalle(desposte_id):
    encabezado, detalle, tara = models.obtener_desposte_por_id(desposte_id)
    if encabezado is None:
        flash("El desposte solicitado no existe.", "error")
        return redirect(url_for("inventario.desposte_historial"))

    return render_template(
        "inventario/desposte_detalle.html",
        d=encabezado,
        detalle=detalle,
        tara=tara,
        rendimiento_minimo=models.RENDIMIENTO_MINIMO_ESPERADO,
    )


@inventario_bp.route("/productos", methods=["GET"])
def catalogo_productos():
    categoria = request.args.get("categoria") or None
    busqueda = request.args.get("q") or None

    productos = models.obtener_productos_catalogo(categoria=categoria, busqueda=busqueda)
    resumen = models.obtener_resumen_inventario()

    return render_template(
        "inventario/catalogo.html",
        productos=productos,
        resumen=resumen,
        categorias=models.CATEGORIAS_PRODUCTO,
        categoria_activa=categoria or "",
        busqueda=busqueda or "",
    )


@inventario_bp.route("/productos/nuevo", methods=["GET", "POST"])
def nuevo_producto():
    if request.method == "GET":
        return render_template("inventario/producto_nuevo.html", categorias=models.CATEGORIAS_PRODUCTO)

    datos, errores = _leer_formulario_producto()
    if errores:
        for error in errores:
            flash(error, "error")
        return redirect(url_for("inventario.nuevo_producto"))

    nombre_foto = _guardar_foto_producto(request.files.get("foto"))

    nuevo = models.crear_producto(
        nombre=datos["nombre"],
        categoria=datos["categoria"],
        unidad_venta=datos["unidad_venta"],
        precio_detalle=datos["precio_detalle"],
        precio_mayoreo=datos["precio_mayoreo"],
        stock_actual=datos["stock_actual"],
        stock_minimo=datos["stock_minimo"],
        descripcion=datos["descripcion"],
        costo=datos["costo"],
        foto_archivo=nombre_foto,
    )

    auditoria.registrar(
        "producto_creado", f"Creó el producto «{datos['nombre']}» ({nuevo['codigo']}).", "producto", nuevo["id"],
        {"categoria": datos["categoria"], "precio_detalle": datos["precio_detalle"],
         "precio_mayoreo": datos["precio_mayoreo"], "stock_inicial": datos["stock_actual"],
         "stock_minimo": datos["stock_minimo"]},
    )
    flash(f"Producto «{datos['nombre']}» agregado al catálogo.", "success")
    return redirect(url_for("inventario.catalogo_productos"))


@inventario_bp.route("/productos/<int:producto_id>/editar", methods=["GET", "POST"])
def editar_producto(producto_id):
    producto = models.obtener_producto_por_id(producto_id)
    if producto is None or not producto["activo"]:
        flash("El producto no existe.", "error")
        return redirect(url_for("inventario.catalogo_productos"))

    if request.method == "GET":
        return render_template(
            "inventario/producto_nuevo.html", categorias=models.CATEGORIAS_PRODUCTO, producto=producto
        )

    datos, errores = _leer_formulario_producto()
    if errores:
        for error in errores:
            flash(error, "error")
        return redirect(url_for("inventario.editar_producto", producto_id=producto_id))

    nombre_foto = _guardar_foto_producto(request.files.get("foto"))
    try:
        models.actualizar_producto(
            producto_id,
            nombre=datos["nombre"],
            categoria=datos["categoria"],
            descripcion=datos["descripcion"],
            costo=datos["costo"],
            precio_detalle=datos["precio_detalle"],
            precio_mayoreo=datos["precio_mayoreo"],
            stock_minimo=datos["stock_minimo"],
            foto_archivo=nombre_foto,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("inventario.editar_producto", producto_id=producto_id))

    modificado = auditoria.cambios(
        producto, datos, ["nombre", "categoria", "descripcion", "costo", "precio_detalle", "precio_mayoreo", "stock_minimo"]
    )
    if nombre_foto:
        modificado["foto"] = {"antes": producto["foto_archivo"], "despues": nombre_foto}
    if modificado:  # si se guardó sin tocar nada, no se llena la bitácora de ruido
        auditoria.registrar(
            "producto_editado", f"Editó el producto «{producto['nombre']}» ({producto['codigo']}).",
            "producto", producto_id, {"cambios": modificado},
        )
    flash(f"Producto «{datos['nombre']}» actualizado.", "success")
    return redirect(url_for("inventario.catalogo_productos"))


def _leer_formulario_producto():
    """Lee y valida el formulario de producto (alta y edición). Devuelve (datos, errores)."""
    errores = []

    def _num(nombre_campo, valor, opcional=False):
        valor = (valor or "").strip()
        if opcional and not valor:
            return 0.0
        try:
            v = float(valor)
        except ValueError:
            errores.append(f"{nombre_campo} no es un número válido.")
            return 0.0
        if v < 0:
            errores.append(f"{nombre_campo} no puede ser negativo.")
        return v

    datos = {
        "nombre": request.form.get("nombre", "").strip(),
        "categoria": request.form.get("categoria", "").strip(),
        "descripcion": request.form.get("descripcion", "").strip() or None,
        "unidad_venta": request.form.get("unidad_venta", "lb").strip(),
        "costo": _num("El precio de costo", request.form.get("costo"), opcional=True),
        "precio_detalle": _num("El precio de detalle", request.form.get("precio_detalle")),
        "precio_mayoreo": _num("El precio de mayoreo", request.form.get("precio_mayoreo")),
        "stock_actual": _num("El stock inicial", request.form.get("stock_actual"), opcional=True),
        "stock_minimo": _num("El stock mínimo", request.form.get("stock_minimo"), opcional=True),
    }
    if not datos["nombre"]:
        errores.append("El nombre del producto es obligatorio.")
    if datos["categoria"] not in models.CATEGORIAS_PRODUCTO:
        errores.append("Selecciona una categoría válida.")
    if datos["unidad_venta"] not in ("lb", "unidad"):
        errores.append("La unidad de venta debe ser 'lb' o 'unidad'.")
    return datos, errores
