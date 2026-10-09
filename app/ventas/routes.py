from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from app.auditoria import models as auditoria
from app.comun import notificaciones
from app.comun.excel import respuesta_excel
from app.inventario import models as modelos_inventario
from app.ventas import models

ventas_bp = Blueprint(
    "ventas",
    __name__,
    url_prefix="/ventas",
    template_folder="../templates",
)


@ventas_bp.route("/pos", methods=["GET"])
def pos():
    productos = modelos_inventario.obtener_productos_para_venta()
    clientes = models.obtener_clientes_activos()
    return render_template(
        "ventas/pos.html",
        productos=productos,
        clientes=clientes,
        categorias=modelos_inventario.CATEGORIAS_PRODUCTO,
        metodos_pago=models.METODOS_PAGO,
    )


@ventas_bp.route("/checkout", methods=["POST"])
def checkout():
    """API JSON usada por el carrito del POS (ver static JS en ventas/pos.html)."""
    datos = request.get_json(silent=True) or {}
    cliente_id = datos.get("cliente_id")
    tipo_precio = datos.get("tipo_precio")
    metodo_pago = datos.get("metodo_pago") or "Efectivo"
    items = datos.get("items") or []

    if not cliente_id:
        return jsonify({"error": "Selecciona un cliente."}), 400

    try:
        resultado = models.registrar_venta(
            cliente_id=int(cliente_id),
            tipo_precio=tipo_precio,
            items=items,
            metodo_pago=metodo_pago,
            vendedor=g.usuario["nombre_completo"],
            usuario_id=g.usuario["id"],
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except (TypeError, KeyError, AttributeError):
        return jsonify({"error": "Datos de venta incompletos o inválidos."}), 400

    auditoria.registrar(
        "venta_creada", f"Registró la venta {resultado['numero_venta']} por Q{resultado['total']:.2f}.",
        "venta", resultado["id"],
        {"cliente_id": int(cliente_id), "metodo_pago": metodo_pago, "tipo_precio": tipo_precio,
         "total": resultado["total"],
         "productos": [{"nombre": l["nombre_producto"], "cantidad": l["cantidad"], "subtotal": l["subtotal_linea"]}
                       for l in resultado["items"]]},
    )

    # Aviso por WhatsApp en segundo plano (si está configurado); nunca afecta a la venta ya registrada.
    notificaciones.notificar_bajo_stock(
        resultado["alertas_stock"], resultado["numero_venta"], al_fallar=models.revertir_aviso_stock
    )

    return jsonify({
        "ok": True,
        "venta_id": resultado["id"],
        "numero_venta": resultado["numero_venta"],
        "total": resultado["total"],
        "alertas_stock": resultado["alertas_stock"],
        "redirect": url_for("ventas.venta_detalle", venta_id=resultado["id"]),
    })


@ventas_bp.route("/historial", methods=["GET"])
def historial():
    busqueda = request.args.get("q") or None
    pagina = max(int(request.args.get("pagina", 1) or 1), 1)
    por_pagina = 10

    registros, total_registros = models.obtener_historial_ventas(
        busqueda=busqueda, pagina=pagina, por_pagina=por_pagina
    )
    total_paginas = max((total_registros + por_pagina - 1) // por_pagina, 1)

    return render_template(
        "ventas/historial.html",
        registros=registros,
        total_registros=total_registros,
        pagina=pagina,
        total_paginas=total_paginas,
        por_pagina=por_pagina,
        busqueda=busqueda or "",
    )


@ventas_bp.route("/historial/excel", methods=["GET"])
def exportar_historial_excel():
    busqueda = request.args.get("q") or None
    registros, _total = models.obtener_historial_ventas(busqueda=busqueda, pagina=1, por_pagina=1_000_000)
    filas = [
        (
            r["creado_en"].strftime("%d/%m/%Y %H:%M"), r["numero_venta"], r["cliente_nombre"],
            r["tipo_precio_aplicado"], float(r["total"]), r["estado"], r["vendedor"] or "Caja Principal",
        )
        for r in registros
    ]
    return respuesta_excel(
        "historial_ventas.xlsx", "Ventas",
        ["Fecha", "No. Venta", "Cliente", "Precio Aplicado", "Total (Q)", "Estado", "Vendedor"],
        filas,
    )


@ventas_bp.route("/<int:venta_id>", methods=["GET"])
def venta_detalle(venta_id):
    venta, detalle = models.obtener_venta_por_id(venta_id)
    if venta is None:
        flash("La venta solicitada no existe.", "error")
        return redirect(url_for("ventas.historial"))

    return render_template("ventas/venta_detalle.html", venta=venta, detalle=detalle)


@ventas_bp.route("/clientes", methods=["GET"])
def clientes():
    tipo = request.args.get("tipo") or None
    busqueda = request.args.get("q") or None

    lista_clientes = models.obtener_clientes(tipo=tipo, busqueda=busqueda)
    resumen = models.obtener_resumen_clientes()

    return render_template(
        "ventas/clientes.html",
        clientes=lista_clientes,
        tipos_cliente=models.TIPOS_CLIENTE,
        resumen=resumen,
        tipo_activo=tipo or "",
        busqueda=busqueda or "",
    )


@ventas_bp.route("/clientes", methods=["POST"])
def crear_cliente_form():
    nombre = request.form.get("nombre", "").strip()
    tipo_cliente = request.form.get("tipo_cliente", "detalle").strip()
    categoria = request.form.get("categoria", "").strip() or None
    telefono = request.form.get("telefono", "").strip() or None
    direccion = request.form.get("direccion", "").strip() or None
    nit = request.form.get("nit", "").strip() or None

    try:
        nuevo = models.crear_cliente(nombre, tipo_cliente, telefono, direccion, nit, categoria)
        auditoria.registrar("cliente_creado", f"Creó al cliente «{nombre}».", "cliente", nuevo["id"],
                            {"tipo_cliente": tipo_cliente})
        flash(f"Cliente «{nombre}» registrado.", "success")
    except ValueError as exc:
        flash(str(exc), "error")

    return redirect(url_for("ventas.clientes"))


@ventas_bp.route("/clientes/excel", methods=["GET"])
def exportar_clientes_excel():
    tipo = request.args.get("tipo") or None
    busqueda = request.args.get("q") or None
    lista_clientes = models.obtener_clientes(tipo=tipo, busqueda=busqueda)
    filas = [
        (
            c["nombre"], c["tipo_cliente"], c["categoria"] or "", c["telefono"] or "",
            c["direccion"] or "", c["nit"] or "",
            c["ultima_compra"].strftime("%d/%m/%Y %H:%M") if c["ultima_compra"] else "Sin compras",
        )
        for c in lista_clientes
    ]
    return respuesta_excel(
        "clientes.xlsx", "Clientes",
        ["Nombre", "Tipo", "Categoría", "Teléfono", "Dirección", "NIT", "Última Compra"],
        filas,
    )


@ventas_bp.route("/clientes/<int:cliente_id>/editar", methods=["POST"])
def editar_cliente(cliente_id):
    nombre = request.form.get("nombre", "").strip()
    tipo_cliente = request.form.get("tipo_cliente", "detalle").strip()
    categoria = request.form.get("categoria", "").strip() or None
    telefono = request.form.get("telefono", "").strip() or None
    direccion = request.form.get("direccion", "").strip() or None
    nit = request.form.get("nit", "").strip() or None

    antes = models.obtener_cliente_por_id(cliente_id)
    try:
        models.actualizar_cliente(cliente_id, nombre, tipo_cliente, telefono, direccion, nit, categoria)
        if antes:
            modificado = auditoria.cambios(
                antes, {"nombre": nombre, "tipo_cliente": tipo_cliente, "categoria": categoria,
                        "telefono": telefono, "direccion": direccion, "nit": nit},
                ["nombre", "tipo_cliente", "categoria", "telefono", "direccion", "nit"],
            )
            if modificado:
                auditoria.registrar("cliente_editado", f"Editó al cliente «{antes['nombre']}».", "cliente",
                                    cliente_id, {"cambios": modificado})
        flash(f"Cliente «{nombre}» actualizado.", "success")
    except ValueError as exc:
        flash(str(exc), "error")

    return redirect(url_for("ventas.clientes"))


@ventas_bp.route("/clientes/<int:cliente_id>/eliminar", methods=["POST"])
def eliminar_cliente(cliente_id):
    antes = models.obtener_cliente_por_id(cliente_id)
    try:
        models.eliminar_cliente(cliente_id)
        auditoria.registrar(
            "cliente_eliminado", f"Eliminó al cliente «{antes['nombre'] if antes else cliente_id}».", "cliente",
            cliente_id, {"nit": antes["nit"], "telefono": antes["telefono"]} if antes else None,
        )
        flash("Cliente eliminado.", "success")
    except ValueError as exc:
        flash(str(exc), "error")

    return redirect(url_for("ventas.clientes"))


@ventas_bp.route("/api/clientes", methods=["POST"])
def crear_cliente_api():
    """Alta rápida de cliente desde el modal del POS, sin recargar la página."""
    datos = request.get_json(silent=True) or {}
    nombre = (datos.get("nombre") or "").strip()
    tipo_cliente = (datos.get("tipo_cliente") or "detalle").strip()

    try:
        cliente = models.crear_cliente(nombre, tipo_cliente)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    auditoria.registrar("cliente_creado", f"Creó al cliente «{nombre}» (desde el POS).", "cliente",
                        cliente["id"], {"tipo_cliente": tipo_cliente})

    return jsonify({"ok": True, "cliente": cliente})
