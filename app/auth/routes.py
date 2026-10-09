import secrets

from flask import (Blueprint, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash

from app.auditoria import models as auditoria
from app.auth import models, permisos, seguridad

auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth",
    template_folder="../templates",
)

METODOS_CON_CAMBIOS = ("POST", "PUT", "PATCH", "DELETE")
# Mientras la contraseña sea temporal, solo se puede cambiarla o cerrar sesión.
ENDPOINTS_CAMBIO_PASSWORD = ("auth.cambiar_password", "auth.logout")
MENSAJE_LOGIN_FALLIDO = "Usuario, contraseña o rol incorrectos."


# --- Guardia global -----------------------------------------------------------------

def _es_peticion_json():
    return request.is_json or request.accept_mimetypes.best == "application/json"


def _rechazar(mensaje, codigo_json, destino_html):
    """Respuesta de rechazo adecuada al tipo de petición (el POS usa fetch/JSON)."""
    if _es_peticion_json():
        return jsonify({"error": mensaje}), codigo_json
    flash(mensaje, "error")
    return redirect(destino_html)


def _cargar_usuario_de_sesion():
    usuario_id = session.get("usuario_id")
    if not usuario_id:
        return None
    usuario = models.obtener_usuario_activo_por_id(usuario_id)
    if usuario is None:
        # Cuenta desactivada, rol desactivado o usuario borrado: la sesión deja de valer YA.
        session.pop("usuario_id", None)
    return usuario


def destino_inicio():
    """URL de la primera pantalla a la que el usuario actual SÍ tiene acceso."""
    return url_for(permisos.endpoint_de_inicio(getattr(g, "permisos", frozenset())))


def _denegar(mensaje="No tienes permiso para acceder a esta sección."):
    if _es_peticion_json():
        return jsonify({"error": mensaje}), 403
    return render_template("auth/acceso_denegado.html", mensaje=mensaje, sin_modulos=False), 403


def _carpeta_upload_permitida(archivo):
    """¿Puede el usuario actual ver este archivo subido? (Gerente sí; el resto, según su carpeta)."""
    if models.es_gerente(g.usuario):
        return True
    for carpeta, requeridos in permisos.PERMISOS_POR_CARPETA_UPLOADS.items():
        if archivo.startswith(carpeta):
            return permisos.permite_alguno(g.permisos, requeridos)
    return False  # carpeta desconocida: falla cerrado


@auth_bp.before_app_request
def proteger_aplicacion():
    endpoint = request.endpoint
    if endpoint is None:  # ruta inexistente: que responda el 404 normal
        return None

    g.usuario = _cargar_usuario_de_sesion()
    g.permisos = models.permisos_efectivos(g.usuario)  # se recalculan en CADA petición

    if request.method in METODOS_CON_CAMBIOS and not seguridad.token_csrf_valido(request):
        destino = url_for("auth.login") if g.usuario is None else destino_inicio()
        return _rechazar("La sesión expiró o el formulario no es válido. Vuelve a intentarlo.", 400, destino)

    archivo_subido = None
    if endpoint == "static":
        archivo = (request.view_args or {}).get("filename", "")
        if not archivo.startswith("uploads/"):
            return None  # CSS/JS/imágenes de la interfaz: públicos
        archivo_subido = archivo  # facturas, comprobantes y fotos: exigen sesión y permiso

    elif endpoint == "auth.login":
        if g.usuario is not None:
            return redirect(destino_inicio())
        return None

    # --- Autenticación ---------------------------------------------------------------------
    if g.usuario is None:
        if _es_peticion_json():
            return jsonify({"error": "Tu sesión expiró. Vuelve a iniciar sesión."}), 401
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    if g.usuario["debe_cambiar_password"] and endpoint not in ENDPOINTS_CAMBIO_PASSWORD:
        if _es_peticion_json():
            return jsonify({"error": "Debes cambiar tu contraseña temporal antes de continuar."}), 403
        return redirect(url_for("auth.cambiar_password"))

    # --- Autorización: falla cerrado ----------------------------------------------------------
    if archivo_subido is not None:
        return None if _carpeta_upload_permitida(archivo_subido) else _denegar()

    if endpoint in permisos.ENDPOINTS_SOLO_AUTENTICADOS:
        return None
    if endpoint.startswith(("configuracion.", "auditoria.")):
        return None  # solo Gerente: lo verifica el before_request del propio blueprint

    requerido = permisos.PERMISO_POR_ENDPOINT.get(endpoint)
    if requerido is None or not permisos.permite(g.permisos, requerido):
        return _denegar()
    return None


