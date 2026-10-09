"""Pantallas de Configuración: usuarios, roles y matriz de permisos (solo Gerente)."""

from datetime import datetime, timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.auditoria import models as auditoria
from app.auth import models, permisos
from app.auth.routes import _rechazar, destino_inicio

config_bp = Blueprint(
    "configuracion",
    __name__,
    url_prefix="/configuracion",
    template_folder="../templates",
)


@config_bp.before_request
def solo_gerente():
    """Configuración no es delegable en la v1: solo el rol de sistema Gerente entra."""
    if not models.es_gerente(getattr(g, "usuario", None)):
        return _rechazar("No tienes permiso para acceder a Configuración.", 403, destino_inicio())
    return None


@config_bp.app_template_filter("ultimo_acceso")
def formatear_ultimo_acceso(momento):
    if momento is None:
        return "Nunca"
    ahora = datetime.now()
    segundos = (ahora - momento).total_seconds()
    if segundos < 60:
        return "Hace unos segundos"
    if segundos < 3600:
        return f"Hace {int(segundos // 60)} min"
    if momento.date() == ahora.date():
        return f"Hoy, {momento.strftime('%H:%M')}"
    if momento.date() == (ahora - timedelta(days=1)).date():
        return f"Ayer, {momento.strftime('%H:%M')}"
    return momento.strftime("%d %b, %Y")


def _ejecutar(accion, mensaje_ok, destino, auditar=None):
    """Corre una operación del modelo mostrando su resultado como mensaje flash.

    `auditar(resultado)` (opcional) devuelve los argumentos de `auditoria.registrar`; solo se
    llama si la operación tuvo éxito.
    """
    try:
        resultado = accion()
        flash(mensaje_ok, "success")
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        if auditar:
            auditoria.registrar(*auditar(resultado))
    return redirect(destino)


def _nombre_usuario(usuario_id):
    u = models.obtener_usuario_por_id(usuario_id)
    return u["nombre_completo"] if u else f"#{usuario_id}"


# --- Usuarios + panel de permisos del rol -----------------------------------------------

@config_bp.route("/", methods=["GET"])
def usuarios():
    busqueda = (request.args.get("q") or "").strip() or None
    roles = models.listar_roles_con_conteo()

    # Rol mostrado en el panel de permisos: el pedido, o Carnicero por defecto (como el prototipo).
    rol_id = request.args.get("rol", type=int)
    rol_sel = next((r for r in roles if r["id"] == rol_id), None)
    if rol_sel is None:
        rol_sel = next((r for r in roles if r["nombre"] == models.ROL_CARNICERO), roles[0] if roles else None)

    es_rol_gerente = bool(rol_sel) and rol_sel["nombre"] == models.ROL_GERENTE and rol_sel["es_sistema"]
    permisos_rol = permisos.TODOS if es_rol_gerente else (
        models.obtener_permisos_rol(rol_sel["id"]) if rol_sel else set()
    )

    lista_usuarios = models.listar_usuarios(busqueda)
    excepciones = models.obtener_excepciones_multiples(u["id"] for u in lista_usuarios)

    # Permisos de CADA rol, para poder mostrar en el modal de excepciones si un permiso
    # ya lo da el rol del usuario (útil para entender qué hace realmente "denegar"/"permitir").
    rol_gerente = next((r for r in roles if r["nombre"] == models.ROL_GERENTE and r["es_sistema"]), None)
    permisos_por_rol = {
        r["id"]: sorted(permisos.TODOS if r is rol_gerente else models.obtener_permisos_rol(r["id"]))
        for r in roles
    }

    return render_template(
        "configuracion/usuarios.html",
        usuarios=lista_usuarios,
        excepciones=excepciones,
        roles=roles,
        rol_sel=rol_sel,
        es_rol_gerente=es_rol_gerente,
        permisos_rol=permisos_rol,
        rol_gerente_id=rol_gerente["id"] if rol_gerente else None,
        permisos_por_rol=permisos_por_rol,
        modulos=permisos.MODULOS,
        busqueda=busqueda or "",
    )


@config_bp.route("/usuarios", methods=["POST"])
def crear_usuario():
    password = request.form.get("password") or ""
    if password != (request.form.get("password_confirmacion") or ""):
        flash("La confirmación no coincide con la contraseña inicial.", "error")
        return redirect(url_for("configuracion.usuarios"))

    nombre = (request.form.get("nombre_completo") or "").strip()
    login = (request.form.get("usuario") or "").strip().lower()
    rol_id = request.form.get("rol_id", type=int)
    return _ejecutar(
        lambda: models.crear_usuario(nombre, request.form.get("usuario"), request.form.get("email"), password, rol_id),
        f"Usuario «{nombre}» creado. Deberá cambiar su contraseña al primer ingreso.",
        url_for("configuracion.usuarios"),
        auditar=lambda nuevo_id: (
            "usuario_creado", f"Creó el usuario «{login}» ({nombre}).", "usuario", nuevo_id,
            {"usuario": login, "rol": (models.obtener_rol(rol_id) or {}).get("nombre")},
        ),
    )


