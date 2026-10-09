import psycopg2
import psycopg2.extras
from flask import current_app, g


def get_db():
    """Devuelve una conexión a PostgreSQL reutilizable dentro del contexto de la request."""
    if "db" not in g:
        g.db = psycopg2.connect(
            host=current_app.config["DB_HOST"],
            port=current_app.config["DB_PORT"],
            dbname=current_app.config["DB_NAME"],
            user=current_app.config["DB_USER"],
            password=current_app.config["DB_PASSWORD"],
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    """Registra el cierre automático de la conexión al finalizar cada request."""
    app.teardown_appcontext(close_db)