@auth_bp.app_context_processor
def inyectar_contexto_auth():
    usuario = getattr(g, "usuario", None)
    efectivos = getattr(g, "permisos", frozenset())
    return {
        "usuario_actual": usuario,
        "es_gerente": models.es_gerente(usuario),
        "puede": lambda permiso: permisos.permite(efectivos, permiso),
        "csrf_token": seguridad.obtener_token_csrf,
    }


# --- Login / logout ---------------------------------------------------------------------

def _iniciar_sesion(usuario):
    session.clear()  # nueva sesión y nuevo token CSRF: evita la fijación de sesión
    session["usuario_id"] = usuario["id"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    roles = models.obtener_roles_activos()
    siguiente = request.values.get("next", "")
    usuario_ingresado = ""
    rol_elegido = None

    if request.method == "POST":
        usuario_ingresado = (request.form.get("usuario") or "").strip().lower()
        password = request.form.get("password") or ""
        rol_elegido = request.form.get("rol_id", type=int)

        usuario = models.obtener_usuario_por_login(usuario_ingresado)
        hash_a_verificar = usuario["password_hash"] if usuario else models.HASH_FICTICIO
        password_correcta = check_password_hash(hash_a_verificar, password)

        # El rol que se ve en pantalla es solo una verificación: el rol REAL sale siempre de la
        # cuenta. Si el elegido no coincide con el de la cuenta, no se inicia sesión.
        if (usuario and password_correcta and usuario["activo"] and usuario["rol_activo"]
                and usuario["rol_id"] == rol_elegido):
            _iniciar_sesion(usuario)
            models.registrar_acceso(usuario["id"])
            auditoria.registrar("login", "Inició sesión.", "usuario", usuario["id"], usuario=usuario)
            if usuario["debe_cambiar_password"]:
                return redirect(url_for("auth.cambiar_password"))
            inicio = permisos.endpoint_de_inicio(models.permisos_efectivos(usuario))
            return redirect(seguridad.url_segura(siguiente) or url_for(inicio))

        # La pantalla da un mensaje genérico (no revela qué falló); la bitácora, que solo ve el
        # Gerente, sí guarda el motivo real para poder investigar intentos sospechosos.
        if usuario is None:
            motivo = "usuario inexistente"
        elif not password_correcta:
            motivo = "contraseña incorrecta"
        elif not (usuario["activo"] and usuario["rol_activo"]):
            motivo = "cuenta o rol desactivado"
        else:
            motivo = "rol elegido distinto al de la cuenta"
        nombre_en_bitacora = auditoria.usuario_valido_para_bitacora(usuario_ingresado)
        auditoria.registrar(
            "login_fallido", f"Intento de inicio de sesión fallido con el usuario «{nombre_en_bitacora}».",
            "usuario", usuario["id"] if usuario else None, {"motivo": motivo},
        )
        flash(MENSAJE_LOGIN_FALLIDO, "error")

    return render_template(
        "auth/login.html",
        roles=roles,
        sin_usuarios=models.contar_usuarios() == 0,
        usuario_ingresado=usuario_ingresado,
        rol_elegido=rol_elegido,
        siguiente=siguiente,
    )


@auth_bp.route("/sin-acceso")
def sin_acceso():
    return render_template(
        "auth/acceso_denegado.html",
        mensaje="Tu rol todavía no tiene módulos habilitados. Pide al Gerente que te asigne permisos.",
        sin_modulos=True,
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    auditoria.registrar("logout", "Cerró sesión.", "usuario", g.usuario["id"])
    session.clear()
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("auth.login"))


# --- Cambio de contraseña -----------------------------------------------------------------

@auth_bp.route("/cambiar-password", methods=["GET", "POST"])
def cambiar_password():
    usuario = g.usuario
    forzado = bool(usuario["debe_cambiar_password"])

    if request.method == "POST":
        actual = request.form.get("password_actual") or ""
        nueva = request.form.get("password_nueva") or ""
        confirmacion = request.form.get("password_confirmacion") or ""

        errores = []
        if not check_password_hash(usuario["password_hash"], actual):
            errores.append("La contraseña actual no es correcta.")
        errores.extend(seguridad.errores_password(nueva, usuario["usuario"]))
        if nueva and nueva == actual:
            errores.append("La nueva contraseña debe ser distinta a la actual.")
        if nueva != confirmacion:
            errores.append("La confirmación no coincide con la nueva contraseña.")

        if errores:
            for error in errores:
                flash(error, "error")
        else:
            models.actualizar_password(usuario["id"], nueva)
            auditoria.registrar("password_cambiada", "Cambió su propia contraseña.", "usuario", usuario["id"])
            flash("Contraseña actualizada correctamente.", "success")
            return redirect(url_for("dashboard.inicio"))

    return render_template("auth/cambiar_password.html", forzado=forzado)
