from flask import Flask

from app import db
from app.config import Config

# Mensajes de arranque según el resultado de sembrar_datos_base (ver app/auth/models.py).
_MENSAJES_SIEMBRA = {
    "ok_creado": "Primer Gerente creado desde ADMIN_USUARIO. Su contraseña es temporal: deberá cambiarla al ingresar.",
    "sin_credenciales": "No hay ningún Gerente y faltan ADMIN_USUARIO / ADMIN_PASSWORD en el .env: nadie podrá iniciar sesión.",
    "password_invalida": "ADMIN_PASSWORD no cumple la política (mínimo 8 caracteres con letras y números): no se creó el Gerente.",
    "usuario_en_uso": "ADMIN_USUARIO ya pertenece a otra cuenta que no es Gerente activo: no se creó el Gerente.",
}


def create_app():
    """Configuración inicial de la app, conexión a Postgres y registro de Blueprints."""
    app = Flask(__name__)
    app.config.from_object(Config)

    if app.config["SECRET_KEY"] == "dev-secret-key":
        app.logger.warning("SECRET_KEY usa el valor de desarrollo: define uno propio en el .env.")

    db.init_app(app)

    from app.auth.routes import auth_bp
    from app.auth.routes_config import config_bp
    from app.auditoria.routes import auditoria_bp
    from app.inventario.routes import inventario_bp
    from app.ventas.routes import ventas_bp
    from app.finanzas.routes import finanzas_bp
    from app.dashboard.routes import dashboard_bp

    # `auth` se registra primero: su guardia (before_app_request) protege TODAS las rutas.
    app.register_blueprint(auth_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(auditoria_bp)
    app.register_blueprint(inventario_bp)
    app.register_blueprint(ventas_bp)
    app.register_blueprint(finanzas_bp)
    app.register_blueprint(dashboard_bp)

    with app.app_context():
        try:
            from app.auth import models as modelos_auth

            # `auth` va PRIMERO: desde la Fase 4, entradas_canal/despostes/ventas/egresos
            # tienen un usuario_id que referencia a usuarios(id) para trazabilidad.
            modelos_auth.crear_tabla()
            from app.auditoria import models as modelos_auditoria

            modelos_auditoria.crear_tabla()  # referencia a usuarios(id): va justo después de auth
            estado = modelos_auth.sembrar_datos_base(
                app.config["ADMIN_USUARIO"], app.config["ADMIN_PASSWORD"], app.config["ADMIN_NOMBRE"]
            )
            if estado in _MENSAJES_SIEMBRA:
                nivel = app.logger.info if estado == "ok_creado" else app.logger.warning
                nivel(_MENSAJES_SIEMBRA[estado])
        except Exception as exc:  # pragma: no cover
            app.logger.error("No se pudo preparar la autenticación: %s", exc)

        try:
            from app.inventario import models as modelos_inventario
            from app.ventas import models as modelos_ventas
            from app.finanzas import models as modelos_finanzas

            # Orden importa: `ventas` referencia la tabla `productos` de `inventario`,
            # y `finanzas` lee (sin FK) la tabla `ventas` para el cuadre diario.
            modelos_inventario.crear_tabla()
            modelos_ventas.crear_tabla()
            modelos_finanzas.crear_tabla()
        except Exception as exc:  # pragma: no cover - la BD puede no estar disponible aún
            app.logger.warning("No se pudieron verificar/crear las tablas: %s", exc)

    @app.route("/")
    def index():
        from flask import redirect

        from app.auth.routes import destino_inicio

        return redirect(destino_inicio())  # la primera pantalla a la que el usuario tiene acceso

    return app