@config_bp.route("/usuarios/<int:usuario_id>/editar", methods=["POST"])
def editar_usuario(usuario_id):
    antes = models.obtener_usuario_por_id(usuario_id)
    rol_id = request.form.get("rol_id", type=int)

    def auditar(_):
        despues = {
            "nombre_completo": (request.form.get("nombre_completo") or "").strip(),
            "email": (request.form.get("email") or "").strip(),
            "rol": (models.obtener_rol(rol_id) or {}).get("nombre") if rol_id is not None else antes["rol_nombre"],
        }
        previo = {"nombre_completo": antes["nombre_completo"], "email": antes["email"], "rol": antes["rol_nombre"]}
        return ("usuario_editado", f"Editó al usuario «{antes['usuario']}».", "usuario", usuario_id,
                {"cambios": auditoria.cambios(previo, despues, ["nombre_completo", "email", "rol"])})

    return _ejecutar(
        lambda: models.actualizar_usuario(
            usuario_id, request.form.get("nombre_completo"), request.form.get("email"),
            rol_id, actor_id=g.usuario["id"],
        ),
        "Usuario actualizado.",
        url_for("configuracion.usuarios"),
        auditar=auditar if antes else None,
    )


@config_bp.route("/usuarios/<int:usuario_id>/estado", methods=["POST"])
def cambiar_estado_usuario(usuario_id):
    activar = request.form.get("activo") == "1"
    nombre = _nombre_usuario(usuario_id)
    return _ejecutar(
        lambda: models.cambiar_estado_usuario(usuario_id, activar, actor_id=g.usuario["id"]),
        "Usuario activado." if activar else "Usuario desactivado: ya no podrá iniciar sesión.",
        url_for("configuracion.usuarios"),
        auditar=lambda _: ("usuario_estado", f"{'Activó' if activar else 'Desactivó'} al usuario «{nombre}».",
                           "usuario", usuario_id, {"activo": activar}),
    )


@config_bp.route("/usuarios/<int:usuario_id>/password", methods=["POST"])
def restablecer_password(usuario_id):
    nombre = _nombre_usuario(usuario_id)
    return _ejecutar(
        lambda: models.restablecer_password(usuario_id, request.form.get("password_temporal")),
        "Contraseña restablecida. El usuario deberá cambiarla al ingresar.",
        url_for("configuracion.usuarios"),
        auditar=lambda _: ("password_restablecida", f"Restableció la contraseña de «{nombre}» (temporal).",
                           "usuario", usuario_id, None),
    )


@config_bp.route("/usuarios/<int:usuario_id>/permisos", methods=["POST"])
def guardar_permisos_usuario(usuario_id):
    """Excepciones puntuales del usuario: cada permiso llega como 'heredado' | 'permitir' | 'denegar'."""
    a_permitir, a_denegar = [], []
    for codigo in permisos.TODOS:
        valor = request.form.get(f"permiso_{codigo}", "heredado")
        if valor == "permitir":
            a_permitir.append(codigo)
        elif valor == "denegar":
            a_denegar.append(codigo)

    nombre = _nombre_usuario(usuario_id)
    return _ejecutar(
        lambda: models.guardar_permisos_usuario(usuario_id, a_permitir, a_denegar),
        "Excepciones de permisos guardadas.",
        url_for("configuracion.usuarios"),
        auditar=lambda guardados: (
            "usuario_permisos", f"Cambió las excepciones de permisos de «{nombre}».", "usuario", usuario_id,
            {"permitir": sorted(guardados[0]), "denegar": sorted(guardados[1])},
        ),
    )


# --- Roles -----------------------------------------------------------------------------------

@config_bp.route("/roles", methods=["GET"])
def roles():
    return render_template("configuracion/roles.html", roles=models.listar_roles_con_conteo())


@config_bp.route("/roles", methods=["POST"])
def crear_rol():
    nombre = (request.form.get("nombre") or "").strip()
    try:
        nuevo_id = models.crear_rol(nombre, request.form.get("descripcion"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("configuracion.roles"))
    auditoria.registrar("rol_creado", f"Creó el rol «{nombre}».", "rol", nuevo_id)
    flash(f"Rol «{nombre}» creado. Asígnale permisos en la matriz.", "success")
    return redirect(url_for("configuracion.usuarios", rol=nuevo_id))


@config_bp.route("/roles/<int:rol_id>/editar", methods=["POST"])
def editar_rol(rol_id):
    antes = models.obtener_rol(rol_id)

    def auditar(_):
        despues = {"nombre": (request.form.get("nombre") or "").strip(),
                   "descripcion": (request.form.get("descripcion") or "").strip()}
        return ("rol_editado", f"Editó el rol «{antes['nombre']}».", "rol", rol_id,
                {"cambios": auditoria.cambios(antes, despues, ["nombre", "descripcion"])})

    return _ejecutar(
        lambda: models.actualizar_rol(rol_id, request.form.get("nombre"), request.form.get("descripcion")),
        "Rol actualizado.",
        url_for("configuracion.roles"),
        auditar=auditar if antes else None,
    )


@config_bp.route("/roles/<int:rol_id>/eliminar", methods=["POST"])
def eliminar_rol(rol_id):
    rol = models.obtener_rol(rol_id)
    nombre = rol["nombre"] if rol else f"#{rol_id}"
    return _ejecutar(
        lambda: models.eliminar_rol(rol_id),
        "Rol eliminado.",
        url_for("configuracion.roles"),
        auditar=lambda _: ("rol_eliminado", f"Eliminó el rol «{nombre}».", "rol", rol_id, None),
    )


@config_bp.route("/roles/<int:rol_id>/permisos", methods=["POST"])
def guardar_permisos(rol_id):
    destino = url_for("configuracion.usuarios", rol=rol_id)
    try:
        guardados = models.guardar_permisos_rol(rol_id, request.form.getlist("permisos"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(destino)
    rol = models.obtener_rol(rol_id)
    auditoria.registrar(
        "rol_permisos", f"Cambió los permisos del rol «{rol['nombre'] if rol else rol_id}».", "rol", rol_id,
        {"permisos": sorted(guardados)},
    )
    flash(f"Permisos del rol guardados ({len(guardados)} activos).", "success")
    return redirect(destino)
